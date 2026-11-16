"""Tests fuer tools/karte.py (nur Standardbibliothek, eigene Wegwerf-Repos)."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "karte.py"
_spec = importlib.util.spec_from_file_location("karte_under_test", TOOL)
karte = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(karte)

GOOD_BODY = "# m\n\n## Einstieg\n- Start in `src/a.py`\n\n## Sackgassen\n- (keine)\n"


def note_text(paths=('src/**',), zweck="Testzweck", body=GOOD_BODY, extra=""):
    lines = ["---", "paths:"] + ['  - "%s"' % p for p in paths] + ['zweck: "%s"' % zweck]
    if extra:
        lines.append(extra)
    return "\n".join(lines + ["---"]) + "\n" + body


class RepoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = os.path.realpath(self._tmp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True, stdout=subprocess.DEVNULL)

    def write(self, rel, content="x = 1\n", binary=False):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content if binary else content.encode("utf-8"))
        return path

    def read(self, rel):
        with open(os.path.join(self.repo, rel), "rb") as f:
            return f.read().decode("utf-8")

    def note(self, name, **kw):
        return self.write("docs/karte/module/%s.md" % name, note_text(**kw))

    def karte(self, *args, cwd=None, stdin=None):
        return subprocess.run([sys.executable, str(TOOL), *args], cwd=cwd or self.repo, input=stdin,
                              capture_output=True, text=True, encoding="utf-8")

    def lines(self, *args):
        return self.karte(*args).stdout.splitlines()

    def hook(self, event, session, stdin=None, **extra):
        payload = {"hook_event_name": event, "session_id": session, "cwd": self.repo}
        payload.update(extra)
        r = self.karte("hook", stdin=json.dumps(payload) if stdin is None else stdin)
        self.assertEqual(r.returncode, 0)
        return r.stdout

    def session(self):
        sid = "karte-test-" + uuid.uuid4().hex
        path = karte.state_path(sid)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return sid, path

    def clean_repo(self):
        """src/a.py + gestempelte Notiz, keine Abweichung."""
        self.write("src/a.py")
        self.note("m")
        self.assertEqual(self.karte("stempel", "m").returncode, 0)


class GlobTests(unittest.TestCase):
    def match(self, pattern, path):
        return karte.compile_glob(pattern).fullmatch(path) is not None

    def test_table(self):
        cases = [
            ("src/**", "src/a.py", True), ("src/**", "src/x/y.py", True), ("src/**", "srcx/a.py", False),
            ("*.md", "a.md", True), ("*.md", "x/y/a.md", True), ("/*.md", "a.md", True),
            ("/*.md", "x/a.md", False), ("src/**/*.py", "src/a.py", True),
            ("src/**/*.py", "src/x/y.py", True), ("src/**/*.py", "src/a.txt", False),
            ("src/*.py", "src/a.py", True), ("src/*.py", "src/x/y.py", False),
            ("{a,b}/*.py", "a/x.py", True), ("{a,b}/*.py", "b/x.py", True), ("{a,b}/*.py", "c/x.py", False),
            ("*.{py,md}", "d/x.md", True), ("**/x", "x", True), ("**/x", "a/b/x", True),
            ("a?c.py", "abc.py", True), ("a?c.py", "a/c.py", False), ("[ab].py", "a.py", True),
            ("[ab].py", "c.py", False), ("[!ab].py", "c.py", True), ("a.b", "axb", False),
        ]
        for pattern, path, expected in cases:
            with self.subTest(pattern=pattern, path=path):
                self.assertEqual(self.match(pattern, path), expected)

    def test_invalid_patterns(self):
        for bad in ["", "  ", "/", "a**b", "**a/x", "{a,{b,c}}", "{a,b", "a}", "[abc", "src/"]:
            with self.subTest(pattern=bad):
                with self.assertRaises(karte.GlobError):
                    karte.compile_glob(bad)

    def test_directory_without_wildcard_is_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "src"))
            with self.assertRaises(karte.GlobError) as cm:
                karte.compile_glob("src", d)
            self.assertIn("src/**", str(cm.exception))
            karte.compile_glob("src/**", d)


class FrontmatterTests(RepoCase):
    def parse(self, fm):
        return karte.Note("m", "m.md", "---\n%s\n---\nBody\n" % fm)

    def test_three_paths_spellings(self):
        block = self.parse('paths:\n  - "a/**"\n  - b/*.py\nzweck: x')
        inline = self.parse('paths: ["a/**", \'b/*.py\']\nzweck: x')
        comma = self.parse('paths: "a/**, b/*.py"\nzweck: x')
        bare = self.parse('paths: a/**, b/*.py\nzweck: x')
        for n in (block, inline, comma, bare):
            self.assertEqual(n.paths, ["a/**", "b/*.py"])

    def test_braces_survive_comma_splitting(self):
        self.assertEqual(self.parse('paths: "{a,b}/*.py, c/**"').paths, ["{a,b}/*.py", "c/**"])

    def test_scalars(self):
        n = self.parse("paths: a\nzweck: 'Es ist''s'\ntests: bare cmd # kommentar\nfoo: 1")
        self.assertEqual(n.zweck, "Es ist's")
        self.assertEqual(n.tests, "bare cmd")
        n = self.parse('paths: a\nzweck: "mit \\"Quote\\" und \\\\"')
        self.assertEqual(n.zweck, 'mit "Quote" und \\')

    def test_missing_frontmatter(self):
        self.assertIsNone(karte.Note("m", "m.md", "# nur Text\n").fm_end)
        self.assertIsNone(karte.Note("m", "m.md", "---\npaths: a\n").fm_end)

    def test_stamp_changes_only_stand_line(self):
        original = ("---\r\n# Kommentar\r\npaths: [ \"src/**\" ]   # hier\r\nzweck: Zweck\r\n"
                    "extra: 'bleibt'\r\n---\r\n# m\r\n\r\n- ok\r\n")
        self.write("src/a.py")
        self.write("docs/karte/module/m.md", original)
        self.assertEqual(self.karte("stempel", "m").returncode, 0)
        stamped = self.read("docs/karte/module/m.md")
        self.assertRegex(stamped, r'\r\nstand: "[0-9a-f]{12}"\r\n---\r\n')
        without = "\r\n".join(l for l in stamped.split("\r\n") if not l.startswith("stand:"))
        self.assertEqual(without, original)
        self.write("src/a.py", "x = 2\n")
        self.assertEqual(self.karte("stempel", "m").returncode, 0)
        again = self.read("docs/karte/module/m.md")
        old = stamped.split("\r\n")
        new = again.split("\r\n")
        self.assertEqual(len(old), len(new))
        diff = [i for i, (a, b) in enumerate(zip(old, new)) if a != b]
        self.assertEqual(len(diff), 1)
        self.assertTrue(new[diff[0]].startswith('stand: "'))

    def test_tool_writes_double_quoted_values(self):
        self.write("src/a.py")
        self.karte("neu", "m", "src/**", "--zweck", 'Sagt "hi" \\ da', "--tests", "echo \"x\"")
        text = self.read("docs/karte/module/m.md")
        self.assertIn('  - "src/**"', text)
        self.assertIn('zweck: "Sagt \\"hi\\" \\\\ da"', text)
        self.assertIn('tests: "echo \\"x\\""', text)
        n = karte.Note("m", "m.md", text)
        self.assertEqual(n.zweck, 'Sagt "hi" \\ da')
        self.assertEqual(n.tests, 'echo "x"')


class NeuAndStempelTests(RepoCase):
    def test_neu_skeleton_and_workflow(self):
        self.write("src/a.py")
        r = self.karte("neu", "m", "src/**")
        self.assertEqual(r.stdout.strip(), "angelegt: docs/karte/module/m.md")
        text = self.read("docs/karte/module/m.md")
        skeleton = ("# m\n\n## Einstieg\n- …\n\n## Verträge und Fallstricke\n- …\n\n## Tests\n- …\n\n"
                    "## Sackgassen\n- (keine)\n")
        self.assertTrue(text.endswith("---\n" + skeleton))
        self.assertIn('zweck: "…"', text)
        self.assertNotIn("stand", text)
        r = self.karte("pruefe")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FEHLER m: Platzhalter nicht ausgefüllt", r.stdout)
        self.assertIn("FEHLER m: Pflichtfeld fehlt: zweck", r.stdout)
        self.assertIn("UNGESTEMPELT m", r.stdout)
        r = self.karte("stempel", "m")
        self.assertEqual(r.returncode, 1)
        self.assertIn("nicht gestempelt: m (", r.stdout)
        self.write("docs/karte/module/m.md", note_text())
        r = self.karte("stempel", "m")
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"^gestempelt: m [0-9a-f]{12}\n$")
        r = self.karte("pruefe")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.splitlines()[-1], "Karte ist auf Stand.")

    def test_neu_errors(self):
        self.write("src/a.py")
        self.assertEqual(self.karte("neu", "Bad_Name", "src/**").returncode, 1)
        self.assertEqual(self.karte("neu", "m", "a**b").returncode, 1)
        self.assertEqual(self.karte("neu", "m", "src").returncode, 1)
        r = self.karte("neu", "m", "nix/**")
        self.assertEqual((r.returncode, r.stdout.strip()), (1, "paths treffen keine Datei"))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "docs/karte/module")))
        self.assertEqual(self.karte("neu", "m", "src/**").returncode, 0)
        r = self.karte("neu", "m", "src/**")
        self.assertEqual((r.returncode, r.stdout.strip()),
                         (1, "Notiz existiert bereits: docs/karte/module/m.md"))

    def test_stempel_unknown_and_partial_failure(self):
        self.clean_repo()
        self.write("docs/karte/module/bad.md", note_text(paths=("nix/**",)))
        r = self.karte("stempel", "bad", "m", "gibtsnicht")
        self.assertEqual(r.returncode, 1)
        self.assertIn("nicht gestempelt: bad (", r.stdout)
        self.assertIn("gestempelt: m ", r.stdout)
        self.assertIn("unbekanntes Modul: gibtsnicht", r.stdout)

    def test_invalid_module_name_and_missing_frontmatter(self):
        self.write("src/a.py")
        self.write("docs/karte/module/Bad.md", note_text())
        self.write("docs/karte/module/leer.md", "# nur Text\n")
        out = self.karte("pruefe").stdout
        self.assertIn("FEHLER Bad: ungültiger Modulname", out)
        self.assertIn("FEHLER leer: Frontmatter fehlt oder ist nicht lesbar", out)
        self.assertIn("- leer · FEHLER", self.karte("status").stdout)

    def test_invalid_glob_in_note(self):
        self.write("src/a.py")
        self.note("m", paths=("src/**", "a**b"))
        self.assertIn("FEHLER m: ungültiges Muster `a**b`", self.karte("pruefe").stdout)


class DriftTests(RepoCase):
    def test_edit_makes_stale_and_restamp_clears(self):
        self.clean_repo()
        self.write("src/a.py", "x = 2\n")
        r = self.karte("pruefe")
        self.assertEqual(r.returncode, 1)
        self.assertIn("VERALTET m", r.stdout)
        self.assertIn("· VERALTET ·", self.karte("status").stdout)
        self.karte("stempel", "m")
        self.assertEqual(self.karte("pruefe").stdout.splitlines()[-1], "Karte ist auf Stand.")

    def test_crlf_equals_lf(self):
        self.write("src/a.py", b"a = 1\nb = 2\n", binary=True)
        self.note("m")
        fp_lf = self.karte("stempel", "m").stdout.split()[-1]
        self.write("src/a.py", b"a = 1\r\nb = 2\r\n", binary=True)
        self.assertEqual(self.karte("pruefe").returncode, 0)
        self.assertEqual(self.karte("stempel", "m").stdout.split()[-1], fp_lf)

    def test_symlink_hashes_target_string(self):
        self.write("src/a.py")
        os.symlink("a.py", os.path.join(self.repo, "src/link.py"))
        self.note("m")
        self.karte("stempel", "m")
        os.remove(os.path.join(self.repo, "src/link.py"))
        os.symlink("other.py", os.path.join(self.repo, "src/link.py"))
        self.assertIn("VERALTET m", self.karte("pruefe").stdout)

    def test_unmapped_ignored_and_never_reported(self):
        self.clean_repo()
        self.write(".gitignore", "*.log\n")
        self.write("src/debug.log", "x")
        self.write("vendor/lib.py")
        self.write("other/b.py")
        self.write("docs/karte/ignoriert.txt", "# Kommentar\n\nvendor/**\n")
        self.write(".claude/settings.json", "{}")
        self.write("docs/karte/notes.txt", "x")
        out = self.karte("pruefe").stdout.splitlines()
        self.assertIn("UNKARTIERT other/b.py", out)
        self.assertIn("UNKARTIERT .gitignore", out)
        joined = "\n".join(out)
        for hidden in ("debug.log", "vendor", ".claude", "docs/karte"):
            self.assertNotIn(hidden, joined)

    def test_group_order(self):
        self.clean_repo()
        self.write("src/a.py", "x = 2\n")
        self.write("new/z.py")
        self.write("docs/karte/module/u.md", note_text(paths=("new/**",)))
        self.write("docs/karte/module/e.md", note_text(paths=("nix/**",)))
        kinds = [l.split()[0] for l in self.lines("pruefe")]
        self.assertEqual(kinds, sorted(kinds, key=["FEHLER", "UNGESTEMPELT", "VERALTET",
                                                    "UNKARTIERT", "HINWEIS"].index))

    def test_long_note_is_only_a_hint(self):
        self.write("src/a.py")
        self.note("m", body=GOOD_BODY + "x" * 6100 + "\n")
        self.karte("stempel", "m")
        r = self.karte("pruefe")
        self.assertEqual(r.returncode, 0)
        self.assertIn("HINWEIS m: Notiz länger als 6000 Zeichen", r.stdout)
        self.assertEqual(r.stdout.splitlines()[-1], "Karte ist auf Stand.")

    def test_repo_without_commits_and_subdirectory(self):
        self.clean_repo()
        sub = os.path.join(self.repo, "src")
        r = self.karte("pruefe", cwd=sub)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_no_git_repository(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.karte("status", cwd=d)
            self.assertEqual((r.returncode, r.stderr.strip()), (2, "karte: kein Git-Repository"))


class PointerTests(RepoCase):
    def errors(self, body):
        self.write("src/a.py", "def funktion():\n    pass\n\nclass Klasse:\n    def methode(self): pass\n")
        self.write("docs/guide.md", "x")
        self.note("m", body=body)
        return [l for l in self.lines("pruefe") if l.startswith("FEHLER")]

    def test_dead_and_existing_paths(self):
        out = self.errors("- `src/alt.py` und `src/a.py` und `src/`\n")
        self.assertEqual(out, ["FEHLER m: toter Verweis `src/alt.py`"])

    def test_dead_path_with_root_entry_first_segment(self):
        out = self.errors("- `src/gone` und `docs/guide.md`\n")
        self.assertEqual(out, ["FEHLER m: toter Verweis `src/gone`"])

    def test_symbols(self):
        out = self.errors("- `src/a.py:funktion` `src/a.py:Klasse.methode` `src/a.py:fehlt` "
                          "`src/a.py:42` `src/a.py:10-20`\n")
        self.assertEqual(out, ["FEHLER m: Symbol nicht gefunden `src/a.py:fehlt`"])

    def test_ignored_spans(self):
        body = ("- `application/json` `https://example.com/x.py` `src/*.py` `-x/y.py` `a b/c.py`\n"
                "- `/abs/pfad.py` `~/x.py` `$HOME/x.py`\n"
                "```\n`src/fence.py` src/fence2.py\n```\n")
        self.assertEqual(self.errors(body), [])

    def test_template_spans_ignored(self):
        self.assertEqual(self.errors("- `docs/karte/module/<modul>.md` `src/{a,b}.py` `src/…/x.py`\n"), [])

    def test_span_after_fence_is_checked_again(self):
        out = self.errors("```\nx\n```\n- `src/dead.py`\n")
        self.assertEqual(out, ["FEHLER m: toter Verweis `src/dead.py`"])


class TestCommandTests(RepoCase):
    def test_green_then_stale(self):
        self.write("src/a.py")
        self.note("m", extra='tests: "echo ok"')
        self.karte("stempel", "m")
        r = self.karte("test", "m")
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"^GRÜN m \(\d+\.\ds\)\n$")
        self.assertRegex(self.read("docs/karte/module/m.md"), r'testlauf: "gruen [0-9a-f]{12} \d{4}-\d\d-\d\d"')
        self.assertIn("· Tests grün", self.karte("status").stdout)
        self.assertNotIn("Tests grün@alt", self.karte("status").stdout)
        self.write("src/a.py", "x = 3\n")
        self.assertIn("Tests grün@alt", self.karte("status").stdout)

    def test_red_prints_tail_and_records(self):
        self.write("src/a.py")
        cmd = "for i in $(seq 1 60); do echo zeile$i; done; echo boom; exit 3"
        self.note("m", extra='tests: "%s"' % cmd)
        r = self.karte("test", "m")
        self.assertEqual(r.returncode, 1)
        out = r.stdout.splitlines()
        self.assertEqual(len(out), 41)
        self.assertEqual(out[-2], "boom")
        self.assertRegex(out[-1], r"^ROT m \(exit 3, \d+\.\ds\)$")
        self.assertNotIn("zeile1\n", r.stdout)
        self.assertIn('testlauf: "rot ', self.read("docs/karte/module/m.md"))
        self.assertIn("Tests rot", self.karte("status").stdout)

    def test_timeout(self):
        self.write("src/a.py")
        self.note("m", extra='tests: "sleep 30"')
        r = self.karte("test", "m", "--timeout", "1")
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout.strip(), r"ROT m \(Zeitlimit, \d+\.\ds\)$")

    def test_without_tests(self):
        self.clean_repo()
        r = self.karte("test", "m")
        self.assertEqual((r.returncode, r.stdout.strip()), (1, "ohne Tests: m"))
        r = self.karte("test", "--alle")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertIn("ohne Tests", self.karte("status").stdout)

    def test_never_run_state(self):
        self.write("src/a.py")
        self.note("m", extra='tests: "true"')
        self.assertIn("Tests nie gelaufen", self.karte("status").stdout)


class HookTests(RepoCase):
    def test_session_start_output_and_baseline(self):
        self.clean_repo()
        sid, path = self.session()
        out = json.loads(self.hook("SessionStart", sid))
        spec = out["hookSpecificOutput"]
        self.assertEqual(spec["hookEventName"], "SessionStart")
        self.assertIn("Projektkarte", spec["additionalContext"])
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            self.assertEqual(json.load(f), {"basis": [], "gemeldet": {}})

    def test_preexisting_drift_does_not_block(self):
        self.clean_repo()
        self.write("src/new.py")
        sid, _ = self.session()
        self.hook("SessionStart", sid)
        self.assertEqual(self.hook("Stop", sid), "")

    def test_new_drift_blocks_exactly_once(self):
        self.clean_repo()
        sid, _ = self.session()
        self.hook("SessionStart", sid)
        self.assertEqual(self.hook("Stop", sid), "")
        self.write("src/a.py", "x = 2\n")
        self.write("src/x.py")
        self.write("docs/karte/module/neu1.md", note_text(paths=("src/x.py",)))
        out = self.hook("Stop", sid)
        data = json.loads(out)
        self.assertEqual(out.count("\n"), 1)
        self.assertEqual(data["decision"], "block")
        reason = data["reason"]
        self.assertTrue(reason.startswith("Projektkarte nicht auf Stand (docs/karte). Neu in dieser Sitzung:\n"))
        self.assertIn("- VERALTET m: Code seit dem letzten Stempel geändert. Notiz docs/karte/module/m.md "
                      "gegen den Code prüfen, anpassen, dann `python3 tools/karte.py stempel m`", reason)
        self.assertIn("- UNGESTEMPELT neu1: Notiz ausfüllen, dann `python3 tools/karte.py stempel neu1`", reason)
        self.assertTrue(reason.endswith("Jedes Problem wird pro Sitzung nur einmal gemeldet."))
        self.assertEqual(self.hook("Stop", sid), "")
        self.assertEqual(self.hook("Stop", sid), "")

    def test_unmapped_bullet_and_cap(self):
        self.clean_repo()
        sid, _ = self.session()
        self.hook("SessionStart", sid)
        for i in range(15):
            self.write("lib/f%02d.py" % i)
        reason = json.loads(self.hook("Stop", sid))["reason"]
        self.assertIn("- UNKARTIERT lib/f00.py: in `paths` einer Modulnotiz aufnehmen oder "
                      "`python3 tools/karte.py neu <modul> <glob>`", reason)
        self.assertIn("- … +3 weitere: python3 tools/karte.py pruefe", reason)
        self.assertEqual(reason.count("\n- "), 13)

    def test_subagents_are_reported_separately(self):
        self.clean_repo()
        sid, _ = self.session()
        self.hook("SessionStart", sid)
        self.write("other/new.py")
        self.assertIn("block", self.hook("SubagentStop", sid, agent_id="a1"))
        self.assertIn("block", self.hook("SubagentStop", sid, agent_id="a2"))
        self.assertEqual(self.hook("SubagentStop", sid, agent_id="a1"), "")
        self.assertIn("block", self.hook("Stop", sid))
        self.assertEqual(self.hook("Stop", sid), "")

    def test_stop_waits_for_background_workers(self):
        self.clean_repo()
        sid, _ = self.session()
        self.hook("SessionStart", sid)
        self.write("other/new.py")
        busy = [{"id": "t1", "type": "subagent", "status": "running"}]
        self.assertEqual(self.hook("Stop", sid, background_tasks=busy), "")
        self.assertIn("block", self.hook("Stop", sid, background_tasks=[]))
        sid2, _ = self.session()
        self.hook("SessionStart", sid2)
        self.write("other/new2.py")
        shell = [{"id": "t2", "type": "shell", "status": "running"}]
        self.assertIn("block", self.hook("Stop", sid2, background_tasks=shell))

    def test_preexisting_drift_blocks_neither_stop_nor_subagentstop(self):
        self.clean_repo()
        self.write("other/old.py")
        self.write("src/a.py", "x = 9\n")
        sid, _ = self.session()
        self.hook("SessionStart", sid)
        self.assertEqual(self.hook("Stop", sid), "")
        self.assertEqual(self.hook("SubagentStop", sid, agent_id="a1"), "")

    def test_stop_hook_active_is_silent(self):
        self.clean_repo()
        sid, _ = self.session()
        self.hook("SessionStart", sid)
        self.write("src/new.py")
        self.assertEqual(self.hook("Stop", sid, stop_hook_active=True), "")
        self.assertIn("block", self.hook("Stop", sid))

    def test_stop_without_state_file_uses_empty_baseline(self):
        self.clean_repo()
        self.write("other/new.py")
        sid, path = self.session()
        self.assertIn("UNKARTIERT other/new.py", json.loads(self.hook("Stop", sid))["reason"])
        self.assertTrue(os.path.exists(path))

    def test_subagent_start(self):
        self.clean_repo()
        sid, path = self.session()
        out = json.loads(self.hook("SubagentStart", sid))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SubagentStart")
        self.assertIn("Projektkarte", out["hookSpecificOutput"]["additionalContext"])
        self.assertFalse(os.path.exists(path))

    def test_other_event_is_silent(self):
        self.clean_repo()
        sid, _ = self.session()
        self.assertEqual(self.hook("PreToolUse", sid), "")

    def test_garbage_and_non_git(self):
        for garbage in ["", "not json", "[1, 2]", "null", '{"hook_event_name": 5}']:
            r = self.karte("hook", stdin=garbage)
            self.assertEqual((r.returncode, r.stdout), (0, ""), garbage)
        with tempfile.TemporaryDirectory() as d:
            sid, _ = self.session()
            payload = json.dumps({"hook_event_name": "SessionStart", "session_id": sid, "cwd": d})
            r = self.karte("hook", cwd=d, stdin=payload)
            self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_missing_cwd_field_falls_back_to_process_cwd(self):
        self.clean_repo()
        sid, _ = self.session()
        payload = json.dumps({"hook_event_name": "SubagentStart", "session_id": sid, "cwd": "/gibt/es/nicht"})
        out = json.loads(self.karte("hook", stdin=payload).stdout)
        self.assertIn("Projektkarte", out["hookSpecificOutput"]["additionalContext"])

    def test_session_id_is_sanitized(self):
        self.assertEqual(os.path.basename(karte.state_path("../a b/c_d-1")), "karte-abc_d-1.json")


class StatusTests(RepoCase):
    def test_empty_map(self):
        r = self.karte("status")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.splitlines()[0],
                         "Projektkarte: leer · Notizen: docs/karte/module/<modul>.md")

    def test_full_format(self):
        self.write("src/a.py")
        self.write("src/b.py")
        self.write("tests/t.py")
        self.write("docs/karte/module/zz.md", note_text(paths=("src/a.py",), zweck="Zweck Z"))
        self.write("docs/karte/module/aa.md", note_text(paths=("src/a.py", "tests/**"), zweck="Zweck A",
                                                        body="- `src/weg.py`\n", extra='tests: "true"'))
        out = self.lines("status")
        self.assertEqual(out[0], "Projektkarte: 2 Module · Notizen: docs/karte/module/<modul>.md")
        self.assertEqual(out[1], "- aa · src/a.py tests/** · Zweck A · UNGESTEMPELT · Tests nie gelaufen")
        self.assertEqual(out[2], "- zz · src/a.py · Zweck Z · UNGESTEMPELT · ohne Tests")
        self.assertEqual(out[3], "Unkartiert (1): src/b.py")
        self.assertEqual(out[4], "Fehler (1): aa: toter Verweis `src/weg.py`")
        self.assertTrue(out[5].startswith("Befehle: python3 tools/karte.py status | pruefe"))

    def test_decisions_newest_first_and_capped(self):
        entries = "".join("## E-%03d · 2026-11-16 · Titel %d\nText\n\n" % (i, i) for i in range(1, 11))
        self.write("docs/karte/ENTSCHEIDUNGEN.md", "# Entscheidungen\n\n" + entries)
        line = [l for l in self.lines("status") if l.startswith("Entscheidungen")][0]
        self.assertEqual(line, "Entscheidungen (docs/karte/ENTSCHEIDUNGEN.md): E-010 Titel 10; E-009 Titel 9; "
                               "E-008 Titel 8; E-007 Titel 7; E-006 Titel 6; E-005 Titel 5; E-004 Titel 4; "
                               "E-003 Titel 3 … +2")

    def test_two_decisions(self):
        self.write("docs/karte/ENTSCHEIDUNGEN.md", "## E-001 · 2026-11-16 · Titel eins\n## E-002 · 2026-11-17 · Titel zwei\n")
        line = [l for l in self.lines("status") if l.startswith("Entscheidungen")][0]
        self.assertTrue(line.endswith(": E-002 Titel zwei; E-001 Titel eins"))

    def test_caps(self):
        for i in range(12):
            self.write("u/f%02d.py" % i)
        out = [l for l in self.lines("status") if l.startswith("Unkartiert")][0]
        self.assertTrue(out.startswith("Unkartiert (12): u/f00.py, "))
        self.assertTrue(out.endswith("u/f09.py, … +2"))
        for i in range(42):
            self.write("docs/karte/module/m%02d.md" % i, note_text(paths=("u/f00.py",)))
        out = self.lines("status")
        self.assertEqual(sum(1 for l in out if l.startswith("- m")), 40)
        self.assertIn("… +2 weitere", out)


if __name__ == "__main__":
    unittest.main()
