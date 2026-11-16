#!/usr/bin/env python3
"""karte - Projektkarte: prueft und pflegt Modulnotizen unter docs/karte/.

Jede Notiz speichert einen Fingerabdruck der Dateien, die sie abdeckt. Das
Werkzeug meldet veraltete Notizen, unkartierte Dateien und tote Verweise und
laeuft auch als Claude-Code-Hook (SessionStart, SubagentStart, Stop,
SubagentStop). Nur Standardbibliothek.
"""

import datetime
import functools
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections import namedtuple

NOTES_DIR = "docs/karte/module"
IGNORE_FILE = "docs/karte/ignoriert.txt"
DECISIONS_FILE = "docs/karte/ENTSCHEIDUNGEN.md"
ALWAYS_IGNORED = (".git/", ".claude/", "docs/karte/")
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
PLACEHOLDER = "- …"
MAX_NOTE_CHARS = 6000
USAGE = ("Aufruf: python3 tools/karte.py status | pruefe | stempel <modul>... | "
         "test <modul>... | neu <modul> <glob>... [--zweck TEXT] [--tests CMD]")
COMMANDS_LINE = ("Befehle: python3 tools/karte.py status | pruefe | stempel <modul> | "
                 "test <modul> | neu <modul> <glob>...")

Problem = namedtuple("Problem", "kind key subject text")


# --------------------------------------------------------------------------
# Hilfen: Dateien, Git
# --------------------------------------------------------------------------

def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8", "surrogateescape")


def write_text(path, text):
    with open(path, "wb") as f:
        f.write(text.encode("utf-8", "surrogateescape"))


def split_lines(text):
    """Zeilen inklusive Zeilenende, nur an \\n getrennt (Bytes bleiben erhalten)."""
    return re.findall(r"[^\n]*\n|[^\n]+", text)


def line_content(line):
    return line.rstrip("\r\n")


def run_git(cwd, args):
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def git_root(cwd):
    out = run_git(cwd, ["rev-parse", "--show-toplevel"])
    if not out:
        return None
    return os.fsdecode(out).rstrip("\n") or None


# --------------------------------------------------------------------------
# Glob-Teilmenge -> regulaerer Ausdruck
# --------------------------------------------------------------------------

class GlobError(ValueError):
    pass


def expand_braces(pattern, limit=256):
    start = pattern.find("{")
    close = pattern.find("}")
    if start == -1:
        if close != -1:
            raise GlobError("unausgewogene geschweifte Klammern")
        return [pattern]
    if close == -1 or close < start:
        raise GlobError("unausgewogene geschweifte Klammern")
    inner = pattern[start + 1:close]
    if "{" in inner:
        raise GlobError("verschachtelte geschweifte Klammern")
    tails = expand_braces(pattern[close + 1:], limit)
    out = [pattern[:start] + alt + tail for alt in inner.split(",") for tail in tails]
    if len(out) > limit:
        raise GlobError("zu viele Alternativen")
    return out


def translate_class(body):
    negated = body.startswith(("!", "^"))
    chars = body[1:] if negated else body
    if not chars:
        raise GlobError("leere Zeichenklasse")
    escaped = "".join("\\" + c if c in "\\[]&~|" else c for c in chars)
    return "[^/" + escaped + "]" if negated else "[" + escaped + "]"


def translate_segment(seg):
    if "**" in seg:
        raise GlobError("`**` ist nur als ganzes Pfadsegment erlaubt")
    out = []
    i = 0
    while i < len(seg):
        c = seg[i]
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = i + 1
            if j < len(seg) and seg[j] in "!^":
                j += 1
            if j < len(seg) and seg[j] == "]":
                j += 1
            while j < len(seg) and seg[j] != "]":
                j += 1
            if j >= len(seg):
                raise GlobError("unausgewogene eckige Klammer [")
            out.append(translate_class(seg[i + 1:j]))
            i = j
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def translate_alternative(alt, anchored):
    if not anchored and "/" not in alt:
        alt = "**/" + alt
    segs = alt.split("/")
    if any(s == "" for s in segs):
        raise GlobError("leeres Pfadsegment")
    parts = []
    for n, seg in enumerate(segs):
        last = n == len(segs) - 1
        if seg == "**":
            parts.append(".+" if last else "(?:[^/]+/)*")
        else:
            parts.append(translate_segment(seg) + ("" if last else "/"))
    return "".join(parts)


