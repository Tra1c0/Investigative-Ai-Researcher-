"""Gemeinsame Hilfen für die recherche-Tests (selbst ohne Tests)."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

HTML_SEITE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Seitentitel</title>
<meta property="og:title" content="Der Og-Titel">
<meta property="og:site_name" content="Beispiel Zeitung">
<meta property="article:published_time" content="2026-05-01T08:30:00+02:00">
<meta name="author" content="Erika Muster">
<style>.verstecktes-css { color: red; }</style>
<script>var geheim = "SKRIPTINHALT";</script></head>
<body><nav>Navigation</nav>
<article><h1>Überschrift</h1>
<p>Die Behörde sagte: „Das ist ein   Test“ &amp; mehr –   später.</p>
<p>Ver&shy;wal­tung und Ge&#8203;schäft</p>
<script>alert('SKRIPTINHALT2')</script><noscript>BITTE-JS</noscript>
<template>VORLAGE</template><svg><title>SVGTITEL</title></svg>
<p>Zeile eins<br>Zeile zwei</p></article></body></html>"""

JSON_INHALT = '{"name": "Müller", "betrag": 1200}'


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _senden(self, status, koerper, typ, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(koerper)))
        for name, wert in extra:
            self.send_header(name, wert)
        self.end_headers()
        self.wfile.write(koerper)

    def do_GET(self):
        pfad = self.path
        if pfad == "/artikel":
            self._senden(200, HTML_SEITE.encode("utf-8"), "text/html; charset=utf-8")
        elif pfad == "/weiter":
            self._senden(302, b"", "text/plain", [("Location", "/artikel")])
        elif pfad == "/endlos":
            self._senden(302, b"", "text/plain", [("Location", "/endlos")])
        elif pfad == "/daten.json":
            self._senden(200, JSON_INHALT.encode("utf-8"), "application/json")
        elif pfad == "/latin1":
            self._senden(200, "<p>Größe in Zoll: 5 Äpfel</p>".encode("latin-1"),
                         "text/html; charset=iso-8859-1")
        elif pfad == "/gross":
            self._gross()
        else:
            self.send_error(404)

    def _gross(self):
        groesse = 26 * 1024 * 1024
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(groesse))
        self.end_headers()
        try:
            for _ in range(26):
                self.wfile.write(b"\0" * 1024 * 1024)
        except OSError:
            pass


class Testserver:
    """HTTP-Server auf 127.0.0.1 in einem Thread."""

    def __init__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return "http://127.0.0.1:%d" % self.server.server_address[1]

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()


class Ergebnis:
    def __init__(self, ergebnis):
        self.code = ergebnis.returncode
        self.out = ergebnis.stdout
        self.err = ergebnis.stderr
        self.zeilen = self.out.splitlines()


