"""Fall-Speicher: Verzeichnisse, SQLite-Datenbank, ID-Vergabe und Protokoll."""

import calendar
import contextlib
import errno
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import urllib.parse
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path


class Fehler(Exception):
    """Fachlicher Fehler: wird als `fehler: <Text>` ausgegeben, Exit 1."""

    code = 1


class Nutzungsfehler(Fehler):
    """Falsche Verwendung des Werkzeugs, Exit 2."""

    code = 2


# --- Aufzählungen -----------------------------------------------------------

QUELLEN_TYPEN = ("amtlich", "register", "gericht", "parlament", "eigenangabe", "agentur",
                 "medium", "wissenschaft", "ngo", "datenbank", "social", "blog", "archiv",
                 "sonstiges", "unbekannt")
KATEGORIEN = ("amtstraeger", "oeffentlich", "funktion", "privat", "organisation", "unbekannt")
ZUVERLAESSIGKEIT = ("A", "B", "C", "D", "E", "F")
BEHAUPTUNGS_ARTEN = ("tatsache", "schlussfolgerung", "verdacht", "bewertung")
PRUEFBARE_STATUS = ("belegt", "gestuetzt", "unbestaetigt", "strittig", "widerlegt")
BEHAUPTUNGS_STATUS = ("ungeprueft", "werturteil") + PRUEFBARE_STATUS
HYPOTHESEN_STATUS = ("offen", "gestuetzt", "geschwaecht", "widerlegt")
FRAGEN_STATUS = ("offen", "in_arbeit", "beantwortet", "sackgasse")
RICHTUNGEN = ("pro", "contra", "neutral")
KONFRONTATIONS_STATUS = ("entwurf", "gesendet", "beantwortet", "keine_antwort")

TABELLE = {"H": "hypothese", "F": "frage", "S": "suche", "Q": "quelle", "B": "beleg",
           "A": "behauptung", "P": "akteur", "O": "akteur", "R": "beziehung",
           "E": "ereignis", "K": "konfrontation"}

SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")
ID_FORM = re.compile(r"([A-Z])(\d+)")
DATUM_FORM = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")

SCHEMA = """
CREATE TABLE meta (schluessel TEXT PRIMARY KEY, wert TEXT NOT NULL);
CREATE TABLE zaehler (praefix TEXT PRIMARY KEY, n INTEGER NOT NULL);
CREATE TABLE protokoll (nr INTEGER PRIMARY KEY AUTOINCREMENT, zeit TEXT NOT NULL,
    wer TEXT NOT NULL, aktion TEXT NOT NULL, objekt TEXT NOT NULL, details TEXT NOT NULL);
CREATE TABLE hypothese (id TEXT PRIMARY KEY, text TEXT NOT NULL,
    prueft TEXT NOT NULL DEFAULT '[]', widerlegt TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'offen', vermerk TEXT NOT NULL DEFAULT '');
CREATE TABLE frage (id TEXT PRIMARY KEY, text TEXT NOT NULL, hypothese TEXT,
    plan TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'offen',
    ergebnis TEXT NOT NULL DEFAULT '', mensch INTEGER NOT NULL DEFAULT 0);
CREATE TABLE suche (id TEXT PRIMARY KEY, frage TEXT, hypothese TEXT, anfrage TEXT NOT NULL,
    richtung TEXT NOT NULL, treffer INTEGER, notiz TEXT NOT NULL DEFAULT '',
    zeit TEXT NOT NULL, wer TEXT NOT NULL);
CREATE TABLE quelle (id TEXT PRIMARY KEY, url TEXT NOT NULL DEFAULT '',
    angefragt_url TEXT NOT NULL DEFAULT '', titel TEXT NOT NULL DEFAULT '',
    herausgeber TEXT NOT NULL DEFAULT '', autor TEXT NOT NULL DEFAULT '',
    datum TEXT NOT NULL DEFAULT '', abgerufen TEXT NOT NULL, sha256 TEXT NOT NULL,
    typ TEXT NOT NULL DEFAULT 'unbekannt', zuverlaessigkeit TEXT NOT NULL DEFAULT '',
    ursprung TEXT NOT NULL DEFAULT '', interesse TEXT NOT NULL DEFAULT '',
    archiv_url TEXT NOT NULL DEFAULT '', zeichen INTEGER NOT NULL DEFAULT 0,
    art TEXT NOT NULL, inhaltstyp TEXT NOT NULL DEFAULT '', frage TEXT);
CREATE TABLE beleg (id TEXT PRIMARY KEY, quelle TEXT NOT NULL, zitat TEXT NOT NULL,
    stelle INTEGER NOT NULL, aussage TEXT NOT NULL, direkt INTEGER NOT NULL DEFAULT 0,
    frage TEXT, wer TEXT NOT NULL, zeit TEXT NOT NULL);
CREATE TABLE behauptung (id TEXT PRIMARY KEY, text TEXT NOT NULL, art TEXT NOT NULL,
    hypothese TEXT, belastend INTEGER NOT NULL DEFAULT 0,
    zuschreibung INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ungeprueft', vermerk TEXT NOT NULL DEFAULT '',
    pruefer TEXT NOT NULL DEFAULT '', geprueft TEXT, klaerung TEXT NOT NULL DEFAULT '');
CREATE TABLE akteur (id TEXT PRIMARY KEY, art TEXT NOT NULL, name TEXT NOT NULL,
    kategorie TEXT NOT NULL, kennungen TEXT NOT NULL DEFAULT '{}',
    notiz TEXT NOT NULL DEFAULT '');
CREATE TABLE beziehung (id TEXT PRIMARY KEY, von TEXT NOT NULL, zu TEXT NOT NULL,
    art TEXT NOT NULL, von_datum TEXT NOT NULL DEFAULT '', bis_datum TEXT NOT NULL DEFAULT '');
CREATE TABLE ereignis (id TEXT PRIMARY KEY, datum TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE konfrontation (id TEXT PRIMARY KEY, akteur TEXT NOT NULL, frage TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'entwurf', gesendet_am TEXT NOT NULL DEFAULT '',
    frist TEXT NOT NULL DEFAULT '', antwort TEXT NOT NULL DEFAULT '', antwort_quelle TEXT,
    vermerk TEXT NOT NULL DEFAULT '');
CREATE TABLE verknuepfung (nr INTEGER PRIMARY KEY AUTOINCREMENT, art TEXT NOT NULL,
    von TEXT NOT NULL, zu TEXT NOT NULL, UNIQUE (art, von, zu));
"""