@functools.lru_cache(maxsize=1024)
def _compile_cached(pattern):
    p = pattern.strip()
    anchored = p.startswith("/")
    if anchored:
        p = p[1:]
    if not p:
        raise GlobError("leeres Muster")
    alts = [translate_alternative(a, anchored) for a in expand_braces(p)]
    try:
        return re.compile("|".join("(?:" + a + ")" for a in alts))
    except re.error as e:
        raise GlobError("ungültiges Muster (%s)" % e)


def compile_glob(pattern, root=None):
    """Kompiliert ein Muster; mit root wird zusaetzlich 'Verzeichnis ohne Wildcard' geprueft."""
    regex = _compile_cached(pattern)
    if root is not None:
        p = pattern.strip()
        p = p[1:] if p.startswith("/") else p
        if not re.search(r"[*?\[{]", p) and os.path.isdir(os.path.join(root, p)):
            raise GlobError("`%s` ist ein Verzeichnis, stattdessen `%s/**` verwenden" % (p, p))
    return regex


def match_files(proj, patterns):
    """-> (passende Dateien, [(muster, grund)]) fuer eine Liste von Globs."""
    regexes, errors = [], []
    for g in patterns:
        try:
            regexes.append(compile_glob(g, proj.root))
        except GlobError as e:
            errors.append((g, str(e)))
    matched = [f for f in proj.files if any(r.fullmatch(f) for r in regexes)]
    return matched, errors


# --------------------------------------------------------------------------
# Frontmatter
# --------------------------------------------------------------------------

KEY_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)[ \t]*:(?:[ \t]+(.*)|[ \t]*)")
ITEM_RE = re.compile(r"\s*-\s+(.*)")
TESTLAUF_RE = re.compile(r"(gruen|rot) ([0-9a-f]{12}) (\d{4}-\d{2}-\d{2})")


def yaml_quote(value):
    value = value.replace("\r", " ").replace("\n", " ")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_scalar(raw):
    s = raw.strip()
    if s.startswith('"'):
        out, i = [], 1
        while i < len(s):
            c = s[i]
            if c == "\\" and i + 1 < len(s):
                out.append({"n": "\n", "t": "\t"}.get(s[i + 1], s[i + 1]))
                i += 2
                continue
            if c == '"':
                break
            out.append(c)
            i += 1
        return "".join(out)
    if s.startswith("'"):
        out, i = [], 1
        while i < len(s):
            if s[i] == "'":
                if s[i + 1:i + 2] == "'":
                    out.append("'")
                    i += 2
                    continue
                break
            out.append(s[i])
            i += 1
        return "".join(out)
    return re.sub(r"\s+#.*$", "", s).strip()


def split_items(s):
    """Trennt an Kommas ausserhalb von Anfuehrungszeichen und {}; Teile werden entquotet."""
    items, cur, quote, depth, esc = [], [], None, 0, False
    for c in s:
        if quote:
            cur.append(c)
            if esc:
                esc = False
            elif c == "\\" and quote == '"':
                esc = True
            elif c == quote:
                quote = None
        elif c in "\"'" and not "".join(cur).strip():
            quote = c
            cur.append(c)
        elif c == "{":
            depth += 1
            cur.append(c)
        elif c == "}":
            depth = max(0, depth - 1)
            cur.append(c)
        elif c == "," and depth == 0:
            items.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    items.append("".join(cur))
    return [parse_scalar(i) for i in items if i.strip()]


