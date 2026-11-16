"""Tests der Weboberfläche (recherche/web.py, recherche/web_ui.html). Kein Test greift auf das Internet zu."""

import http.client
import json
import os
import re
import shutil
import threading
import unittest
from pathlib import Path
from unittest import mock

from recherche import web
from test_recherche_basis import REPO, FallTest, Testserver

ZITAT_TEXT = ('Er sagte: "Das ist nicht wahr" und \'nie\' mehr. Kosten: $HOME und `date` je Monat. '
              "Weiterer Satz, damit der Text lang genug ist.")
ZITAT = '"Das ist nicht wahr" und \'nie\' mehr. Kosten: $HOME und `date` je Monat.'


class WebTest(FallTest):
    def setUp(self):
        super().setUp()
        umgebung = mock.patch.dict(os.environ, {
            "RECHERCHE_FAELLE": self.wurzel, "RECHERCHE_LOKAL_ERLAUBT": "1", "RECHERCHE_WER": "tester",
            "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
        umgebung.start()
        self.addCleanup(umgebung.stop)
        os.environ.pop("RECHERCHE_FALL", None)
        self.server = web.Server(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.stoppe)
        self.port = self.server.port

    # -- HTTP-Helfer

    def http(self, methode, pfad, koerper=None, headers=None, angemeldet=True, host=None):
        kopf = {"Host": host or "127.0.0.1:%d" % self.port}
        if angemeldet:
            kopf["X-Recherche-Token"] = self.server.token
        kopf.update(headers or {})
        verbindung = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            verbindung.request(methode, pfad, body=koerper, headers=kopf)
            antwort = verbindung.getresponse()
            return antwort.status, antwort, antwort.read()
        finally:
            verbindung.close()

    def befehl(self, argv, fall="t", eingabe=None, wer="tester"):
        koerper = json.dumps({"fall": fall, "wer": wer, "argv": argv, "eingabe": eingabe})
        status, _, daten = self.http("POST", "/api/befehl", koerper, {"Content-Type": "application/json"})
        return status, json.loads(daten.decode("utf-8"))

    def befehl_ok(self, argv, **kwargs):
        status, ergebnis = self.befehl(argv, **kwargs)
        self.assertEqual((status, ergebnis["code"]), (200, 0), ergebnis)
        return ergebnis

    def export_http(self, slug="t"):
        status, _, daten = self.http("GET", "/api/export?fall=" + slug)
        self.assertEqual(status, 200)
        return json.loads(daten.decode("utf-8"))

    def fall_mit_quelle(self):
        self.befehl_ok(["fall", "neu", "t", "--titel=Testfall", "--auftrag=Prüfen"], fall=None)
        ergebnis = self.befehl_ok(["quelle", "text", "--titel=Quelle Eins"], eingabe=ZITAT_TEXT)
        self.assertIn("angelegt: Q1", ergebnis["aus"])


class Zugang(WebTest):
    def test_ohne_token_403_und_cookie_ueber_t(self):
        status, antwort, daten = self.http("GET", "/", angemeldet=False)
        self.assertEqual(status, 403)
        self.assertIn("Kein Zugriff", daten.decode("utf-8"))
        status, _, _ = self.http("GET", "/api/faelle", angemeldet=False)
        self.assertEqual(status, 403)
        status, _, _ = self.http("GET", "/?t=falsch", angemeldet=False)
        self.assertEqual(status, 403)
        status, antwort, _ = self.http("GET", "/?t=" + self.server.token, angemeldet=False)
        self.assertEqual(status, 302)
        self.assertEqual(antwort.getheader("Location"), "/")
        cookie = antwort.getheader("Set-Cookie")
        self.assertIn("%s=%s" % (self.server.cookie, self.server.token), cookie)
        for teil in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(teil, cookie)
        mit_cookie = {"Cookie": "%s=%s" % (self.server.cookie, self.server.token)}
        status, _, _ = self.http("GET", "/api/faelle", headers=mit_cookie, angemeldet=False)
        self.assertEqual(status, 200)
        status, _, _ = self.http("GET", "/api/faelle", headers={"Cookie": self.server.cookie + "=falsch"},
                                 angemeldet=False)
        self.assertEqual(status, 403)

    def test_hostpruefung(self):
        for host in ("evil.example", "evil.example:%d" % self.port, "127.0.0.1", "127.0.0.1:1"):
            status, _, _ = self.http("GET", "/api/faelle", host=host)
            self.assertEqual(status, 403, host)
        for host in ("127.0.0.1:%d" % self.port, "localhost:%d" % self.port):
            status, _, _ = self.http("GET", "/api/faelle", host=host)
            self.assertEqual(status, 200, host)

    def test_ursprung_bei_post(self):
        koerper = json.dumps({"fall": None, "argv": ["fall", "liste"]})
        kopf = {"Content-Type": "application/json"}
        status, _, _ = self.http("POST", "/api/befehl", koerper, dict(kopf, Origin="http://evil.example"))
        self.assertEqual(status, 403)
        status, _, _ = self.http("POST", "/api/befehl", koerper, dict(kopf, Origin="null"))
        self.assertEqual(status, 403)
        status, _, _ = self.http("POST", "/api/befehl", koerper, dict(kopf, Origin="http://127.0.0.1:%d" % self.port))
        self.assertEqual(status, 200)

    def test_nur_loopback(self):
        self.assertEqual(self.server.httpd.server_address[0], "127.0.0.1")

    def test_koepfe_auf_jeder_antwort_und_kein_cors(self):
        for pfad, angemeldet in (("/", True), ("/", False), ("/api/faelle", True), ("/gibt-es-nicht", True)):
            _, antwort, _ = self.http("GET", pfad, angemeldet=angemeldet)
            self.assertEqual(antwort.getheader("X-Content-Type-Options"), "nosniff", pfad)
            self.assertEqual(antwort.getheader("Referrer-Policy"), "no-referrer", pfad)
            self.assertFalse([k for k, _ in antwort.getheaders() if k.lower().startswith("access-control")])
        _, antwort, _ = self.http("OPTIONS", "/api/befehl")
        self.assertEqual(antwort.status, 405)
        self.assertEqual(antwort.getheader("X-Content-Type-Options"), "nosniff")

    def test_csp_mit_nonce_passt_zur_seite(self):
        status, antwort, daten = self.http("GET", "/")
        self.assertEqual(status, 200)
        csp = antwort.getheader("Content-Security-Policy")
        nonce = re.search(r"script-src 'nonce-([^']+)'", csp).group(1)
        self.assertIn("style-src 'nonce-%s'" % nonce, csp)
        for teil in ("default-src 'none'", "connect-src 'self'", "frame-src 'self'", "base-uri 'none'",
                     "form-action 'none'"):
            self.assertIn(teil, csp)
        self.assertNotRegex(csp, r"https?:|\*|unsafe")
        seite = daten.decode("utf-8")
        self.assertEqual(seite.count('nonce="%s"' % nonce), 2)
        self.assertNotIn("__NONCE__", seite)
        _, zweite, _ = self.http("GET", "/")
        self.assertNotEqual(nonce, re.search(r"nonce-([^']+)", zweite.getheader("Content-Security-Policy")).group(1))

    def test_grenzen_der_koerper(self):
        kopf = {"Content-Type": "application/json"}
        gross = json.dumps({"fall": None, "argv": ["fall", "liste"], "eingabe": "x" * (1024 * 1024)})
        status, _, _ = self.http("POST", "/api/befehl", gross, kopf)
        self.assertEqual(status, 413)
        status, _, _ = self.http("POST", "/api/befehl", "{}", {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        status, _, _ = self.http("POST", "/api/befehl", "kein json", kopf)
        self.assertEqual(status, 400)
        # Zu große Uploads werden an der Content-Length abgelehnt, ohne den Körper zu lesen.
        for pfad, groesse in (("/api/quelle-datei?fall=t&titel=x&name=a.txt", 26 * 1024 * 1024),
                              ("/api/laden", 513 * 1024 * 1024)):
            verbindung = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
            verbindung.putrequest("POST", pfad, skip_host=True)
            for name, wert in (("Host", "127.0.0.1:%d" % self.port), ("X-Recherche-Token", self.server.token),
                               ("Content-Type", "application/octet-stream"), ("Content-Length", str(groesse))):
                verbindung.putheader(name, wert)
            verbindung.endheaders()
            self.assertEqual(verbindung.getresponse().status, 413, pfad)
            verbindung.close()


class Befehle(WebTest):
    def test_befehl_liefert_code_ausgabe_und_deutschen_fehler(self):
        ergebnis = self.befehl_ok(["fall", "neu", "t", "--titel=Testfall", "--auftrag=Prüfen"], fall=None)
        self.assertIn("angelegt: t", ergebnis["aus"])
        ergebnis = self.befehl_ok(["fall", "zeigen"])
        self.assertIn("Testfall", ergebnis["aus"])
        self.assertEqual(ergebnis["fehler"], "")
        status, ergebnis = self.befehl(["hypothese", "status", "H99", "offen", "--vermerk=x"])
        self.assertEqual((status, ergebnis["code"]), (200, 1))
        self.assertIn("fehler: unbekannt: H99", ergebnis["fehler"])
        status, ergebnis = self.befehl(["fall", "neu", "t", "--titel=Doppelt", "--auftrag=x"], fall=None)
        self.assertEqual(ergebnis["code"], 1)
        self.assertIn("Fall existiert bereits", ergebnis["fehler"])
        status, ergebnis = self.befehl(["quatsch"])
        self.assertEqual(ergebnis["code"], 2)  # SystemExit der Argumentprüfung abgefangen
        self.assertIn("fehler:", ergebnis["fehler"])

    def test_wer_landet_im_protokoll(self):
        self.befehl_ok(["fall", "neu", "t", "--titel=Testfall", "--auftrag=Prüfen"], fall=None, wer="Nutzer Eins")
        self.befehl_ok(["hypothese", "neu", "--text=Eine Hypothese"], wer="Nutzer Eins")
        import sqlite3
        db = sqlite3.connect(os.path.join(self.wurzel, "t", "fall.db"))
        wer = db.execute("SELECT wer FROM protokoll WHERE aktion = 'hypothese neu'").fetchone()[0]
        db.close()
        self.assertEqual(wer, "Nutzer Eins")

    def test_befehl_ohne_fall_nur_fuer_neu_und_liste(self):
        status, ergebnis = self.befehl(["fall", "zeigen"], fall=None)
        self.assertEqual(status, 400)
        self.assertIn("Fall", ergebnis["fehler"])
        self.befehl_ok(["fall", "liste"], fall=None)

    def test_verbotene_befehle_und_optionen(self):
        self.fall_mit_quelle()
        ziel = os.path.join(self.wurzel, "ausserhalb.json")
        vorher = sorted(os.listdir(self.wurzel))
        verboten = [
            ["web"], ["web", "--port=1"],
            ["quelle", "datei", "/etc/hostname", "--titel=x"],
            ["fall", "sichern"], ["fall", "sichern", "--ziel", self.wurzel],
            ["fall", "laden", ziel],
            ["export", "--datei", ziel], ["export", "--datei=" + ziel], ["export", "--dat", ziel],
            ["dossier", "--ziel", self.wurzel], ["dossier", "--ziel=" + self.wurzel], ["dossier", "--zi", self.wurzel],
            ["--fall", "t", "fall", "zeigen"],
        ]
        for argv in verboten:
            status, ergebnis = self.befehl(argv)
            self.assertEqual(status, 403, argv)
            self.assertNotEqual(ergebnis["code"], 0, argv)
        self.assertFalse(os.path.exists(ziel))
        self.assertEqual(sorted(os.listdir(self.wurzel)), vorher)  # kein Zip, kein Dossier, kein Export
        self.assertEqual(os.listdir(os.path.join(self.wurzel, "t")).count("dossier.html"), 0)
        # Gewöhnliche Befehle laufen weiter, auch mit ähnlichen Optionen.
        self.befehl_ok(["export"])
        self.befehl_ok(["fall", "zeigen"])

    def test_zitat_von_stdin_mit_sonderzeichen(self):
        self.fall_mit_quelle()
        ergebnis = self.befehl_ok(["beleg", "neu", "--quelle=Q1", "--zitat=-", "--aussage=Er bestreitet es"],
                                  eingabe=ZITAT)
        self.assertIn("angelegt: B1", ergebnis["aus"])
        beleg = self.export_http()["belege"][0]
        self.assertEqual(beleg["zitat"], ZITAT)
        self.assertTrue(beleg["zitat_ok"])
        # Ein Zitat, das nicht im Text steht, wird mit der ähnlichsten Stelle abgelehnt.
        status, ergebnis = self.befehl(["beleg", "neu", "--quelle=Q1", "--zitat=-", "--aussage=x"],
                                       eingabe="Das steht so nirgends im gespeicherten Text, wirklich nicht")
        self.assertEqual(ergebnis["code"], 1)
        self.assertIn("Zitat nicht im Text von Q1 gefunden", ergebnis["fehler"])
        self.assertIn("ähnlichste Stelle", ergebnis["fehler"])
        self.assertEqual(len(self.export_http()["belege"]), 1)

    def test_werte_mit_bindestrich_am_anfang(self):
        self.fall_mit_quelle()
        self.befehl_ok(["hypothese", "neu", "--text=-5 Prozent"])
        self.assertEqual(self.export_http()["hypothesen"][0]["text"], "-5 Prozent")

    def test_quelle_per_adresse_gegen_lokalen_server(self):
        self.befehl_ok(["fall", "neu", "t", "--titel=Testfall", "--auftrag=Prüfen"], fall=None)
        with Testserver() as basis:
            ergebnis = self.befehl_ok(["quelle", "holen", basis + "/artikel", "--typ=medium"])
        self.assertIn("angelegt: Q1", ergebnis["aus"])
        self.assertEqual(self.export_http()["quellen"][0]["typ"], "medium")

    def test_behauptung_und_pruefung_mit_deutschem_fehler(self):
        self.fall_mit_quelle()
        self.befehl_ok(["beleg", "neu", "--quelle=Q1", "--zitat=-", "--aussage=x"], eingabe=ZITAT)
        self.befehl_ok(["behauptung", "neu", "--text=Eine Tatsache", "--art=tatsache", "--pro=B1"])
        status, ergebnis = self.befehl(["behauptung", "pruefen", "A1", "--status=belegt", "--vermerk=ok", "--pruefer=p"])
        self.assertEqual(ergebnis["code"], 1)
        self.assertIn("Obergrenze", ergebnis["fehler"])
        a = self.export_http()["behauptungen"][0]
        self.assertEqual(a["status"], "ungeprueft")
        self.assertTrue(a["obergrenze_grund"])


class Dateien(WebTest):
    def test_upload_einer_textdatei_als_quelle(self):
        self.befehl_ok(["fall", "neu", "t", "--titel=Testfall", "--auftrag=Prüfen"], fall=None)
        inhalt = "Ein hochgeladenes Protokoll. Der Zeuge sagte klar und deutlich etwas.".encode("utf-8")
        pfad = "/api/quelle-datei?fall=t&titel=Protokoll&typ=amtlich&name=..%2F..%2Fprotokoll.txt&wer=tester"
        status, _, daten = self.http("POST", pfad, inhalt, {"Content-Type": "application/octet-stream"})
        ergebnis = json.loads(daten.decode("utf-8"))
        self.assertEqual((status, ergebnis["code"]), (200, 0), ergebnis)
        self.assertIn("angelegt: Q1", ergebnis["aus"])
        quelle = self.export_http()["quellen"][0]
        self.assertEqual((quelle["art"], quelle["titel"], quelle["typ"]), ("datei", "Protokoll", "amtlich"))
        text = Path(self.wurzel, "t", "quellen", "Q1", "text.txt").read_text(encoding="utf-8")
        self.assertIn("Der Zeuge sagte", text)
        self.assertFalse(Path(self.wurzel).parent.joinpath("protokoll.txt").exists())
        # Dieselben Bytes noch einmal: bereits erfasst. Ohne Titel: Fehler des Werkzeugs.
        _, _, daten = self.http("POST", pfad, inhalt, {"Content-Type": "application/octet-stream"})
        self.assertIn("bereits erfasst: Q1", json.loads(daten.decode("utf-8"))["aus"])
        _, _, daten = self.http("POST", "/api/quelle-datei?fall=t&name=b.txt", b"anderer Inhalt, lang genug",
                                {"Content-Type": "application/octet-stream"})
        self.assertIn("--titel darf nicht leer sein", json.loads(daten.decode("utf-8"))["fehler"])

    def test_sichern_und_laden_ueber_http(self):
        self.fall_mit_quelle()
        self.befehl_ok(["beleg", "neu", "--quelle=Q1", "--zitat=-", "--aussage=x"], eingabe=ZITAT)
        vorher = self.export_http()
        status, antwort, zip_bytes = self.http("GET", "/api/sichern?fall=t")
        self.assertEqual(status, 200)
        self.assertEqual(antwort.getheader("Content-Type"), "application/zip")
        self.assertRegex(antwort.getheader("Content-Disposition"), r'attachment; filename="t-\d{8}-\d{4}\.zip"')
        self.assertTrue(zip_bytes.startswith(b"PK"))
        # Existiert der Fall schon, lädt `laden` nicht darüber.
        status, _, daten = self.http("POST", "/api/laden", zip_bytes, {"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 400)
        self.assertIn("Fall existiert bereits", json.loads(daten.decode("utf-8"))["fehler"])
        shutil.rmtree(os.path.join(self.wurzel, "t"))
        status, _, daten = self.http("POST", "/api/laden", zip_bytes, {"Content-Type": "application/octet-stream"})
        self.assertEqual((status, json.loads(daten.decode("utf-8"))), (200, {"slug": "t"}))
        nachher = self.export_http()
        for d in (vorher, nachher):
            d["fall"].pop("stand")
        self.assertEqual(vorher, nachher)
        self.assertEqual([n for n in os.listdir(self.wurzel) if n.startswith(".")], [])
        status, _, daten = self.http("POST", "/api/laden", b"kein zip", {"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 400)
        self.assertIn("Archiv nicht lesbar", json.loads(daten.decode("utf-8"))["fehler"])

    def test_exportiere_und_importiere(self):
        self.fall_mit_quelle()
        ziel = os.path.join(self.wurzel, "..", "ziel-%d" % os.getpid())
        self.addCleanup(shutil.rmtree, ziel, True)
        pfad = web.exportiere("t", ziel)
        self.assertTrue(os.path.isfile(pfad) and pfad.endswith(".zip"))
        shutil.rmtree(os.path.join(self.wurzel, "t"))
        self.assertEqual(web.importiere(pfad), "t")
        self.assertEqual(self.export_http()["quellen"][0]["titel"], "Quelle Eins")
        with self.assertRaises(web.Fehler):
            web.importiere(pfad)
        with self.assertRaises(web.Anfragefehler):
            web.exportiere("../t", ziel)

    def test_dossier_datei_enthaelt_den_titel(self):
        self.fall_mit_quelle()
        ziel = os.path.join(self.wurzel, "..", "dossier-%d" % os.getpid())
        self.addCleanup(shutil.rmtree, ziel, True)
        pfad = web.dossier_datei("t", ziel)
        html = Path(pfad).read_text(encoding="utf-8")
        self.assertIn("Testfall", html)
        self.assertNotIn("<base", html)  # die Datei bleibt das unveränderte Dossier
        self.assertTrue(html.startswith("<!DOCTYPE html>"))

    def test_dossier_eingebettet_hat_base_und_popups(self):
        self.fall_mit_quelle()
        self.befehl_ok(["beleg", "neu", "--quelle=Q1", "--zitat=-", "--aussage=x"], eingabe=ZITAT)
        self.befehl_ok(["behauptung", "neu", "--text=Eine Tatsache", "--art=tatsache", "--pro=B1"])
        status, antwort, roh = self.http("GET", "/api/dossier?fall=t")
        schlicht = roh.decode("utf-8")
        status, eingebettet_antwort, roh = self.http("GET", "/api/dossier?fall=t&eingebettet=1")
        eingebettet = roh.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertNotIn("<base", schlicht)
        self.assertIn('<base target="_blank">', eingebettet)
        self.assertIn('<a href="#', schlicht)  # das Dossier verlinkt innerhalb seiner selbst ...
        self.assertNotIn('<a href="#', eingebettet)  # ... das bleibt im Rahmen
        self.assertIn('<a target="_self" href="#', eingebettet)
        self.assertIn("Testfall", eingebettet)
        csp_schlicht = antwort.getheader("Content-Security-Policy")
        csp_eingebettet = eingebettet_antwort.getheader("Content-Security-Policy")
        for csp in (csp_schlicht, csp_eingebettet):
            self.assertIn("default-src 'none'", csp)
            self.assertNotIn("script-src", csp)
            self.assertRegex(csp, r"sandbox")
        self.assertNotIn("allow-popups", csp_schlicht)
        self.assertIn("allow-popups allow-popups-to-escape-sandbox", csp_eingebettet)
        self.assertNotIn("allow-scripts", csp_eingebettet)
        self.assertNotIn("allow-same-origin", csp_eingebettet)

    def test_faelle_und_export(self):
        self.assertEqual(self.http("GET", "/api/faelle")[2], b"[]")
        self.fall_mit_quelle()
        _, _, daten = self.http("GET", "/api/faelle")
        self.assertEqual(json.loads(daten), [{"slug": "t", "titel": "Testfall"}])
        daten = self.export_http()
        vergleich = json.loads(self.ok("--fall", "t", "export").out)
        for d in (daten, vergleich):
            d["fall"].pop("stand")
        self.assertEqual(daten, vergleich)
        optionen = json.loads(self.http("GET", "/api/optionen")[2])
        self.assertIn("amtlich", optionen["quellen_typen"])


class Eingaben(WebTest):
    def test_ungueltiger_slug_erreicht_das_dateisystem_nicht(self):
        self.fall_mit_quelle()
        aussen = Path(self.wurzel).parent / "t"
        vorher = sorted(os.listdir(self.wurzel))
        for slug in ("../t", "..%2Ft", "T", "a/b", "-x", "", "x" * 200, "t%00", "..", "t/../t", "%2e%2e"):
            for pfad in ("/api/export?fall=", "/api/dossier?fall=", "/api/sichern?fall=",
                         "/api/quelle-datei?titel=x&name=a&fall="):
                if "quelle-datei" in pfad:
                    status, _, _ = self.http("POST", pfad + slug, b"abc", {"Content-Type": "application/octet-stream"})
                else:
                    status, _, _ = self.http("GET", pfad + slug)
                self.assertIn(status, (400, 404), (pfad, slug))
        status, _, _ = self.http("GET", "/api/export")
        self.assertEqual(status, 400)
        status, ergebnis = self.befehl(["fall", "zeigen"], fall="../t")
        self.assertEqual(status, 400)
        status, ergebnis = self.befehl(["fall", "zeigen"], fall="gibtsnicht")
        self.assertEqual(status, 404)
        status, ergebnis = self.befehl(["fall", "neu", "../evil", "--titel=x", "--auftrag=y"], fall=None)
        self.assertEqual(ergebnis["code"], 1)
        self.assertIn("Slug muss", ergebnis["fehler"])
        self.assertFalse(aussen.exists())
        self.assertFalse((Path(self.wurzel).parent / "evil").exists())
        self.assertEqual(sorted(os.listdir(self.wurzel)), vorher)
        for aufruf in (web.exportiere, web.dossier_datei):
            with self.assertRaises(web.Anfragefehler):
                aufruf("../t", self.wurzel)

    def test_befehl_prueft_die_form(self):
        for koerper in ({"fall": None, "argv": "fall liste"}, {"fall": None, "argv": []},
                        {"fall": None, "argv": ["fall", 1]}, {"fall": None, "argv": ["-h"]},
                        {"fall": 5, "argv": ["fall", "zeigen"]}, {"fall": "t", "argv": ["fall", "zeigen"], "eingabe": 3},
                        [1, 2]):
            status, _, _ = self.http("POST", "/api/befehl", json.dumps(koerper), {"Content-Type": "application/json"})
            self.assertIn(status, (400, 403, 404), koerper)

    def test_unbekannte_pfade(self):
        self.assertEqual(self.http("GET", "/api/nichts")[0], 404)
        self.assertEqual(self.http("POST", "/api/nichts", "{}", {"Content-Type": "application/json"})[0], 405)


class Hintergrund(unittest.TestCase):
    def test_starte_im_hintergrund_liefert_denselben_server(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}):
            wurzel = os.path.join(tmp, "akten")
            alt = web._hintergrund
            web._hintergrund = None
            try:
                erst = web.starte_im_hintergrund(wurzel)
                self.assertEqual(set(erst), {"url", "port", "token"})
                self.assertEqual(erst["url"], "http://127.0.0.1:%d/?t=%s" % (erst["port"], erst["token"]))
                self.assertEqual(os.environ["RECHERCHE_FAELLE"], wurzel)
                self.assertTrue(os.path.isdir(wurzel))
                self.assertEqual(web.starte_im_hintergrund(wurzel), erst)
                verbindung = http.client.HTTPConnection("127.0.0.1", erst["port"], timeout=30)
                verbindung.request("GET", "/api/faelle", headers={"X-Recherche-Token": erst["token"]})
                antwort = verbindung.getresponse()
                self.assertEqual((antwort.status, antwort.read()), (200, b"[]"))
                verbindung.close()
            finally:
                if web._hintergrund is not None:
                    web._hintergrund.stoppe()
                web._hintergrund = alt


class Seite(unittest.TestCase):
    def setUp(self):
        self.html = (REPO / "recherche" / "web_ui.html").read_text(encoding="utf-8")

    def test_keine_fremden_ressourcen(self):
        self.assertIsNone(re.search(r"https?://", self.html))
        self.assertIsNone(re.search(r"(?:src|href|action)\s*=\s*[\"']?//", self.html))
        self.assertNotIn("@import", self.html)
        self.assertNotRegex(self.html, r"url\(\s*[\"']?(?!data:)")

    def test_keine_html_zuweisung_aus_daten(self):
        for gefaehrlich in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                            "new Function", "setTimeout(\"", "javascript:"):
            self.assertNotIn(gefaehrlich, self.html, gefaehrlich)

    def test_skript_und_stil_tragen_den_nonce(self):
        for tag in re.findall(r"<(?:script|style)\b[^>]*>", self.html):
            self.assertIn('nonce="__NONCE__"', tag)
        self.assertNotRegex(self.html, r"<[a-z]+[^>]*\sstyle=")  # Inline-Stilattribute blockiert die CSP
        self.assertNotRegex(self.html, r"<[a-z]+[^>]*\son[a-z]+=")  # keine Inline-Handler

    def test_dossier_rahmen_ohne_skripterlaubnis(self):
        self.assertIn("sandbox: 'allow-popups allow-popups-to-escape-sandbox'", self.html)
        self.assertNotIn("allow-scripts", self.html)
        self.assertNotIn("allow-same-origin", self.html)

    def test_android_bruecke_und_neuladen(self):
        for name in ("importieren", "exportieren", "dossierTeilen", "oeffneExtern", "neuLaden"):
            self.assertIn(name, self.html)


if __name__ == "__main__":
    unittest.main()
