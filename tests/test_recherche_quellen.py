"""Tests für recherche.quellen: Normalisierung, Zitatprüfung, Abruf, Textgewinnung."""

import importlib.util
import logging
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_recherche_basis import FallTest, Testserver  # noqa: E402
from recherche import quellen  # noqa: E402
from recherche.store import Fehler  # noqa: E402

TEXT = ("Die Ministerin sagte: „Wir prüfen den Vorgang – gründlich und\n schnell“ und kündigte "
        "ein Gespräch an.\nDer Rechnungshof stellte fest, dass die Vergabe ohne Ausschreibung "
        "erfolgte und der Auftrag an eine Firma des Bürgermeisters ging, obwohl ein günstigeres "
        "Angebot vorlag.")


class NormalisierungTest(unittest.TestCase):
    def test_typografie_und_leerraum(self):
        roh = "A­ B​C  „x“ ‚y‘ – — «z»\n\t d"
        self.assertEqual(quellen.normalisiere(roh), "A BC \"x\" 'y' - - \"z\" d")

    def test_gross_klein_bleibt(self):
        self.assertNotEqual(quellen.normalisiere("Haus"), quellen.normalisiere("haus"))

    def test_nfc(self):
        self.assertEqual(quellen.normalisiere("ü"), "ü")

    def test_teile_an_auslassung(self):
        self.assertEqual(quellen.zitat_teile("Anfang des Satzes […] Ende des Satzes [...] noch mehr Text"),
                         ["Anfang des Satzes", "Ende des Satzes", "noch mehr Text"])

    def test_reihenfolge_und_ueberlappung(self):
        text = quellen.normalisiere("alpha alpha alpha beta beta beta gamma gamma gamma")
        self.assertEqual(quellen.finde_teile(["alpha alpha", "beta beta", "gamma gamma"], text), 0)
        self.assertIsNone(quellen.finde_teile(["beta beta", "alpha alpha"], text))
        self.assertIsNone(quellen.finde_teile(["alpha alpha alpha", "alpha alpha alpha"], text))

    def test_teile_duerfen_nicht_weit_auseinander_liegen(self):
        teile = ["Anfang des Zitats", "Ende des Zitats"]
        text = quellen.normalisiere("Anfang des Zitats " + "füllwort " * 400 + "Ende des Zitats")
        self.assertIsNone(quellen.finde_teile(teile, text))
        self.assertEqual(quellen.finde_teile(teile, text, max_spanne=None), 0)

    def test_spanne_nimmt_ein_spaeteres_vorkommen_des_anfangs(self):
        teile = ["Anfang des Zitats", "Ende des Zitats"]
        text = quellen.normalisiere("Anfang des Zitats " + "füllwort " * 400
                                    + "Anfang des Zitats und gleich das Ende des Zitats")
        self.assertGreater(quellen.finde_teile(teile, text), 3000)

    def test_formpruefung(self):
        with self.assertRaises(Fehler):
            quellen.pruefe_zitatform("zu kurz")
        with self.assertRaises(Fehler):
            quellen.pruefe_zitatform("x" * 701)
        with self.assertRaises(Fehler):
            quellen.pruefe_zitatform("Langer erster Teil […] kurz")

    def test_aehnlichste_stelle_ist_schnell(self):
        gross = " ".join("wort%d" % (i % 5000) for i in range(170000))
        gross += " der Bundesrechnungshof prüfte die Vergabe der Autobahnmaut gründlich"
        start = time.time()
        offset, passage = quellen.aehnlichste_stelle("Bundesrechnungshof prüfte die Vergabe der Autobahnmaut", gross)
        self.assertLess(time.time() - start, 5)
        self.assertIn("Bundesrechnungshof", passage)
        self.assertGreater(offset, 1000000)