def find_frontmatter(lines):
    """Index der schliessenden --- Zeile oder None."""
    if not lines or line_content(lines[0]) != "---":
        return None
    for i in range(1, len(lines)):
        if line_content(lines[i]) == "---":
            return i
    return None


def parse_frontmatter(fm_lines):
    meta, current = {}, None
    for raw in fm_lines:
        line = line_content(raw)
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = KEY_RE.fullmatch(line)
        if m:
            key, value = m.group(1), (m.group(2) or "").strip()
            current = None
            if value == "" or value.startswith("#"):
                meta[key] = []
                current = key
            elif value.startswith("["):
                end = value.rfind("]")
                meta[key] = split_items(value[1:end] if end > 0 else value[1:])
            else:
                meta[key] = parse_scalar(value)
            continue
        item = ITEM_RE.fullmatch(line)
        if item and current is not None:
            meta[current].append(parse_scalar(item.group(1)))
        else:
            current = None
    return meta


def meta_str(meta, key):
    v = meta.get(key)
    return v.strip() if isinstance(v, str) else ""


def meta_list(meta, key):
    v = meta.get(key)
    if v is None:
        return []
    items = v if isinstance(v, list) else split_items(v)
    return [i.strip() for i in items if i.strip()]


def set_frontmatter_value(path, key, value):
    """Aendert nur die Zeile `key` (oder fuegt sie vor dem schliessenden --- ein)."""
    lines = split_lines(read_text(path))
    close = find_frontmatter(lines)
    if close is None:
        raise ValueError("Frontmatter fehlt")
    new = "%s: %s" % (key, yaml_quote(value))
    for i in range(1, close):
        m = KEY_RE.fullmatch(line_content(lines[i]))
        if m and m.group(1) == key:
            lines[i] = new + lines[i][len(line_content(lines[i])):]
            break
    else:
        eol = lines[close][len(line_content(lines[close])):] or "\n"
        lines.insert(close, new + eol)
    write_text(path, "".join(lines))


class Note:
    def __init__(self, name, path, text):
        self.name, self.path = name, path
        self.lines = split_lines(text)
        self.fm_end = find_frontmatter(self.lines)
        ok = self.fm_end is not None
        self.meta = parse_frontmatter(self.lines[1:self.fm_end]) if ok else {}
        self.body_lines = self.lines[self.fm_end + 1:] if ok else []
        self.body = "".join(self.body_lines)
        self.paths = meta_list(self.meta, "paths")
        self.zweck = meta_str(self.meta, "zweck")
        self.tests = meta_str(self.meta, "tests")
        self.stand = meta_str(self.meta, "stand")
        m = TESTLAUF_RE.fullmatch(meta_str(self.meta, "testlauf"))
        self.testlauf = m.groups() if m else None
        self.errors, self.hints = [], []
        self.matched, self.fingerprint, self.drift = [], None, None

    @property
    def zweck_ok(self):
        return bool(self.zweck) and self.zweck != "…"

    @property
    def readable(self):
        return self.fm_end is not None and bool(self.paths) and self.zweck_ok


def load_notes(root):
    directory = os.path.join(root, NOTES_DIR)
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    notes = []
    for fn in names:
        path = os.path.join(directory, fn)
        if not fn.endswith(".md") or not os.path.isfile(path):
            continue
        try:
            text = read_text(path)
        except OSError:
            text = ""
        notes.append(Note(fn[:-3], path, text))
    return notes


# --------------------------------------------------------------------------
# Projekt: Dateiinventar und Fingerabdruecke
# --------------------------------------------------------------------------