class FallTest(unittest.TestCase):
    """Jeder Test bekommt ein eigenes Fallverzeichnis und eine saubere Umgebung."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.wurzel = tmp.name
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("RECHERCHE_")}
        self.env.update(RECHERCHE_FAELLE=self.wurzel, RECHERCHE_LOKAL_ERLAUBT="1",
                        RECHERCHE_WER="tester", NO_PROXY="127.0.0.1,localhost",
                        no_proxy="127.0.0.1,localhost", PYTHONIOENCODING="utf-8")

    # -- Aufrufe

    def cli(self, *args, eingabe=None, env=None):
        ergebnis = subprocess.run([sys.executable, "-m", "recherche"] + [str(a) for a in args],
                                  cwd=str(REPO), env=env or self.env, input=eingabe,
                                  capture_output=True, text=True, encoding="utf-8", timeout=120)
        return Ergebnis(ergebnis)

    def ok(self, *args, **kwargs):
        ergebnis = self.cli(*args, **kwargs)
        self.assertEqual(ergebnis.code, 0, "%s -> %s\n%s" % (args, ergebnis.code, ergebnis.err))
        return ergebnis

    def fehler(self, *args, code=1, **kwargs):
        ergebnis = self.cli(*args, **kwargs)
        self.assertEqual(ergebnis.code, code, "%s -> %s\n%s%s" % (args, ergebnis.code, ergebnis.out, ergebnis.err))
        return ergebnis

    def neue_id(self, *args, **kwargs):
        ergebnis = self.ok(*args, **kwargs)
        self.assertTrue(ergebnis.zeilen[0].startswith("angelegt: "), ergebnis.out)
        return ergebnis.zeilen[0].split(": ", 1)[1].split(" ")[0]

    def export(self):
        return json.loads(self.ok("export").out)

    # -- Bausteine

    def neuer_fall(self, slug="t"):
        self.ok("fall", "neu", slug, "--titel", "Testfall", "--auftrag", "Prüfen")
        return slug

    def quelle(self, text, typ=None, zuv=None, ursprung=None, titel="Quelle"):
        qid = self.neue_id("quelle", "text", "--titel", titel, eingabe=text)
        optionen = []
        for name, wert in (("--typ", typ), ("--zuverlaessigkeit", zuv), ("--ursprung", ursprung)):
            if wert is not None:
                optionen += [name, wert]
        if optionen:
            self.ok("quelle", "setzen", qid, *optionen)
        return qid

    def beleg(self, quelle, zitat, direkt=False, aussage="Aussage"):
        optionen = ["--direkt"] if direkt else []
        return self.neue_id("beleg", "neu", "--quelle", quelle, "--zitat", zitat, "--aussage", aussage, *optionen)

    def behauptung(self, text="Eine Behauptung", art="tatsache", *optionen):
        return self.neue_id("behauptung", "neu", "--text", text, "--art", art, *optionen)

    def status(self, aid):
        zeile = self.ok("behauptung", "zeigen", aid).zeilen[0]
        return zeile.split("status ")[1]


class ArchivHilfen:
    """Mixin für FallTest: gesicherte Akten bauen, auch solche mit unzulässigem Status."""

    def gesichertes_archiv(self, slug):
        """Sichert den Fall in ein neues Verzeichnis außerhalb der Fälle und gibt den Zip-Pfad zurück."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ok("--fall", slug, "fall", "sichern", "--ziel", tmp.name)
        return os.path.join(tmp.name, [n for n in os.listdir(tmp.name) if n.endswith(".zip")][0])

    def setze_status(self, aid, status, slug="t"):
        """Schreibt einen Status an den Regeln vorbei in die Datenbank (wie ein manipuliertes Archiv)."""
        db = sqlite3.connect(os.path.join(self.wurzel, slug, "fall.db"))
        with db:
            db.execute("UPDATE behauptung SET status = ?, pruefer = 'x', geprueft = '2026-01-01T00:00:00Z' "
                       "WHERE id = ?", (status, aid))
        db.close()

    def manipulierte_akte(self):
        """Quelle mit Zuverlässigkeit E, ein Zitat, eine Tatsachenbehauptung mit Status belegt in
        der Datenbank, gesichert und aus den Fällen entfernt. Gibt den Zip-Pfad zurück."""
        self.neuer_fall("t")
        qid = self.quelle("Er sagte klar und deutlich: Das ist belegt genug, wirklich. Mehr nicht.",
                          typ="medium", zuv="E")
        bid = self.beleg(qid, "Das ist belegt genug, wirklich.")
        aid = self.behauptung("Eine Tatsache", "tatsache", "--pro", bid)
        self.assertEqual((qid, bid, aid), ("Q1", "B1", "A1"))
        self.setze_status(aid, "belegt")
        archiv = self.gesichertes_archiv("t")
        shutil.rmtree(os.path.join(self.wurzel, "t"))
        return archiv

    def protokoll(self, slug="t"):
        db = sqlite3.connect(os.path.join(self.wurzel, slug, "fall.db"))
        zeilen = db.execute("SELECT aktion, objekt, wer FROM protokoll ORDER BY nr").fetchall()
        db.close()
        return zeilen