class ZitatCliTest(FallTest):
    def setUp(self):
        super().setUp()
        self.neuer_fall()
        self.q = self.quelle(TEXT)

    def versuche(self, zitat):
        return self.cli("beleg", "neu", "--quelle", self.q, "--zitat", zitat, "--aussage", "x")

    def test_toleranz_bei_leerraum_anfuehrungszeichen_und_strichen(self):
        zitat = 'Ministerin sagte: "Wir prüfen den Vorgang - gründlich und schnell" und kündigte'
        ergebnis = self.versuche(zitat)
        self.assertEqual(ergebnis.code, 0, ergebnis.err)
        self.assertEqual(ergebnis.zeilen[0], "angelegt: B1")

    def test_gross_klein_wird_geprueft(self):
        self.assertEqual(self.versuche("die ministerin sagte: „Wir prüfen den Vorgang").code, 1)

    def test_auslassungen_in_reihenfolge(self):
        zitat = "Der Rechnungshof stellte fest […] ohne Ausschreibung erfolgte [...] günstigeres Angebot vorlag."
        self.assertEqual(self.versuche(zitat).code, 0)

    def test_auslassungen_falsche_reihenfolge(self):
        zitat = "ohne Ausschreibung erfolgte […] Der Rechnungshof stellte fest"
        ergebnis = self.versuche(zitat)
        self.assertEqual(ergebnis.code, 1)
        self.assertIn("fehler: Zitat nicht im Text von Q1 gefunden.", ergebnis.err)

    def test_zitatteil_zu_kurz(self):
        ergebnis = self.versuche("Der Rechnungshof stellte fest […] vorlag.")
        self.assertEqual(ergebnis.code, 1)
        self.assertIn("Zitatteil zu kurz", ergebnis.err)

    def test_erfundenes_zitat_nennt_aehnlichste_stelle(self):
        ergebnis = self.versuche("Der Rechnungshof stellte fest, dass die Vergabe ordnungsgemäß ausgeschrieben wurde.")
        self.assertEqual(ergebnis.code, 1)
        self.assertIn("fehler: Zitat nicht im Text von Q1 gefunden.", ergebnis.err)
        self.assertIn("ähnlichste Stelle (Zeichen ", ergebnis.err)
        self.assertIn("Rechnungshof", ergebnis.err)
        self.assertIn("Auslassungen mit […] kennzeichnen.", ergebnis.err)
        self.assertEqual(self.export()["belege"], [])

    def test_zu_kurz_und_zu_lang(self):
        for zitat in ("Ministerin sag", "x" * 701):
            ergebnis = self.versuche(zitat)
            self.assertEqual(ergebnis.code, 1)
            self.assertIn("fehler: Zitat muss 15 bis 700 Zeichen lang sein", ergebnis.err)

    def test_grenze_700_zeichen(self):
        text = " ".join("wort%04d" % i for i in range(200))
        qid = self.quelle(text, titel="lang")
        zitat700 = text[:700]
        self.assertEqual(self.cli("beleg", "neu", "--quelle", qid, "--zitat", zitat700, "--aussage", "x").code, 0)
        self.assertEqual(self.cli("beleg", "neu", "--quelle", qid, "--zitat", text[:701], "--aussage", "x").code, 1)

    def test_zitat_von_stdin_mit_sonderzeichen(self):
        zitat = 'Er rief: "Das gehört mir!" und \'$HOME\' sei `kein` Befehl, sagte er.'
        qid = self.quelle("Vorspann.\n" + zitat + "\nNachspann.", titel="sonder")
        ergebnis = self.cli("beleg", "neu", "--quelle", qid, "--zitat", "-", "--aussage", "x",
                            eingabe="  " + zitat + "\n")
        self.assertEqual(ergebnis.code, 0, ergebnis.err)
        beleg = self.export()["belege"][0]
        self.assertEqual(beleg["zitat"], zitat)
        self.assertTrue(beleg["zitat_ok"])

    def test_stelle_ist_offset_im_gespeicherten_text(self):
        # Zeilenumbrüche, Leerzeilen, weiche Trennstriche und typografische Zeichen davor
        vorspann = "".join("Zeile %d mit „Zitat“ – und Ver\u00adwaltung \n\n\n  \t" % i for i in range(300))
        text = vorspann + "Der Bürgermeister sagte:\n „Wir   prüfen den Vorgang – gründlich“ und ging."
        qid = self.quelle(text, titel="Lang")
        zitat = 'Der Bürgermeister sagte: "Wir prüfen den Vorgang - gründlich" und ging.'
        ergebnis = self.ok("beleg", "neu", "--quelle", qid, "--zitat", zitat, "--aussage", "x")
        stelle = self.export()["belege"][0]["stelle"]
        self.assertEqual(ergebnis.zeilen[1], "quelle: %s | stelle: %d" % (qid, stelle))
        self.assertEqual(ergebnis.zeilen[2], "kontext: python3 -m recherche quelle lesen %s --ab %d --laenge 1200"
                         % (qid, stelle - 300))
        gespeichert = self.wurzel_text(qid)
        self.assertGreater(stelle, 5000)
        self.assertTrue(quellen.normalisiere(gespeichert[stelle:stelle + 40]).startswith(zitat[:25]))
        self.assertTrue(gespeichert[stelle:].startswith("Der Bürgermeister"))
        gelesen = self.ok("quelle", "lesen", qid, "--ab", stelle, "--laenge", 100).out
        self.assertIn("Der Bürgermeister sagte:", gelesen)

    def test_stelle_bei_mehreren_teilen_ist_der_erste_teil(self):
        text = "Vorspann\n\n" * 50 + "Anfang des Satzes und viele Worte dazwischen, Ende des Satzes steht hier."
        qid = self.quelle(text, titel="Teile")
        self.ok("beleg", "neu", "--quelle", qid, "--zitat", "Anfang des Satzes […] Ende des Satzes", "--aussage", "x")
        stelle = self.export()["belege"][0]["stelle"]
        self.assertTrue(self.wurzel_text(qid)[stelle:].startswith("Anfang des Satzes"))

    def test_aehnlichste_stelle_nennt_offset_im_gespeicherten_text(self):
        text = "Leer\n\n\nzeilen " * 100 + "Der Rechnungshof prüfte die Vergabe der Autobahnmaut gründlich."
        qid = self.quelle(text, titel="Fund")
        ergebnis = self.fehler("beleg", "neu", "--quelle", qid, "--aussage", "x",
                               "--zitat", "Der Rechnungshof prüfte die Vergabe der Autobahnmaut nicht")
        offset = int(ergebnis.err.split("(Zeichen ")[1].split(")")[0])
        self.assertIn("Rechnungshof", self.wurzel_text(qid)[offset:offset + 30])

    def wurzel_text(self, qid):
        with open(os.path.join(self.wurzel, "t", "quellen", qid, "text.txt"), encoding="utf-8") as f:
            return f.read()

    def test_lesen_ohne_zerschnittene_woerter_und_ohne_wiederholung(self):
        woerter = ["wort%03d" % i for i in range(400)]
        woerter[100] = "Haushalt"
        woerter[103] = "Haushalt"
        woerter[300] = "Haushalt"
        text = " ".join(woerter)
        qid = self.quelle(text, titel="Treffer")
        ergebnis = self.ok("quelle", "lesen", qid, "--suche", "haushalt")
        bloecke = [z for z in ergebnis.zeilen if z.startswith("[Zeichen ")]
        self.assertEqual(len(bloecke), 2)  # die ersten beiden Treffer verschmelzen
        self.assertIn("3 Treffer", ergebnis.zeilen)
        self.assertEqual(ergebnis.out.count("wort102"), 1)
        for block, inhalt in zip(bloecke, [z for z in ergebnis.zeilen if z.startswith("wort")]):
            start, ende = (int(x) for x in block[len("[Zeichen "):-1].split("-"))
            self.assertEqual(text[start:ende], inhalt)
            self.assertTrue(start == 0 or text[start - 1] == " ")
            self.assertTrue(ende == len(text) or text[ende] == " ")
            self.assertTrue(inhalt.startswith("wort"))
            self.assertTrue(inhalt.split(" ")[-1].startswith("wort") and len(inhalt.split(" ")[-1]) == 7)

    def test_lesen_fenster_endet_am_wortende(self):
        text = "alpha beta gamma delta epsilon " * 20
        qid = self.quelle(text, titel="Fenster")
        ergebnis = self.ok("quelle", "lesen", qid, "--ab", "2", "--laenge", "11")
        inhalt = ergebnis.zeilen[2]
        self.assertEqual(inhalt, text[2:len(inhalt) + 2])
        self.assertTrue(inhalt.startswith("pha beta"))
        self.assertEqual(inhalt, "pha beta gamma")
        self.assertIn("-- Zeichen 2 bis 16 von ", ergebnis.out)