# --- kleine Helfer ----------------------------------------------------------

def jetzt():
    """Aktuelle UTC-Zeit als ISO-String ohne Bruchteile."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pflicht(wert, name):
    """Gibt den getrimmten Text zurück; leere Pflichtangaben sind ein Fehler."""
    wert = (wert or "").strip()
    if not wert:
        raise Fehler("%s darf nicht leer sein" % name)
    return wert


def pruefe_datum(wert, name="Datum"):
    """Erlaubt YYYY, YYYY-MM und YYYY-MM-DD; die Genauigkeit bleibt erhalten."""
    wert = wert.strip()
    treffer = DATUM_FORM.fullmatch(wert)
    gueltig = bool(treffer)
    if treffer:
        jahr, monat, tag = treffer.groups()
        if monat is not None:
            gueltig = 1 <= int(monat) <= 12
        if gueltig and tag is not None:
            gueltig = 1 <= int(tag) <= calendar.monthrange(int(jahr), int(monat))[1]
    if not gueltig:
        raise Fehler('%s muss die Form YYYY, YYYY-MM oder YYYY-MM-DD haben: "%s"' % (name, wert))
    return wert


def normalisiere_id(wert):
    return (wert or "").strip().upper()


def teile_liste(text):
    """Zerlegt `B1,B2` in IDs ohne Dubletten; None und leer ergeben []."""
    ids = []
    for stueck in (text or "").split(","):
        stueck = normalisiere_id(stueck)
        if stueck and stueck not in ids:
            ids.append(stueck)
    return ids


def namensschluessel(name):
    """Name für den Dublettenvergleich: kleingeschrieben, Leerraum zusammengezogen."""
    return " ".join(name.casefold().split())


# --- Fallverzeichnis --------------------------------------------------------

def faelle_wurzel():
    """RECHERCHE_FAELLE, sonst <git-Toplevel>/faelle, sonst ./faelle."""
    gesetzt = os.environ.get("RECHERCHE_FAELLE")
    if gesetzt:
        return Path(gesetzt)
    try:
        ergebnis = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                                  text=True, timeout=10)
        if ergebnis.returncode == 0 and ergebnis.stdout.strip():
            return Path(ergebnis.stdout.strip()) / "faelle"
    except (OSError, subprocess.SubprocessError):
        pass
    return Path("faelle")


def faelle_liste(wurzel):
    wurzel = Path(wurzel)
    if not wurzel.is_dir():
        return []
    # Nur Namen in Slug-Form: Arbeitsverzeichnisse des Ladens und Löschens beginnen mit einem Punkt.
    return sorted(p.name for p in wurzel.iterdir()
                  if SLUG.fullmatch(p.name) and (p / "fall.db").is_file())


def aktiver_slug(wurzel, angegeben):
    """--fall, sonst RECHERCHE_FALL, sonst der einzige vorhandene Fall."""
    vorhanden = faelle_liste(wurzel)
    wahl = angegeben or os.environ.get("RECHERCHE_FALL")
    if wahl:
        if wahl not in vorhanden:
            raise Fehler("unbekannt: Fall %s (vorhanden: %s)" % (wahl, ", ".join(vorhanden) or "keine"))
        return wahl
    if len(vorhanden) == 1:
        return vorhanden[0]
    if not vorhanden:
        raise Fehler("kein Fall vorhanden. Mit `fall neu SLUG --titel T --auftrag T` anlegen.")
    raise Fehler("mehrere Fälle vorhanden (%s). --fall SLUG oder RECHERCHE_FALL angeben."
                 % ", ".join(vorhanden))


class Fall:
    """Ein Fall: SQLite-Datenbank plus Snapshots der Quellen."""

    def __init__(self, slug, wurzel, wer):
        self.slug = slug
        self.verzeichnis = Path(wurzel) / slug
        self.wer = wer
        self.conn = sqlite3.connect(str(self.verzeichnis / "fall.db"), timeout=30,
                                    isolation_level=None)
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def oeffnen(cls, wurzel, slug, wer):
        if not (Path(wurzel) / slug / "fall.db").is_file():
            raise Fehler("unbekannt: Fall %s" % slug)
        return cls(slug, wurzel, wer)

    @classmethod
    def neu(cls, wurzel, slug, wer, titel, auftrag, interesse=""):
        if not SLUG.fullmatch(slug):
            raise Fehler("Slug muss [a-z0-9][a-z0-9-]* entsprechen: %s" % slug)
        verzeichnis = Path(wurzel) / slug
        if (verzeichnis / "fall.db").exists():
            raise Fehler("Fall existiert bereits: %s" % slug)
        (verzeichnis / "quellen").mkdir(parents=True, exist_ok=True)
        fall = cls(slug, wurzel, wer)
        try:
            fall.conn.execute("PRAGMA journal_mode=WAL")
            fall.conn.executescript(SCHEMA)
        except sqlite3.OperationalError:
            raise Fehler("Fall existiert bereits: %s" % slug)
        with fall.schreiben():
            fall.setze_meta(slug=slug, titel=titel, auftrag=auftrag, interesse=interesse,
                            zusammenfassung="", erstellt=jetzt(), schema="1")
            fall.log("fall neu", slug, titel)
        return fall

    # -- Transaktionen, IDs, Protokoll

    @contextlib.contextmanager
    def schreiben(self):
        """Schreibtransaktion; IDs und Änderungen gehören immer in dieselbe."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def neue_id(self, praefix):
        self.conn.execute("INSERT OR IGNORE INTO zaehler (praefix, n) VALUES (?, 0)", (praefix,))
        self.conn.execute("UPDATE zaehler SET n = n + 1 WHERE praefix = ?", (praefix,))
        n = self.conn.execute("SELECT n FROM zaehler WHERE praefix = ?", (praefix,)).fetchone()[0]
        return "%s%d" % (praefix, n)

    def log(self, aktion, objekt="", details=""):
        self.conn.execute(
            "INSERT INTO protokoll (zeit, wer, aktion, objekt, details) VALUES (?, ?, ?, ?, ?)",
            (jetzt(), self.wer, aktion, objekt, details))

    # -- Metadaten

    def meta(self):
        zeilen = self.conn.execute("SELECT schluessel, wert FROM meta").fetchall()
        return {z["schluessel"]: z["wert"] for z in zeilen}

    def setze_meta(self, **werte):
        for schluessel, wert in werte.items():
            self.conn.execute("INSERT OR REPLACE INTO meta (schluessel, wert) VALUES (?, ?)",
                              (schluessel, wert))

    # -- Objekte lesen und schreiben

    def hole(self, wert, erlaubt=None):
        """Liefert das Objekt zur ID als dict; sonst `unbekannt: <ID>`."""
        objekt_id = normalisiere_id(wert)
        treffer = ID_FORM.fullmatch(objekt_id)
        if not treffer or treffer.group(1) not in TABELLE or (erlaubt and treffer.group(1) not in erlaubt):
            raise Fehler("unbekannt: %s" % objekt_id)
        tabelle = TABELLE[treffer.group(1)]
        zeile = self.conn.execute("SELECT * FROM %s WHERE id = ?" % tabelle, (objekt_id,)).fetchone()
        if zeile is None:
            raise Fehler("unbekannt: %s" % objekt_id)
        return dict(zeile)

    def hole_liste(self, text, erlaubt):
        """Prüft eine kommagetrennte ID-Liste und gibt die IDs zurück."""
        return [self.hole(i, erlaubt)["id"] for i in teile_liste(text)]

    def alle(self, tabelle, bedingung="", parameter=()):
        sql = "SELECT * FROM %s %s ORDER BY rowid" % (tabelle, bedingung)
        return [dict(z) for z in self.conn.execute(sql, parameter).fetchall()]

    def anzahl(self, tabelle):
        return self.conn.execute("SELECT COUNT(*) FROM %s" % tabelle).fetchone()[0]

    def einfuegen(self, tabelle, **werte):
        spalten = ", ".join(werte)
        platz = ", ".join("?" for _ in werte)
        self.conn.execute("INSERT INTO %s (%s) VALUES (%s)" % (tabelle, spalten, platz),
                          tuple(werte.values()))

    def aendern(self, tabelle, objekt_id, **werte):
        zuweisung = ", ".join("%s = ?" % spalte for spalte in werte)
        self.conn.execute("UPDATE %s SET %s WHERE id = ?" % (tabelle, zuweisung),
                          tuple(werte.values()) + (objekt_id,))

    def erzeuge(self, praefix, aktion, details="", **werte):
        """Legt ein Objekt mit neuer ID an und protokolliert es."""
        objekt_id = self.neue_id(praefix)
        self.einfuegen(TABELLE[praefix], id=objekt_id, **werte)
        self.log(aktion, objekt_id, details)
        return objekt_id

    # -- Verknüpfungen (pro, contra, aus, betrifft, ...)

    def verknuepfe(self, art, von, ziele):
        """Fügt Verknüpfungen hinzu und gibt die tatsächlich neuen Ziele zurück."""
        neu = []
        for ziel in ziele:
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO verknuepfung (art, von, zu) VALUES (?, ?, ?)", (art, von, ziel))
            if cursor.rowcount:
                neu.append(ziel)
        return neu

    def entferne_verknuepfung(self, art, von, ziel):
        """Löst eine Verknüpfung; True, wenn sie bestand."""
        cursor = self.conn.execute("DELETE FROM verknuepfung WHERE art = ? AND von = ? AND zu = ?",
                                   (art, von, ziel))
        return cursor.rowcount > 0

    def ersetze_verknuepfung(self, art, von, ziele):
        self.conn.execute("DELETE FROM verknuepfung WHERE art = ? AND von = ?", (art, von))
        self.verknuepfe(art, von, ziele)

    def verknuepfungen(self, art):
        """Alle Verknüpfungen einer Art als {von: [zu, ...]} in Anlegereihenfolge."""
        ergebnis = {}
        for zeile in self.conn.execute("SELECT von, zu FROM verknuepfung WHERE art = ? ORDER BY nr", (art,)):
            ergebnis.setdefault(zeile["von"], []).append(zeile["zu"])
        return ergebnis

    # -- Snapshots

    def quellen_verzeichnis(self, quelle_id):
        return self.verzeichnis / "quellen" / quelle_id

    def lies_text(self, quelle_id):
        """Gespeicherter Text einer Quelle; fehlt die Datei, ist er leer."""
        try:
            return (self.quellen_verzeichnis(quelle_id) / "text.txt").read_text(encoding="utf-8")
        except OSError:
            return ""