class Projekt:
    def __init__(self, root):
        self.root = root
        self._digests = {}
        self.files = self._inventory()

    def _inventory(self):
        out = run_git(self.root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
        names = set()
        for raw in (out or b"").split(b"\0"):
            if not raw:
                continue
            rel = os.fsdecode(raw)
            full = os.path.join(self.root, rel)
            if rel.startswith(ALWAYS_IGNORED) or not os.path.lexists(full):
                continue
            if os.path.isdir(full) and not os.path.islink(full):  # Submodul/Gitlink
                continue
            names.add(rel)
        return sorted(names)

    def digest(self, rel):
        if rel not in self._digests:
            self._digests[rel] = self._compute_digest(os.path.join(self.root, rel))
        return self._digests[rel]

    @staticmethod
    def _compute_digest(full):
        try:
            if os.path.islink(full):
                data = os.fsencode(os.readlink(full))
            elif stat.S_ISREG(os.stat(full).st_mode):
                with open(full, "rb") as f:
                    data = f.read().replace(b"\r\n", b"\n")
            else:
                data = b"unlesbar"
        except OSError:
            data = b"unlesbar"
        return hashlib.sha256(data).hexdigest()

    def fingerprint(self, matched):
        h = hashlib.sha256()
        for rel in sorted(matched):
            h.update(rel.encode("utf-8", "surrogateescape") + b"\0" + self.digest(rel).encode() + b"\n")
        return h.hexdigest()[:12]


def read_ignore(root):
    patterns, errors = [], []
    try:
        text = read_text(os.path.join(root, IGNORE_FILE))
    except OSError:
        return patterns, errors
    for raw in split_lines(text):
        line = line_content(raw).strip()
        if not line or line.startswith("#"):
            continue
        try:
            patterns.append(compile_glob(line, root))
        except GlobError as e:
            errors.append("ungültiges Muster `%s`: %s" % (line, e))
    return patterns, errors


# --------------------------------------------------------------------------
# Verweispruefung
# --------------------------------------------------------------------------

SPAN_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")


def check_pointer(root, entries, span):
    if re.search(r"\s", span) or any(c in span for c in "*<>{}…") or span.startswith(("http", "-", "/", "~", "$")):
        return None
    path, sep, suffix = span.rpartition(":")
    if not sep:
        path, suffix = span, None
    if not path:
        return None
    first, last = path.split("/")[0], path.split("/")[-1]
    if not (first in entries or ("/" in path and re.fullmatch(r"[^/]*\.[A-Za-z0-9]{1,5}", last))):
        return None
    full = os.path.join(root, path)
    if not os.path.lexists(full):
        return "toter Verweis `%s`" % span
    if suffix and not suffix.isdigit() and os.path.isfile(full):
        ident = suffix[:-2] if suffix.endswith("()") else suffix
        ident = ident.rsplit(".", 1)[-1]
        if re.fullmatch(r"[A-Za-z_]\w*", ident):
            try:
                if ident not in read_text(full):
                    return "Symbol nicht gefunden `%s`" % span
            except OSError:
                return None
    return None


def pointer_errors(root, body):
    try:
        entries = set(os.listdir(root))
    except OSError:
        entries = set()
    errors, in_fence = [], False
    for line in split_lines(body):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for span in SPAN_RE.findall(line):
            err = check_pointer(root, entries, span)
            if err and err not in errors:
                errors.append(err)
    return errors


# --------------------------------------------------------------------------
# Analyse
# --------------------------------------------------------------------------

def check_note(proj, note):
    errs = note.errors
    if not NAME_RE.fullmatch(note.name):
        errs.append("ungültiger Modulname")
    if note.fm_end is None:
        errs.append("Frontmatter fehlt oder ist nicht lesbar")
        return
    if not note.paths:
        errs.append("Pflichtfeld fehlt: paths")
    if not note.zweck_ok:
        errs.append("Pflichtfeld fehlt: zweck")
    note.matched, bad = match_files(proj, note.paths)
    for glob, reason in bad:
        errs.append("ungültiges Muster `%s`: %s" % (glob, reason))
    if note.paths and not bad and not note.matched:
        errs.append("paths treffen keine Datei")
    if any(line_content(l) == PLACEHOLDER for l in note.body_lines):
        errs.append("Platzhalter nicht ausgefüllt")
    errs.extend(pointer_errors(proj.root, note.body))
    note.fingerprint = proj.fingerprint(note.matched)
    if not note.stand:
        note.drift = "UNGESTEMPELT"
    elif note.stand != note.fingerprint:
        note.drift = "VERALTET"
    if len(note.body) > MAX_NOTE_CHARS:
        note.hints.append("Notiz länger als %d Zeichen" % MAX_NOTE_CHARS)


class Analyse:
    def __init__(self, proj):
        self.proj = proj
        self.notes = load_notes(proj.root)
        ignore, ignore_errors = read_ignore(proj.root)
        covered = []
        for note in self.notes:
            check_note(proj, note)
            covered.extend(compile_glob_safe(g) for g in note.paths)
        covered = [r for r in covered if r]
        self.unmapped = [f for f in proj.files
                         if not any(r.fullmatch(f) for r in ignore)
                         and not any(r.fullmatch(f) for r in covered)]
        self.problems = self._problems(ignore_errors)

    def _problems(self, ignore_errors):
        groups = {k: [] for k in ("FEHLER", "UNGESTEMPELT", "VERALTET", "UNKARTIERT", "HINWEIS")}
        for note in self.notes:
            for e in note.errors:
                groups["FEHLER"].append(Problem("FEHLER", "fehler:%s:%s" % (note.name, e), note.name, e))
            if note.drift == "UNGESTEMPELT":
                groups["UNGESTEMPELT"].append(
                    Problem("UNGESTEMPELT", "ungestempelt:" + note.name, note.name, ""))
            elif note.drift == "VERALTET":
                groups["VERALTET"].append(
                    Problem("VERALTET", "veraltet:%s:%s" % (note.name, note.fingerprint), note.name, ""))
            for h in note.hints:
                groups["HINWEIS"].append(Problem("HINWEIS", "hinweis:%s:%s" % (note.name, h), note.name, h))
        for e in ignore_errors:
            groups["FEHLER"].append(Problem("FEHLER", "fehler:ignoriert:" + e, "ignoriert", e))
        for path in self.unmapped:
            groups["UNKARTIERT"].append(Problem("UNKARTIERT", "unkartiert:" + path, path, ""))
        return [p for kind in groups for p in groups[kind]]

    def tracked(self):
        return [p for p in self.problems if p.kind != "HINWEIS"]


def compile_glob_safe(pattern):
    try:
        return compile_glob(pattern)
    except GlobError:
        return None


# --------------------------------------------------------------------------
# Status-Text
# --------------------------------------------------------------------------

DECISION_RE = re.compile(r"##[ \t]+(E-(\d+))[ \t]+·[ \t]+\S+[ \t]+·[ \t]+(.+?)[ \t]*")


def read_decisions(root):
    try:
        text = read_text(os.path.join(root, DECISIONS_FILE))
    except OSError:
        return []
    found = []
    for raw in split_lines(text):
        m = DECISION_RE.fullmatch(line_content(raw))
        if m:
            found.append((int(m.group(2)), "%s %s" % (m.group(1), m.group(3))))
    found.sort(key=lambda d: -d[0])
    return [label for _, label in found]


def test_state(note):
    if not note.tests:
        return "ohne Tests"
    if not note.testlauf:
        return "Tests nie gelaufen"
    result, fp, _ = note.testlauf
    label = "Tests grün" if result == "gruen" else "Tests rot"
    return label if fp == note.fingerprint else label + "@alt"


def capped(items, limit, sep, more):
    shown = sep.join(items[:limit])
    if len(items) > limit:
        shown += more % (len(items) - limit)
    return shown


def status_text(an):
    notes = an.notes
    count = "%d Module" % len(notes) if notes else "leer"
    lines = ["Projektkarte: %s · Notizen: %s/<modul>.md" % (count, NOTES_DIR)]
    for note in notes[:40]:
        if not note.readable:
            lines.append("- %s · FEHLER" % note.name)
            continue
        parts = [note.name, " ".join(note.paths), note.zweck]
        if note.drift:
            parts.append(note.drift)
        parts.append(test_state(note))
        lines.append("- " + " · ".join(parts))
    if len(notes) > 40:
        lines.append("… +%d weitere" % (len(notes) - 40))
    decisions = read_decisions(an.proj.root)
    if decisions:
        lines.append("Entscheidungen (%s): %s" % (DECISIONS_FILE, capped(decisions, 8, "; ", " … +%d")))
    if an.unmapped:
        lines.append("Unkartiert (%d): %s" % (len(an.unmapped), capped(an.unmapped, 10, ", ", ", … +%d")))
    errors = ["%s: %s" % (p.subject, p.text) for p in an.problems if p.kind == "FEHLER"]
    if errors:
        lines.append("Fehler (%d): %s" % (len(errors), capped(errors, 10, "; ", "; … +%d")))
    lines.append(COMMANDS_LINE)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Befehle
# --------------------------------------------------------------------------

def cmd_status(root, args):
    print(status_text(Analyse(Projekt(root))))
    return 0


def cmd_pruefe(root, args):
    problems = Analyse(Projekt(root)).problems
    for p in problems:
        if p.kind in ("FEHLER", "HINWEIS"):
            print("%s %s: %s" % (p.kind, p.subject, p.text))
        else:
            print("%s %s" % (p.kind, p.subject))
    if any(p.kind != "HINWEIS" for p in problems):
        return 1
    print("Karte ist auf Stand.")
    return 0


def cmd_stempel(root, args):
    alle = "--alle" in args
    names = [a for a in args if a != "--alle"]
    if not alle and not names:
        print(USAGE)
        return 2
    an = Analyse(Projekt(root))
    by_name = {n.name: n for n in an.notes}
    targets = sorted(by_name) if alle else names
    failed = False
    for name in targets:
        note = by_name.get(name)
        if note is None:
            print("unbekanntes Modul: %s" % name)
            failed = True
        elif note.errors:
            print("nicht gestempelt: %s (%s)" % (name, note.errors[0]))
            failed = True
        else:
            set_frontmatter_value(note.path, "stand", note.fingerprint)
            print("gestempelt: %s %s" % (name, note.fingerprint))
    return 1 if failed else 0


def cmd_neu(root, args):
    zweck, tests, pos, i = None, None, [], 0
    while i < len(args):
        a = args[i]
        if a in ("--zweck", "--tests"):
            i += 1
            if i >= len(args):
                print(USAGE)
                return 2
            value = args[i]
        elif a.startswith(("--zweck=", "--tests=")):
            a, value = a.split("=", 1)
        else:
            pos.append(a)
            i += 1
            continue
        if a == "--zweck":
            zweck = value
        else:
            tests = value
        i += 1
    if len(pos) < 2:
        print(USAGE)
        return 2
    name, globs = pos[0], pos[1:]
    if not NAME_RE.fullmatch(name):
        print("ungültiger Modulname: %s" % name)
        return 1
    rel = "%s/%s.md" % (NOTES_DIR, name)
    path = os.path.join(root, rel)
    if os.path.lexists(path):
        print("Notiz existiert bereits: %s" % rel)
        return 1
    matched, bad = match_files(Projekt(root), globs)
    for glob, reason in bad:
        print("ungültiges Muster `%s`: %s" % (glob, reason))
    if bad:
        return 1
    if not matched:
        print("paths treffen keine Datei")
        return 1
    head = ["---", "paths:"] + ["  - " + yaml_quote(g) for g in globs]
    head.append("zweck: " + yaml_quote(zweck if zweck else "…"))
    if tests:
        head.append("tests: " + yaml_quote(tests))
    head.append("---")
    skeleton = ["# " + name, "", "## Einstieg", PLACEHOLDER, "", "## Verträge und Fallstricke",
                PLACEHOLDER, "", "## Tests", PLACEHOLDER, "", "## Sackgassen", "- (keine)"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_text(path, "\n".join(head + skeleton) + "\n")
    print("angelegt: %s" % rel)
    return 0


def run_shell(cmd, cwd, timeout):
    """-> (exitcode oder None bei Zeitlimit, Ausgabe, Sekunden)"""
    start = time.time()
    proc = subprocess.Popen(cmd, shell=True, cwd=cwd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    code = None
    try:
        out, _ = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        try:
            out, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out = b""
    return code, out.decode("utf-8", "replace"), time.time() - start


def cmd_test(root, args):
    timeout, alle, names, i = 600.0, False, [], 0
    while i < len(args):
        a = args[i]
        if a == "--alle":
            alle = True
        elif a == "--timeout" or a.startswith("--timeout="):
            try:
                if a == "--timeout":
                    i += 1
                    timeout = float(args[i])
                else:
                    timeout = float(a.split("=", 1)[1])
            except (IndexError, ValueError):
                print(USAGE)
                return 2
        elif a.startswith("--"):
            print(USAGE)
            return 2
        else:
            names.append(a)
        i += 1
    if not alle and not names:
        print(USAGE)
        return 2
    by_name = {n.name: n for n in load_notes(root)}
    ok = True
    for name in (sorted(by_name) if alle else names):
        note = by_name.get(name)
        if note is None:
            print("unbekanntes Modul: %s" % name)
            ok = False
        elif not note.tests:
            if not alle:
                print("ohne Tests: %s" % name)
                ok = False
        else:
            ok = run_module_tests(root, note, timeout) and ok
    return 0 if ok else 1


def run_module_tests(root, note, timeout):
    code, out, secs = run_shell(note.tests, root, timeout)
    green = code == 0
    if green:
        print("GRÜN %s (%.1fs)" % (note.name, secs))
    else:
        tail = out.splitlines()[-40:]
        if tail:
            print("\n".join(tail))
        reason = "Zeitlimit" if code is None else "exit %d" % code
        print("ROT %s (%s, %.1fs)" % (note.name, reason, secs))
    fresh = load_notes(root)
    proj = Projekt(root)
    current = next((n for n in fresh if n.name == note.name), None)
    if current is not None and current.fm_end is not None:
        matched, _ = match_files(proj, current.paths)
        value = "%s %s %s" % ("gruen" if green else "rot", proj.fingerprint(matched),
                              datetime.date.today().isoformat())
        set_frontmatter_value(current.path, "testlauf", value)
    return green


# --------------------------------------------------------------------------
# Hook
# --------------------------------------------------------------------------

def state_path(session_id):
    clean = re.sub(r"[^A-Za-z0-9_-]", "", str(session_id or ""))
    return os.path.join(tempfile.gettempdir(), "karte-%s.json" % clean)


def load_state(path):
    """-> (basis: list, gemeldet: dict wer -> list). Tolerant gegen fehlende/kaputte Dateien."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return [], {}
    if not isinstance(data, dict):
        return [], {}
    basis = data.get("basis")
    basis = [k for k in basis if isinstance(k, str)] if isinstance(basis, list) else []
    raw = data.get("gemeldet")
    gemeldet = {}
    if isinstance(raw, dict):
        for who, keys in raw.items():
            if isinstance(keys, list):
                gemeldet[str(who)] = [k for k in keys if isinstance(k, str)]
    return basis, gemeldet


def save_state(path, basis, gemeldet):
    fd, tmp = tempfile.mkstemp(prefix=".karte-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"basis": basis, "gemeldet": gemeldet}, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def bullet(p):
    if p.kind == "VERALTET":
        return ("- VERALTET %s: Code seit dem letzten Stempel geändert. Notiz %s/%s.md gegen den "
                "Code prüfen, anpassen, dann `python3 tools/karte.py stempel %s`"
                % (p.subject, NOTES_DIR, p.subject, p.subject))
    if p.kind == "UNGESTEMPELT":
        return "- UNGESTEMPELT %s: Notiz ausfüllen, dann `python3 tools/karte.py stempel %s`" % (
            p.subject, p.subject)
    if p.kind == "UNKARTIERT":
        return ("- UNKARTIERT %s: in `paths` einer Modulnotiz aufnehmen oder "
                "`python3 tools/karte.py neu <modul> <glob>`" % p.subject)
    return "- FEHLER %s: %s" % (p.subject, p.text)


def block_reason(new_problems):
    lines = ["Projektkarte nicht auf Stand (docs/karte). Neu in dieser Sitzung:"]
    lines += [bullet(p) for p in new_problems[:12]]
    if len(new_problems) > 12:
        lines.append("- … +%d weitere: python3 tools/karte.py pruefe" % (len(new_problems) - 12))
    lines.append("Bearbeite nur, was deine Änderungen betrifft; wer orchestriert, gibt das an `worker` ab. "
                 "Jedes Problem wird pro Sitzung nur einmal gemeldet.")
    return "\n".join(lines)


def background_work_running(payload):
    tasks = payload.get("background_tasks")
    return isinstance(tasks, list) and any(
        isinstance(t, dict) and t.get("type") in ("subagent", "workflow", "teammate") for t in tasks)


def reporter(event, payload):
    if event == "Stop":
        return "main"
    agent = payload.get("agent_id")
    return agent if isinstance(agent, str) and agent else "sub"


def hook_output(raw):
    """-> dict fuer stdout oder None. Darf Ausnahmen werfen (cmd_hook faengt sie)."""
    payload = json.loads(raw.decode("utf-8", "replace"))
    if not isinstance(payload, dict):
        return None
    event = payload.get("hook_event_name")
    if event not in ("SessionStart", "SubagentStart", "Stop", "SubagentStop"):
        return None
    if event in ("Stop", "SubagentStop") and payload.get("stop_hook_active"):
        return None
    if event == "Stop" and background_work_running(payload):
        return None
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not os.path.isdir(cwd):
        cwd = os.getcwd()
    root = git_root(cwd)
    if root is None:
        return None
    an = Analyse(Projekt(root))
    path = state_path(payload.get("session_id"))
    if event in ("SessionStart", "SubagentStart"):
        if event == "SessionStart" and not os.path.exists(path):
            save_state(path, [p.key for p in an.tracked()], {})
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": status_text(an)}}
    basis, gemeldet = load_state(path)
    who = reporter(event, payload)
    seen = set(basis) | set(gemeldet.get(who, []))
    new = [p for p in an.tracked() if p.key not in seen]
    if not new:
        return None
    gemeldet[who] = gemeldet.get(who, []) + [p.key for p in new]
    save_state(path, basis, gemeldet)
    return {"decision": "block", "reason": block_reason(new)}


def cmd_hook():
    try:
        out = hook_output(sys.stdin.buffer.read())
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()
    except Exception:  # der Hook darf nie eine Sitzung stoeren
        pass
    return 0


# --------------------------------------------------------------------------

COMMANDS = {"status": cmd_status, "pruefe": cmd_pruefe, "stempel": cmd_stempel,
            "neu": cmd_neu, "test": cmd_test}


def main(argv):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    if not argv:
        print(USAGE)
        return 2
    if argv[0] == "hook":
        return cmd_hook()
    if argv[0] not in COMMANDS:
        print(USAGE)
        return 2
    root = git_root(os.getcwd())
    if root is None:
        print("karte: kein Git-Repository", file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](root, argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