class AbrufTest(FallTest):
    @classmethod
    def setUpClass(cls):
        cls._server = Testserver()
        cls.basis = cls._server.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._server.__exit__(None, None, None)

    def setUp(self):
        super().setUp()
        self.neuer_fall()

    def holen(self, pfad, *optionen, env=None):
        return self.cli("quelle", "holen", self.basis + pfad, *optionen, env=env)

    def test_html_text_und_metadaten(self):
        ergebnis = self.holen("/artikel", "--typ", "medium")
        self.assertEqual(ergebnis.code, 0, ergebnis.err)
        self.assertEqual(ergebnis.zeilen[0], "angelegt: Q1")
        self.assertEqual(ergebnis.zeilen[1], "titel: Der Og-Titel")
        self.assertEqual(ergebnis.zeilen[2], "herausgeber: Beispiel Zeitung | datum: 2026-05-01 | typ: medium")
        self.assertRegex(ergebnis.zeilen[3], r"^zeichen: \d+ \| sha256: [0-9a-f]{12}$")
        self.assertEqual(ergebnis.zeilen[4], 'lesen: python3 -m recherche quelle lesen Q1 --suche "<Begriff>"')
        self.assertIn("warnung: kaum Text extrahiert", ergebnis.out)
        text = (self.wurzel_text("t", "Q1"))
        for erwartet in ("Überschrift", "Die Behörde sagte: „Das ist ein Test“ & mehr – später.",
                         "Verwaltung und Geschäft", "Zeile eins\nZeile zwei"):
            self.assertIn(erwartet, text)
        for verboten in ("SKRIPTINHALT", "verstecktes-css", "BITTE-JS", "VORLAGE", "SVGTITEL", "Seitentitel", "­", "​"):
            self.assertNotIn(verboten, text)
        self.assertNotIn("\n\n\n", text)
        quelle = self.export()["quellen"][0]
        self.assertEqual((quelle["autor"], quelle["art"], quelle["url"]), ("Erika Muster", "web", self.basis + "/artikel"))
        self.assertEqual(quelle["zeichen"], len(text))
        self.assertEqual(len(quelle["sha256"]), 64)

    def wurzel_text(self, slug, qid):
        with open(os.path.join(self.wurzel, slug, "quellen", qid, "text.txt"), encoding="utf-8") as f:
            return f.read()

    def test_umleitung_speichert_endgueltige_url(self):
        self.assertEqual(self.holen("/weiter").code, 0)
        quelle = self.export()["quellen"][0]
        self.assertEqual(quelle["url"], self.basis + "/artikel")

    def test_zu_viele_umleitungen(self):
        ergebnis = self.holen("/endlos")
        self.assertEqual(ergebnis.code, 1)
        self.assertIn("fehler: Abruf fehlgeschlagen (", ergebnis.err)
        self.assertEqual(self.export()["quellen"], [])

    def test_404_speichert_nichts(self):
        ergebnis = self.holen("/gibtsnicht")
        self.assertEqual(ergebnis.code, 1)
        self.assertEqual(ergebnis.err.strip(), "fehler: Abruf fehlgeschlagen (HTTP 404)")
        self.assertEqual(self.export()["quellen"], [])
        self.assertEqual(os.listdir(os.path.join(self.wurzel, "t", "quellen")), [])

    def test_zu_grosse_antwort(self):
        ergebnis = self.holen("/gross")
        self.assertEqual(ergebnis.code, 1)
        self.assertIn("fehler: Antwort größer als 25 MB", ergebnis.err)
        self.assertEqual(self.export()["quellen"], [])

    def test_interne_adresse_ohne_freigabe(self):
        env = dict(self.env)
        del env["RECHERCHE_LOKAL_ERLAUBT"]
        ergebnis = self.holen("/artikel", env=env)
        self.assertEqual(ergebnis.code, 1)
        self.assertIn("fehler: interne Adresse nicht erlaubt", ergebnis.err)
        self.assertEqual(self.export()["quellen"], [])

    def test_nur_http_und_https(self):
        ergebnis = self.cli("quelle", "holen", "file:///etc/passwd")
        self.assertEqual(ergebnis.code, 1)
        self.assertIn("fehler:", ergebnis.err)

    def test_gleicher_inhalt_zweimal(self):
        self.assertEqual(self.holen("/artikel").code, 0)
        zweites = self.holen("/weiter")
        self.assertEqual(zweites.code, 0)
        self.assertEqual(zweites.zeilen, ["bereits erfasst: Q1"])
        self.assertEqual(len(self.export()["quellen"]), 1)

    def test_json_wird_als_text_gespeichert(self):
        self.assertEqual(self.holen("/daten.json").code, 0)
        self.assertEqual(self.wurzel_text("t", "Q1"), '{"name": "Müller", "betrag": 1200}')
        roh = os.path.join(self.wurzel, "t", "quellen", "Q1", "roh")
        with open(roh, "rb") as f:
            self.assertEqual(f.read(), '{"name": "Müller", "betrag": 1200}'.encode("utf-8"))

    def test_zeichensatz_aus_header(self):
        self.assertEqual(self.holen("/latin1").code, 0)
        self.assertIn("Größe in Zoll: 5 Äpfel", self.wurzel_text("t", "Q1"))

    def test_lesen_suche_und_fenster(self):
        self.holen("/artikel")
        suche = self.ok("quelle", "lesen", "Q1", "--suche", "später")
        self.assertTrue(suche.zeilen[0].startswith("Q1 | Der Og-Titel | Beispiel Zeitung | 2026-05-01 | typ unbekannt | "))
        self.assertIn("1 Treffer", suche.zeilen)
        self.assertTrue(any(z.startswith("[Zeichen ") for z in suche.zeilen))
        fenster = self.ok("quelle", "lesen", "Q1", "--ab", "3", "--laenge", "10")
        self.assertIn("-- Zeichen 3 bis 23 von", fenster.out)  # Ende wird bis zum Wortende verlängert

    def test_archiv_nur_mit_flag_und_best_effort(self):
        with mock.patch.object(quellen, "_lade", side_effect=OSError("kein Netz")):
            archiv_url, hinweise = quellen.archiviere("https://example.org/x", sichern=True)
        self.assertEqual((archiv_url, hinweise), ("", ["hinweis: Archiv nicht erreichbar"]))

    def test_archiv_antwort_wird_ausgewertet(self):
        antwort = mock.MagicMock()
        antwort.__enter__.return_value = antwort
        antwort.read.return_value = (b'{"archived_snapshots": {"closest": {"available": true, '
                                     b'"url": "http://web.archive.org/web/20260101000000/https://example.org/x"}}}')
        with mock.patch.object(quellen, "_lade", return_value=antwort) as lade:
            self.assertEqual(quellen.archiv_suchen("https://example.org/x"),
                             "http://web.archive.org/web/20260101000000/https://example.org/x")
        self.assertIn("archive.org/wayback/available?url=https%3A%2F%2Fexample.org%2Fx", lade.call_args[0][0])