def zu_liste(text):
    """JSON-Liste aus einer Textspalte."""
    return json.loads(text) if text else []


def zu_dict(text):
    """JSON-Objekt aus einer Textspalte."""
    return json.loads(text) if text else {}


# --- Fall mitnehmen: Zip-Archiv -----------------------------------------------

def sichere_fall(fall, ziel):
    """Schreibt fall.db (konsistente Kopie) und quellen/ als Zip nach `ziel`.
    Gibt (Pfad, Anzahl Dateien, Größe in Bytes) zurück."""
    ziel = Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    pfad = ziel / ("%s-%s.zip" % (fall.slug, datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")))
    try:
        fall.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError:
        pass  # die Sicherung unten ist auch bei laufenden Schreibern konsistent
    with tempfile.TemporaryDirectory() as temp:
        kopie = Path(temp) / "fall.db"
        ziel_db = sqlite3.connect(str(kopie))
        with ziel_db:
            fall.conn.backup(ziel_db)
        ziel_db.close()
        dateien = [(kopie, "fall.db")]
        quellen = fall.verzeichnis / "quellen"
        dateien += [(p, p.relative_to(fall.verzeichnis).as_posix())
                    for p in sorted(quellen.rglob("*")) if p.is_file()]
        with zipfile.ZipFile(str(pfad), "w", zipfile.ZIP_DEFLATED) as archiv:
            for quelle, name in dateien:
                archiv.write(str(quelle), "%s/%s" % (fall.slug, name))
    return pfad, len(dateien), pfad.stat().st_size


def _sicherer_archivpfad(name):
    if not name or name.startswith(("/", "\\")) or "\\" in name or re.match(r"[A-Za-z]:", name):
        return False
    return ".." not in name.split("/")


def _archiv_slug(namen):
    """Prüft Pfade und Aufbau (<slug>/fall.db, <slug>/quellen/...) und gibt den Slug zurück."""
    if not all(_sicherer_archivpfad(n) for n in namen):
        raise Fehler("unzulässiger Pfad im Archiv")
    slugs = {n.split("/")[0] for n in namen}
    if len(slugs) != 1 or not SLUG.fullmatch(next(iter(slugs))):
        raise Fehler("unzulässiger Pfad im Archiv")
    slug = slugs.pop()
    if slug + "/fall.db" not in namen:
        raise Fehler("Archiv enthält keinen Fall (fall.db fehlt)")
    erlaubt = (slug + "/fall.db", slug + "/quellen/")
    if not all(n == erlaubt[0] or n.startswith(erlaubt[1]) for n in namen):
        raise Fehler("unzulässiger Pfad im Archiv")
    return slug


MAX_ARCHIV_DATEIEN = 50000
MAX_ARCHIV_BYTES = 4 * 1024 ** 3
# Ein kleines Archiv darf nicht ein großes Vielfaches an Speicher belegen (Zip-Bombe).
MAX_OHNE_VERHAELTNIS = 16 * 1024 ** 2
MAX_VERHAELTNIS = 100
SPEICHER_RESERVE = 100 * 1024 ** 2

_ENTPACK_FEHLER = (zipfile.BadZipFile, zlib.error, EOFError, OSError, RuntimeError, NotImplementedError)


def _mb(bytes_):
    return max(1, bytes_ // (1024 * 1024))


def _schema_soll():
    """Tabellenname -> CREATE-Anweisung aus SCHEMA, Leerraum vereinheitlicht."""
    soll = {}
    for anweisung in SCHEMA.split(";"):
        treffer = re.match(r"\s*CREATE TABLE (\w+)", anweisung)
        if treffer:
            soll[treffer.group(1)] = " ".join(anweisung.split())
    return soll


def _lies_nur(pfad, lesen):
    """Öffnet die Datenbank unveränderlich und gibt `lesen(conn)` zurück."""
    adresse = "file:%s?mode=ro&immutable=1" % urllib.parse.quote(str(pfad))
    try:
        conn = sqlite3.connect(adresse, uri=True)
        try:
            return lesen(conn)
        finally:
            conn.close()
    except sqlite3.Error as fehler:
        raise Fehler("Die Akte im Archiv ist keine lesbare Datenbank (%s); nichts wurde geladen." % fehler)


def pruefe_schema(pfad):
    """Die Datenbank einer geladenen Akte darf nur die Tabellen dieses Werkzeugs enthalten, im
    Wortlaut von SCHEMA. Ein Auslöser oder eine Ansicht könnte Werte ändern, nachdem sie
    geprüft wurden, etwa einen zurückgesetzten Status wiederherstellen."""
    soll = _schema_soll()
    zeilen = _lies_nur(pfad, lambda conn: conn.execute("SELECT type, name, sql FROM sqlite_master").fetchall())
    gefunden = set()
    for typ, name, sql in zeilen:
        if typ == "table" and soll.get(name) == " ".join((sql or "").split()):
            gefunden.add(name)
        elif typ == "table" and name == "sqlite_sequence":
            pass  # legt SQLite für AUTOINCREMENT selbst an
        elif typ == "index" and sql is None and str(name).startswith("sqlite_autoindex_"):
            pass  # automatische Indizes zu PRIMARY KEY und UNIQUE
        else:
            raise Fehler("Die Akte im Archiv hat einen fremden Aufbau (%s %s); nichts wurde geladen."
                         % (typ, name))
    fehlend = sorted(set(soll) - gefunden)
    if fehlend:
        raise Fehler("Der Akte im Archiv fehlen Tabellen (%s); nichts wurde geladen." % ", ".join(fehlend))


# Spalten, die auf andere Objekte verweisen, mit den Buchstaben der erlaubten Ziele. Aus IDs
# werden Pfade (quellen/<ID>) und Schlüssel.
VERWEISSPALTEN = {("frage", "hypothese"): "H", ("suche", "frage"): "F", ("suche", "hypothese"): "H",
                  ("quelle", "frage"): "F", ("beleg", "quelle"): "Q", ("beleg", "frage"): "F",
                  ("behauptung", "hypothese"): "H", ("beziehung", "von"): "PO", ("beziehung", "zu"): "PO",
                  ("konfrontation", "akteur"): "PO", ("konfrontation", "antwort_quelle"): "Q"}
# Arten von Verknüpfungen: (Buchstaben für von, Buchstaben für zu)
VERKNUEPFUNGSARTEN = {"pro": ("A", "B"), "contra": ("A", "B"), "aus": ("A", "A"), "betrifft": ("A", "PO"),
                      "akteur_beleg": ("PO", "B"), "beziehung_beleg": ("R", "B"),
                      "ereignis_beleg": ("E", "B"), "ereignis_akteur": ("E", "PO"),
                      "konfrontation_zu": ("K", "A")}
AUFZAEHLUNGEN = {("hypothese", "status"): HYPOTHESEN_STATUS, ("frage", "status"): FRAGEN_STATUS,
                 ("suche", "richtung"): RICHTUNGEN, ("quelle", "typ"): QUELLEN_TYPEN,
                 ("quelle", "zuverlaessigkeit"): ZUVERLAESSIGKEIT + ("",),
                 ("behauptung", "art"): BEHAUPTUNGS_ARTEN, ("akteur", "art"): ("person", "organisation"),
                 ("akteur", "kategorie"): KATEGORIEN, ("konfrontation", "status"): KONFRONTATIONS_STATUS}
_ID_STRENG = re.compile(r"([A-Z])([0-9]+)")


def _spalten_soll():
    """{Tabelle: [(Spalte, Typ, Pflicht)]}, von SQLite selbst aus SCHEMA gelesen."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(SCHEMA)
        return {name: [(z[1], z[2].upper(), bool(z[3]) or bool(z[5]))
                       for z in conn.execute("PRAGMA table_info(%s)" % name)]
                for name in _schema_soll()}
    finally:
        conn.close()


def _uebernimm(fremd_pfad, ziel_pfad):
    """Schreibt die Zeilen der fremden Datenbank in eine frische mit dem eigenen SCHEMA.

    Die Datei aus dem Archiv wird gelesen, nie benutzt: Ihr Dateiformat hat mehr Winkel, als
    sich prüfen lassen. Zwei Zeilen mit derselben ID hinter einem Index, der nur eine kennt,
    kamen so schon durch; hier scheitern sie am Primärschlüssel der neuen Tabelle."""
    adresse = "file:%s?mode=ro&immutable=1" % urllib.parse.quote(str(fremd_pfad))
    try:
        ziel = sqlite3.connect(str(ziel_pfad), isolation_level=None)
        try:
            ziel.executescript(SCHEMA)
            fremd = sqlite3.connect(adresse, uri=True)
            try:
                befund = fremd.execute("PRAGMA integrity_check").fetchall()
                if befund != [("ok",)]:
                    raise Fehler("Die Datenbank der Akte im Archiv ist beschädigt (%s); nichts wurde geladen."
                                 % str(befund[0][0])[:120])
                ziel.execute("BEGIN")
                for tabelle, spalten in _spalten_soll().items():
                    namen = ", ".join(spalte for spalte, _typ, _pflicht in spalten)
                    einfuegen = "INSERT INTO %s (%s) VALUES (%s)" % (tabelle, namen, ", ".join("?" for _ in spalten))
                    # NOT INDEXED: jede Zeile der Tabelle selbst, nicht das, was ein Index von ihr weiß
                    for zeile in fremd.execute("SELECT %s FROM %s NOT INDEXED ORDER BY rowid" % (namen, tabelle)):
                        ziel.execute(einfuegen, tuple(zeile))
                ziel.execute("COMMIT")
            finally:
                fremd.close()
        finally:
            ziel.close()
    except sqlite3.Error as fehler:
        raise Fehler("Die Akte im Archiv ist keine gültige Fallakte (%s); nichts wurde geladen." % fehler)


def _inhaltsfehler(conn, slug):
    """Erster Verstoß der Daten gegen den Aufbau der Fallakte, sonst None."""
    for tabelle, spalten in _spalten_soll().items():
        bedingungen = []
        for spalte, typ, pflicht in spalten:
            erlaubt = ["'integer'" if typ == "INTEGER" else "'text'"] + ([] if pflicht else ["'null'"])
            bedingungen.append("typeof(%s) IN (%s)" % (spalte, ", ".join(erlaubt)))
        if conn.execute("SELECT 1 FROM %s WHERE NOT (%s) LIMIT 1"
                        % (tabelle, " AND ".join(bedingungen))).fetchone():
            return "Tabelle %s enthält Werte vom falschen Typ" % tabelle
    vorhanden, hoechste = set(), {}
    for tabelle in sorted(set(TABELLE.values())):
        for (wert,) in conn.execute("SELECT id FROM %s" % tabelle):
            treffer = _ID_STRENG.fullmatch(wert)
            if not treffer or TABELLE.get(treffer.group(1)) != tabelle:
                return "unzulässige ID in %s: %r" % (tabelle, wert[:40])
            vorhanden.add(wert)
            hoechste[treffer.group(1)] = max(hoechste.get(treffer.group(1), 0), int(treffer.group(2)))

    def ziel_ok(wert, buchstaben):
        # Ein Verweis auf ein Objekt, das es noch nicht gibt, hinge sich an das nächste, das entsteht.
        return wert[:1] in buchstaben and wert in vorhanden

    for (tabelle, spalte), buchstaben in VERWEISSPALTEN.items():
        for (wert,) in conn.execute("SELECT %s FROM %s WHERE %s IS NOT NULL AND %s != ''"
                                    % (spalte, tabelle, spalte, spalte)):
            if not ziel_ok(wert, buchstaben):
                return "Verweis ohne Ziel in %s.%s: %r" % (tabelle, spalte, wert[:40])
    for art, von, zu in conn.execute("SELECT art, von, zu FROM verknuepfung"):
        if art not in VERKNUEPFUNGSARTEN:
            return "unbekannte Art von Verknüpfung: %r" % art[:40]
        if not ziel_ok(von, VERKNUEPFUNGSARTEN[art][0]) or not ziel_ok(zu, VERKNUEPFUNGSARTEN[art][1]):
            return "Verknüpfung ohne Ziel (%s): %r → %r" % (art, von[:40], zu[:40])
    for (tabelle, spalte), werte in AUFZAEHLUNGEN.items():
        platz = ", ".join("?" for _ in werte)
        if conn.execute("SELECT 1 FROM %s WHERE %s NOT IN (%s) LIMIT 1" % (tabelle, spalte, platz),
                        tuple(werte)).fetchone():
            return "unbekannter Wert in %s.%s" % (tabelle, spalte)
    zaehler = dict(conn.execute("SELECT praefix, n FROM zaehler").fetchall())
    for praefix, nummer in hoechste.items():
        if zaehler.get(praefix, 0) < nummer:
            return "Zähler für %s steht unter der höchsten vergebenen ID" % praefix
    try:
        for tabelle, spalten, form in (("hypothese", ("prueft", "widerlegt"), list), ("akteur", ("kennungen",), dict)):
            for zeile in conn.execute("SELECT %s FROM %s" % (", ".join(spalten), tabelle)):
                for inhalt in zeile:
                    wert = json.loads(inhalt) if inhalt else form()
                    teile = list(wert.items()) if isinstance(wert, dict) else [(None, x) for x in wert]
                    if not isinstance(wert, form) or not all(
                            isinstance(v, str) and (k is None or isinstance(k, str)) for k, v in teile):
                        return "unzulässige Liste oder Zuordnung in %s" % tabelle
    except (ValueError, TypeError, AttributeError):
        return "unlesbare Liste oder Zuordnung in hypothese oder akteur"
    meta = dict(conn.execute("SELECT schluessel, wert FROM meta").fetchall())
    if meta.get("slug") != slug:
        return "der Kurzname in der Akte passt nicht zum Archiv"
    return None


def pruefe_inhalt(pfad, slug):
    """Die Daten einer geladenen Akte müssen so aussehen, wie das Werkzeug sie schreibt:
    Typen der Spalten, IDs und Verweise in der Form `A1`, Zähler, Listen. Das Archiv ist eine
    fremde Datei; aus IDs werden Pfade und Schlüssel, und zwei IDs, die sich nur in der
    Schreibung unterscheiden, haben das Zurücksetzen schon einmal in eine Endlosschleife geführt."""
    fehler = _lies_nur(pfad, lambda conn: _inhaltsfehler(conn, slug))
    if fehler:
        raise Fehler("Die Akte im Archiv verletzt den Aufbau der Fallakte (%s); nichts wurde geladen." % fehler)


ARBEITSVERZEICHNISSE = (".laden-", ".upload-", ".loeschen-")


def raeume_arbeitsverzeichnisse(wurzel, aelter_als=86400):
    """Entfernt liegen gebliebene Arbeitsverzeichnisse von Laden, Hochladen und Löschen. Nach
    einem Abbruch des Prozesses enthalten sie eine ganze Akte, erscheinen aber in keiner Liste.
    Nur die von gestern, damit ein gleichzeitig laufender Vorgang seines sicher behält."""
    wurzel = Path(wurzel)
    if not wurzel.is_dir():
        return
    grenze = datetime.now(timezone.utc).timestamp() - aelter_als
    for pfad in wurzel.iterdir():
        try:
            if pfad.name.startswith(ARBEITSVERZEICHNISSE) and pfad.lstat().st_mtime < grenze:
                if pfad.is_dir() and not pfad.is_symlink():
                    shutil.rmtree(str(pfad), ignore_errors=True)
                else:
                    pfad.unlink()
        except OSError:
            pass


def lade_fall(wurzel, archivpfad, pruefung=None):
    """Stellt einen mit sichere_fall gesicherten Fall wieder her; gibt den Slug zurück.

    Ruft niemand außer `bewertung.lade_akte` auf: Eine geladene Akte muss geprüft werden.
    `pruefung(verzeichnis, slug)` läuft, solange die Akte noch im Arbeitsverzeichnis liegt;
    erst danach wird sie ins Fallverzeichnis verschoben. Scheitert irgendetwas, bleibt dort
    nichts zurück."""
    wurzel = Path(wurzel)
    raeume_arbeitsverzeichnisse(wurzel)
    try:
        archiv = zipfile.ZipFile(str(archivpfad))
    except (OSError, zipfile.BadZipFile) as fehler:
        raise Fehler("Archiv nicht lesbar: %s" % fehler)
    with archiv:
        eintraege = [i for i in archiv.infolist() if not i.is_dir()]
        gesamt = sum(i.file_size for i in eintraege)
        if len(eintraege) > MAX_ARCHIV_DATEIEN or gesamt > MAX_ARCHIV_BYTES:
            raise Fehler("Archiv zu groß")
        komprimiert = sum(i.compress_size for i in eintraege)
        if gesamt > MAX_OHNE_VERHAELTNIS and gesamt > MAX_VERHAELTNIS * max(komprimiert, 1):
            raise Fehler("Archiv verdächtig stark komprimiert (%d MB entpackt aus %d MB gepackt); "
                         "nichts wurde geladen." % (_mb(gesamt), _mb(komprimiert)))
        slug = _archiv_slug([i.filename for i in eintraege])
        if (wurzel / slug).exists():
            raise Fehler("Fall existiert bereits: %s" % slug)
        wurzel.mkdir(parents=True, exist_ok=True)
        frei = shutil.disk_usage(str(wurzel)).free
        if gesamt + SPEICHER_RESERVE > frei:
            raise Fehler("Nicht genug freier Speicher: Die Akte braucht %d MB plus %d MB Reserve, "
                         "frei sind %d MB." % (_mb(gesamt), _mb(SPEICHER_RESERVE), _mb(frei)))
        temp = Path(tempfile.mkdtemp(prefix=".laden-", dir=str(wurzel)))
        try:
            try:
                for eintrag in eintraege:
                    ziel = temp / eintrag.filename
                    ziel.parent.mkdir(parents=True, exist_ok=True)
                    with archiv.open(eintrag) as quelle, open(str(ziel), "wb") as datei:
                        shutil.copyfileobj(quelle, datei)
                (temp / slug / "quellen").mkdir(exist_ok=True)
            except _ENTPACK_FEHLER as fehler:
                if isinstance(fehler, OSError) and fehler.errno == errno.ENOSPC:
                    raise Fehler("Der Speicher ist beim Entpacken voll gelaufen; nichts wurde geladen.")
                raise Fehler("Archiv beschädigt oder unvollständig (%s); nichts wurde geladen." % fehler)
            fremd = temp / "fremd.db"
            (temp / slug / "fall.db").rename(fremd)
            pruefe_schema(fremd)
            _uebernimm(fremd, temp / slug / "fall.db")
            fremd.unlink()
            pruefe_inhalt(temp / slug / "fall.db", slug)
            if pruefung is not None:
                try:
                    pruefung(temp, slug)
                except Fehler as fehler:
                    raise Fehler("Die Akte im Archiv ist in sich nicht stimmig (%s); nichts wurde geladen."
                                 % fehler)
                except Exception as fehler:  # bewusst breit: fremde Daten, jeder Fehler heißt Ablehnen
                    raise Fehler("Die Akte im Archiv ist beschädigt oder unvollständig (%s: %s); "
                                 "nichts wurde geladen." % (type(fehler).__name__, fehler))
            try:
                (temp / slug).rename(wurzel / slug)
            except OSError as fehler:
                raise Fehler("Die Akte ließ sich nicht ablegen (%s); nichts wurde geladen." % fehler)
        finally:
            shutil.rmtree(str(temp), ignore_errors=True)
    return slug