def mini_pdf(seiten):
    """Ein kleines PDF ohne fremde Bibliothek: je Seite eine Liste von Zeilen (WinAnsi)."""
    objekte = []

    def obj(inhalt):
        objekte.append(inhalt)
        return len(objekte)

    schrift = obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    inhalte = []
    for zeilen in seiten:
        teile = [b"BT /F1 12 Tf 72 720 Td 14 TL"]
        for zeile in zeilen:
            roh = zeile.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
            teile.append(b"(" + roh + b") Tj T*")
        teile.append(b"ET")
        strom = b"\n".join(teile)
        inhalte.append(obj(b"<< /Length %d >>\nstream\n" % len(strom) + strom + b"\nendstream"))
    baum = len(objekte) + len(seiten) + 1
    kinder = [obj(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
                  b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (baum, inhalt, schrift)) for inhalt in inhalte]
    obj(b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kinder) + b"] /Count %d >>" % len(kinder))
    katalog = obj(b"<< /Type /Catalog /Pages %d 0 R >>" % baum)
    aus = bytearray(b"%PDF-1.4\n")
    versatz = []
    for nummer, inhalt in enumerate(objekte, 1):
        versatz.append(len(aus))
        aus += b"%d 0 obj\n" % nummer + inhalt + b"\nendobj\n"
    tabelle = len(aus)
    aus += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objekte) + 1)
    for stelle in versatz:
        aus += b"%010d 00000 n \n" % stelle
    aus += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objekte) + 1, katalog, tabelle)
    return bytes(aus)


PDF_SEITEN = [["Der Beirat tagte am 3. März 2024 in Köln.", "Den Vorsitz führte die Staatssekretärin."],
              ["Die Förderung beträgt 1,2 Millionen Euro (netto)."]]
HAT_PYPDF = importlib.util.find_spec("pypdf") is not None
HAT_PDFTOTEXT = shutil.which("pdftotext") is not None


class PdfTest(FallTest):
    """PDF-Text über beide Wege. In der Android-App gibt es nur pypdf."""

    def pruefe_text(self, text):
        self.assertIn("Der Beirat tagte am 3. März 2024 in Köln.", text)
        self.assertIn("Den Vorsitz führte die Staatssekretärin.", text)
        self.assertIn("Die Förderung beträgt 1,2 Millionen Euro (netto).", text)
        self.assertLess(text.index("Staatssekretärin"), text.index("Förderung"))

    @unittest.skipUnless(HAT_PYPDF, "pypdf ist nicht installiert")
    def test_text_ueber_pypdf(self):
        with mock.patch.object(quellen.shutil, "which", return_value=None):
            self.pruefe_text(quellen.extrahiere_pdf(mini_pdf(PDF_SEITEN)))

    @unittest.skipUnless(HAT_PDFTOTEXT, "pdftotext ist nicht installiert")
    def test_text_ueber_pdftotext(self):
        self.pruefe_text(quellen.extrahiere_pdf(mini_pdf(PDF_SEITEN)))

    def test_ohne_werkzeug_bleibt_der_text_leer(self):
        with mock.patch.object(quellen.shutil, "which", return_value=None), \
                mock.patch.dict(sys.modules, {"pypdf": None}):
            self.assertEqual(quellen.extrahiere_pdf(mini_pdf(PDF_SEITEN)), "")

    def test_kaputtes_pdf_bricht_nicht_ab(self):
        logging.disable(logging.CRITICAL)  # pypdf meldet das kaputte Dokument als Warnung
        self.addCleanup(logging.disable, logging.NOTSET)
        self.assertEqual(quellen.extrahiere_pdf(b"%PDF-1.4\nkein gueltiges Dokument"), "")

    @unittest.skipUnless(HAT_PYPDF, "pypdf ist nicht installiert")
    def test_pdf_als_quelle_und_beleg_ohne_pdftotext(self):
        self.neuer_fall()
        with tempfile.TemporaryDirectory() as ordner:
            pfad = os.path.join(ordner, "protokoll.pdf")
            with open(pfad, "wb") as datei:
                datei.write(mini_pdf(PDF_SEITEN))
            leer = os.path.join(ordner, "leer")
            os.mkdir(leer)
            env = dict(self.env, PATH=leer)
            qid = self.neue_id("quelle", "datei", pfad, "--titel", "Protokoll", env=env)
        self.assertEqual(self.export()["quellen"][0]["art"], "datei")
        ergebnis = self.cli("beleg", "neu", "--quelle", qid, "--aussage", "x",
                            "--zitat", "Den Vorsitz führte die Staatssekretärin. […] Förderung beträgt 1,2 Millionen Euro")
        self.assertEqual(ergebnis.code, 0, ergebnis.err)
        falsch = self.cli("beleg", "neu", "--quelle", qid, "--aussage", "x",
                          "--zitat", "Den Vorsitz führte der Staatssekretär.")
        self.assertEqual(falsch.code, 1)


if __name__ == "__main__":
    unittest.main()
