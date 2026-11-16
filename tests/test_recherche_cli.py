"""Tests für CLI, Integritätsprüfung (pruefe), Export, Fallauswahl und Parallelität."""

import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_recherche_basis import FallTest  # noqa: E402

TEXT = "Der Stadtrat hat am 5. Mai 2026 den Haushalt mit 31 zu 12 Stimmen beschlossen."
ZITAT = "Der Stadtrat hat am 5. Mai 2026 den Haushalt"
TEXT2 = "Laut Protokoll wurde der Haushalt 2026 am Montag im Stadtrat verabschiedet."
ZITAT2 = "der Haushalt 2026 am Montag im Stadtrat"


class FallAuswahlTest(FallTest):
    def test_kein_fall(self):
        ergebnis = self.fehler("quelle", "liste")
        self.assertIn("fehler: kein Fall vorhanden", ergebnis.err)

    def test_ein_fall_wird_automatisch_gewaehlt(self):
        self.neuer_fall("eins")
        self.assertEqual(self.ok("fall", "zeigen").zeilen[0], "Fall eins: Testfall")

    def test_zwei_faelle(self):
        self.neuer_fall("eins")
        self.neuer_fall("zwei")
        ergebnis = self.fehler("fall", "zeigen")
        self.assertIn("mehrere Fälle vorhanden (eins, zwei)", ergebnis.err)
        self.assertTrue(self.ok("--fall", "zwei", "fall", "zeigen").zeilen[0].startswith("Fall zwei:"))
        env = dict(self.env, RECHERCHE_FALL="eins")
        self.assertTrue(self.ok("fall", "zeigen", env=env).zeilen[0].startswith("Fall eins:"))
        self.assertIn("unbekannt: Fall drei", self.fehler("--fall", "drei", "fall", "zeigen").err)

    def test_fall_liste_und_slug(self):
        self.assertIn("keine Fälle", self.ok("fall", "liste").out)
        self.neuer_fall("a-1")
        self.assertEqual(self.ok("fall", "liste").zeilen, ["a-1 | Testfall"])
        self.fehler("fall", "neu", "Gross", "--titel", "x", "--auftrag", "y")
        self.assertIn("existiert bereits", self.fehler("fall", "neu", "a-1", "--titel", "x", "--auftrag", "y").err)

    def test_nutzungsfehler_ist_exit_2(self):
        self.fehler("fall", "neu", code=2)
        self.fehler("quatsch", code=2)
        self.neuer_fall()
        self.fehler("fall", "setzen", code=2)

    def test_wer_wird_protokolliert(self):
        self.neuer_fall()
        self.ok("--wer", "Anna", "hypothese", "neu", "--text", "Eine Hypothese")
        db = sqlite3.connect(os.path.join(self.wurzel, "t", "fall.db"))
        zeilen = db.execute("SELECT wer, aktion, objekt FROM protokoll ORDER BY nr").fetchall()
        db.close()
        self.assertEqual(zeilen[-1], ("Anna", "hypothese neu", "H1"))
        self.assertEqual(zeilen[0][0], "tester")


class WaechterTest(FallTest):
    def setUp(self):
        super().setUp()
        self.neuer_fall()

    def test_akteur_namensdublette(self):
        self.assertEqual(self.neue_id("akteur", "neu", "--art", "person", "--name", "Max Müller"), "P1")
        self.assertEqual(self.neue_id("akteur", "neu", "--art", "organisation", "--name", "Müller GmbH"), "O1")
        ergebnis = self.fehler("akteur", "neu", "--art", "person", "--name", "  MAX   müller ")
        self.assertEqual(ergebnis.err.strip(), "fehler: Akteur mit diesem Namen existiert bereits: P1. "
                                               "Bei einer anderen Person gleichen Namens --trotzdem angeben.")
        self.assertEqual(self.neue_id("akteur", "neu", "--art", "person", "--name", "max müller", "--trotzdem"), "P2")
        liste = self.ok("akteur", "liste").zeilen
        self.assertIn("O1 | organisation | Müller GmbH | organisation", liste)
        self.assertIn("P1 | person | Max Müller | unbekannt", liste)

    def test_unbekannte_ids(self):
        q1 = self.quelle(TEXT, "medium", "B")
        faelle = [
            ("beleg", "neu", "--quelle", "Q9", "--zitat", ZITAT, "--aussage", "x"),
            ("beleg", "neu", "--quelle", "B1", "--zitat", ZITAT, "--aussage", "x"),
            ("beleg", "zeigen", "B9"),
            ("behauptung", "zeigen", "A9"),
            ("behauptung", "neu", "--text", "t", "--art", "tatsache", "--pro", "B9"),
            ("quelle", "lesen", "Q9"),
            ("frage", "neu", "--text", "t", "--hypothese", "H9"),
            ("akteur", "setzen", "P9", "--notiz", "x"),
            ("konfrontation", "antwort", "K9", "--text", "x"),
        ]
        for argumente in faelle:
            ergebnis = self.fehler(*argumente)
            self.assertRegex(ergebnis.err, r"^fehler: unbekannt: [A-Z]\d+\n", argumente)
        self.assertEqual(self.fehler("beleg", "zeigen", "B9").err, "fehler: unbekannt: B9\n")
        self.assertEqual(q1, "Q1")

    def test_datumsform(self):
        for datum in ("2026-13", "26", "2026-02-30", "gestern"):
            self.assertEqual(self.cli("ereignis", "neu", "--datum", datum, "--text", "x", "--beleg", "B1").code, 1)
        q1 = self.quelle(TEXT, "medium", "B")
        b1 = self.beleg(q1, ZITAT)
        for datum in ("2026", "2026-05", "2026-05-01"):
            self.ok("ereignis", "neu", "--datum", datum, "--text", "x", "--beleg", b1)
        self.assertEqual([e["datum"] for e in self.export()["ereignisse"]], ["2026", "2026-05", "2026-05-01"])

    def test_quelle_lesen_standardlaenge(self):
        text = "abcdefghi " * 400
        q1 = self.quelle(text)
        ergebnis = self.ok("quelle", "lesen", q1)
        self.assertIn("-- Zeichen 0 bis 2500 von 4000; weiter mit --ab 2500", ergebnis.out)


class PruefeTest(FallTest):
    def setUp(self):
        super().setUp()
        self.neuer_fall()
        self.q1 = self.quelle(TEXT, "medium", "B", titel="Zeitung")
        self.b1 = self.beleg(self.q1, ZITAT)
        self.a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", self.b1)
        self.pruefen(self.a1, "gestuetzt")

    def pruefen(self, aid, status):
        self.ok("behauptung", "pruefen", aid, "--status", status, "--vermerk", "ok", "--pruefer", "Anna")

    def pruefe(self, erwartet_code=None):
        ergebnis = self.cli("pruefe")
        if erwartet_code is not None:
            self.assertEqual(ergebnis.code, erwartet_code, ergebnis.out)
        return ergebnis

    def hat(self, ergebnis, praefix):
        return any(z.startswith(praefix + ":") for z in ergebnis.zeilen)

    def pruefe_kommt_und_geht(self, praefix, ausloeser, behebung, code_vorher):
        """`ausloeser` und `behebung` sind Funktionen ohne Argumente."""
        self.assertFalse(self.hat(self.pruefe(), praefix))
        ausloeser()
        vorher = self.pruefe(code_vorher)
        self.assertTrue(self.hat(vorher, praefix), vorher.out)
        behebung()
        self.assertFalse(self.hat(self.pruefe(), praefix))

    def test_sauberer_fall_hat_keine_sperren(self):
        ergebnis = self.pruefe(0)
        self.assertEqual(ergebnis.zeilen[-1], "Keine Sperren.")
        self.assertTrue(self.hat(ergebnis, "HINWEIS ABHAENGIG A1"))

    def test_zitat(self):
        pfad = os.path.join(self.wurzel, "t", "quellen", self.q1, "text.txt")
        with open(pfad, encoding="utf-8") as f:
            original = f.read()

        def schreiben(inhalt):
            with open(pfad, "w", encoding="utf-8") as f:
                f.write(inhalt)
        self.pruefe_kommt_und_geht("SPERRE ZITAT B1", lambda: schreiben("Etwas ganz anderes."),
                                   lambda: schreiben(original), 1)
        self.assertFalse(self.export()["belege"][0]["zitat_ok"] is False)

    def test_unbelegt_und_ungeprueft(self):
        a2 = []

        def ausloeser():
            a2.append(self.behauptung("Ohne Beleg", "tatsache"))
        self.pruefe_kommt_und_geht("SPERRE UNBELEGT A2", ausloeser,
                                   lambda: self.ok("behauptung", "beleg", a2[0], "--pro", self.b1), 1)
        self.assertTrue(self.hat(self.pruefe(), "SPERRE UNGEPRUEFT A2"))
        self.pruefen(a2[0], "gestuetzt")
        self.assertFalse(self.hat(self.pruefe(), "SPERRE UNGEPRUEFT A2"))
        self.pruefe(0)

    def test_widerspruch(self):
        q2 = self.quelle(TEXT2, "medium", "C", titel="Andere")
        b2 = self.beleg(q2, ZITAT2)
        self.pruefe_kommt_und_geht(
            "SPERRE WIDERSPRUCH A1",
            lambda: (self.ok("behauptung", "beleg", self.a1, "--contra", b2), self.pruefen(self.a1, "unbestaetigt")),
            lambda: self.pruefen(self.a1, "strittig"), 1)
        self.pruefen(self.a1, "unbestaetigt")
        self.assertTrue(self.hat(self.pruefe(), "SPERRE WIDERSPRUCH A1"))
        self.ok("behauptung", "setzen", self.a1, "--klaerung", "Gegenbeleg betrifft anderen Haushalt")
        self.assertFalse(self.hat(self.pruefe(), "SPERRE WIDERSPRUCH A1"))

    def test_quelle_unbewertet(self):
        q2 = self.quelle(TEXT2)  # typ unbekannt, ohne Zuverlässigkeit
        self.assertFalse(self.hat(self.pruefe(), "SPERRE QUELLE_UNBEWERTET Q2"))  # noch ohne Beleg
        self.beleg(q2, ZITAT2)
        self.assertTrue(self.hat(self.pruefe(1), "SPERRE QUELLE_UNBEWERTET Q2"))
        self.ok("quelle", "setzen", q2, "--typ", "medium")
        self.assertTrue(self.hat(self.pruefe(1), "SPERRE QUELLE_UNBEWERTET Q2"))
        self.ok("quelle", "setzen", q2, "--zuverlaessigkeit", "C")
        self.assertFalse(self.hat(self.pruefe(0), "SPERRE QUELLE_UNBEWERTET Q2"))

    def test_person_kategorie_privatperson_identitaet(self):
        p1 = self.neue_id("akteur", "neu", "--art", "person", "--name", "Max Müller")
        self.ok("behauptung", "setzen", self.a1, "--betrifft", p1)
        ergebnis = self.pruefe(1)
        self.assertTrue(self.hat(ergebnis, "SPERRE KATEGORIE P1"))
        self.assertTrue(self.hat(ergebnis, "VOR VERÖFFENTLICHUNG IDENTITAET P1"))
        self.ok("akteur", "setzen", p1, "--kategorie", "privat")
        ergebnis = self.pruefe(0)
        self.assertFalse(self.hat(ergebnis, "SPERRE KATEGORIE P1"))
        self.assertTrue(self.hat(ergebnis, "VOR VERÖFFENTLICHUNG PRIVATPERSON A1/P1"))
        self.ok("akteur", "setzen", p1, "--kennung", "geburtsjahr=1970")
        self.assertFalse(self.hat(self.pruefe(), "VOR VERÖFFENTLICHUNG IDENTITAET P1"))
        self.ok("akteur", "setzen", p1, "--kategorie", "oeffentlich")
        self.assertFalse(self.hat(self.pruefe(), "VOR VERÖFFENTLICHUNG PRIVATPERSON A1/P1"))
        self.assertEqual(self.pruefe(0).zeilen[-1], "Keine Sperren.")

    def test_gegenrecherche_hypothese_direkt(self):
        h1 = self.neue_id("hypothese", "neu", "--text", "Der Haushalt ist rechtswidrig")
        self.assertTrue(self.hat(self.pruefe(0), "HINWEIS GEGENRECHERCHE H1"))
        self.ok("hypothese", "status", h1, "gestuetzt", "--vermerk", "Belege gefunden")
        ergebnis = self.pruefe(1)
        self.assertTrue(self.hat(ergebnis, "SPERRE GEGENRECHERCHE H1"))
        self.assertFalse(self.hat(ergebnis, "HINWEIS GEGENRECHERCHE H1"))
        self.ok("suche", "notieren", "--anfrage", "Haushalt Bestätigung", "--hypothese", h1, "--richtung", "pro")
        self.assertTrue(self.hat(self.pruefe(1), "SPERRE GEGENRECHERCHE H1"))
        self.ok("suche", "notieren", "--anfrage", "Haushalt Kritik", "--hypothese", h1, "--richtung", "contra")
        ergebnis = self.pruefe(0)
        self.assertFalse(self.hat(ergebnis, "SPERRE GEGENRECHERCHE H1"))
        self.assertFalse(self.hat(ergebnis, "HINWEIS GEGENRECHERCHE H1"))

    def test_gegenrecherche_ueber_frage(self):
        h1 = self.neue_id("hypothese", "neu", "--text", "Der Haushalt ist rechtswidrig")
        f1 = self.neue_id("frage", "neu", "--text", "Gab es Kritik?", "--hypothese", h1)
        self.ok("hypothese", "status", h1, "geschwaecht", "--vermerk", "x")
        self.assertTrue(self.hat(self.pruefe(1), "SPERRE GEGENRECHERCHE H1"))
        self.ok("suche", "notieren", "--anfrage", "Kritik Haushalt", "--frage", f1, "--richtung", "contra")
        self.assertFalse(self.hat(self.pruefe(0), "SPERRE GEGENRECHERCHE H1"))

    def test_stellungnahme_vor_und_nach_antwort(self):
        o1 = self.neue_id("akteur", "neu", "--art", "organisation", "--name", "Stadtwerke AG")
        self.ok("behauptung", "setzen", self.a1, "--betrifft", o1, "--belastend")
        ergebnis = self.pruefe(0)
        self.assertTrue(self.hat(ergebnis, "VOR VERÖFFENTLICHUNG STELLUNGNAHME A1/O1"))
        k1 = self.neue_id("konfrontation", "neu", "--akteur", o1, "--frage", "Wie stehen Sie dazu?", "--zu", self.a1)
        self.assertTrue(self.hat(self.pruefe(0), "VOR VERÖFFENTLICHUNG STELLUNGNAHME A1/O1"))
        self.fehler("konfrontation", "antwort", k1, "--text", "Keine Meinung")  # noch nicht gesendet
        self.ok("konfrontation", "status", k1, "gesendet", "--am", "2026-05-10", "--frist", "2026-05-17")
        self.assertTrue(self.hat(self.pruefe(0), "VOR VERÖFFENTLICHUNG STELLUNGNAHME A1/O1"))
        self.ok("konfrontation", "antwort", k1, "--text", "Wir weisen das zurück.")
        self.assertFalse(self.hat(self.pruefe(0), "VOR VERÖFFENTLICHUNG STELLUNGNAHME A1/O1"))
        konf = self.export()["konfrontationen"][0]
        self.assertEqual((konf["status"], konf["zu"], konf["gesendet_am"]), ("beantwortet", [self.a1], "2026-05-10"))

    def test_stellungnahme_keine_antwort_und_fremde_behauptung(self):
        o1 = self.neue_id("akteur", "neu", "--art", "organisation", "--name", "Stadtwerke AG")
        self.ok("behauptung", "setzen", self.a1, "--betrifft", o1, "--belastend")
        a2 = self.behauptung("Andere Aussage", "tatsache", "--pro", self.b1)
        k1 = self.neue_id("konfrontation", "neu", "--akteur", o1, "--frage", "Frage?", "--zu", a2)
        self.ok("konfrontation", "status", k1, "gesendet", "--am", "2026-05-10")
        self.ok("konfrontation", "keine-antwort", k1, "--vermerk", "Frist verstrichen")
        self.assertTrue(self.hat(self.pruefe(), "VOR VERÖFFENTLICHUNG STELLUNGNAHME A1/O1"))
        k2 = self.neue_id("konfrontation", "neu", "--akteur", o1, "--frage", "Frage?", "--zu", self.a1)
        self.ok("konfrontation", "status", k2, "gesendet", "--am", "2026-05-10")
        self.ok("konfrontation", "keine-antwort", k2, "--vermerk", "Frist verstrichen")
        self.assertFalse(self.hat(self.pruefe(), "VOR VERÖFFENTLICHUNG STELLUNGNAHME A1/O1"))

    def test_abhaengig(self):
        q2 = self.quelle(TEXT2, "medium", "B", titel="Zweite")
        b2 = self.beleg(q2, ZITAT2)
        self.assertTrue(self.hat(self.pruefe(0), "HINWEIS ABHAENGIG A1"))
        self.ok("behauptung", "beleg", self.a1, "--pro", b2)
        self.pruefen(self.a1, "belegt")
        self.assertFalse(self.hat(self.pruefe(0), "HINWEIS ABHAENGIG A1"))
        self.ok("quelle", "setzen", q2, "--ursprung", "Zeitung")
        self.ok("quelle", "setzen", self.q1, "--ursprung", " zeitung ")
        self.pruefen(self.a1, "gestuetzt")
        self.assertTrue(self.hat(self.pruefe(0), "HINWEIS ABHAENGIG A1"))

    def test_offene_fragen(self):
        self.pruefe_kommt_und_geht(
            "HINWEIS FRAGE_OFFEN F1",
            lambda: self.neue_id("frage", "neu", "--text", "Wer entschied?"),
            lambda: self.ok("frage", "status", "F1", "beantwortet", "--ergebnis", "Der Stadtrat"), 0)
        self.neue_id("frage", "neu", "--text", "Nur ein Mensch kann das klären", "--mensch")
        self.assertFalse(self.hat(self.pruefe(0), "HINWEIS FRAGE_OFFEN F2"))

    def test_gruppierung_und_exitcode(self):
        self.ok("behauptung", "setzen", self.a1, "--belastend")
        o1 = self.neue_id("akteur", "neu", "--art", "organisation", "--name", "Stadtwerke AG")
        self.ok("behauptung", "setzen", self.a1, "--betrifft", o1)
        self.neue_id("frage", "neu", "--text", "Offen?")
        ergebnis = self.pruefe(0)  # nur veröffentlichungsrelevant und Hinweise: kein Fehlercode
        stufen = [z.split(" ")[0] for z in ergebnis.zeilen[:-1]]
        self.assertEqual(ergebnis.zeilen[-1], "Keine Sperren.")
        self.assertEqual(stufen, ["VOR", "HINWEIS", "HINWEIS"])
        self.behauptung("Ohne Beleg", "tatsache")
        ergebnis = self.pruefe(1)
        self.assertTrue(ergebnis.zeilen[0].startswith("SPERRE "))
        self.assertNotIn("Keine Sperren.", ergebnis.out)
        export = self.export()["probleme"]
        self.assertEqual([p["stufe"] for p in export][0], "sperre")
        self.assertEqual({p["stufe"] for p in export}, {"sperre", "veroeffentlichung", "hinweis"})
        self.assertEqual(set(export[0]), {"stufe", "art", "objekt", "text"})


STRING, INT, BOOL, LISTE, DICT, NULLABLE_STR, NULLABLE_INT = (
    str, int, bool, list, dict, (str, type(None)), (int, type(None)))

EXPORT_FELDER = {
    "hypothesen": {"id": STRING, "text": STRING, "prueft": LISTE, "widerlegt": LISTE, "status": STRING, "vermerk": STRING},
    "fragen": {"id": STRING, "text": STRING, "hypothese": NULLABLE_STR, "plan": STRING, "status": STRING,
               "ergebnis": STRING, "mensch": BOOL},
    "suchen": {"id": STRING, "frage": NULLABLE_STR, "hypothese": NULLABLE_STR, "anfrage": STRING, "richtung": STRING,
               "treffer": NULLABLE_INT, "notiz": STRING, "zeit": STRING, "wer": STRING},
    "quellen": {"id": STRING, "url": STRING, "titel": STRING, "herausgeber": STRING, "autor": STRING, "datum": STRING,
                "abgerufen": STRING, "sha256": STRING, "typ": STRING, "zuverlaessigkeit": STRING, "ursprung": STRING,
                "interesse": STRING, "archiv_url": STRING, "zeichen": INT, "art": STRING},
    "belege": {"id": STRING, "quelle": STRING, "zitat": STRING, "stelle": INT, "aussage": STRING, "direkt": BOOL,
               "frage": NULLABLE_STR, "wer": STRING, "zeit": STRING, "zitat_ok": BOOL},
    "behauptungen": {"id": STRING, "text": STRING, "art": STRING, "hypothese": NULLABLE_STR, "pro": LISTE,
                     "contra": LISTE, "aus": LISTE, "betrifft": LISTE, "belastend": BOOL, "zuschreibung": BOOL,
                     "status": STRING, "obergrenze": STRING, "obergrenze_grund": STRING, "vermerk": STRING,
                     "pruefer": STRING, "geprueft": NULLABLE_STR, "klaerung": STRING},
    "akteure": {"id": STRING, "art": STRING, "name": STRING, "kategorie": STRING, "kennungen": DICT,
                "notiz": STRING, "belege": LISTE},
    "beziehungen": {"id": STRING, "von": STRING, "zu": STRING, "art": STRING, "von_datum": STRING,
                    "bis_datum": STRING, "belege": LISTE},
    "ereignisse": {"id": STRING, "datum": STRING, "text": STRING, "belege": LISTE, "akteure": LISTE},
    "konfrontationen": {"id": STRING, "akteur": STRING, "frage": STRING, "zu": LISTE, "status": STRING,
                        "gesendet_am": STRING, "frist": STRING, "antwort": STRING, "antwort_quelle": NULLABLE_STR,
                        "vermerk": STRING},
    "probleme": {"stufe": STRING, "art": STRING, "objekt": STRING, "text": STRING},
}
FALL_FELDER = {"slug", "titel", "auftrag", "interesse", "zusammenfassung", "erstellt", "stand"}


class ExportTest(FallTest):
    def pruefe_format(self, daten, gefuellt):
        self.assertEqual(set(daten), {"schema", "fall"} | set(EXPORT_FELDER))
        self.assertEqual(daten["schema"], 1)
        self.assertEqual(set(daten["fall"]), FALL_FELDER)
        for wert in daten["fall"].values():
            self.assertIsInstance(wert, str)
        for bereich, felder in EXPORT_FELDER.items():
            self.assertIsInstance(daten[bereich], list, bereich)
            if gefuellt and bereich != "probleme":
                self.assertTrue(daten[bereich], "leer: " + bereich)
            for eintrag in daten[bereich]:
                self.assertEqual(set(eintrag), set(felder), bereich)
                for schluessel, typ in felder.items():
                    self.assertIsInstance(eintrag[schluessel], typ, "%s.%s=%r" % (bereich, schluessel, eintrag[schluessel]))
                    if typ is INT:
                        self.assertNotIsInstance(eintrag[schluessel], bool)

    def test_leerer_fall(self):
        self.neuer_fall()
        daten = self.export()
        self.pruefe_format(daten, gefuellt=False)
        self.assertEqual(daten["fall"]["slug"], "t")
        self.assertEqual(daten["probleme"], [])
        self.assertTrue(all(daten[b] == [] for b in EXPORT_FELDER))

    def test_gefuellter_fall(self):
        self.neuer_fall()
        h1 = self.neue_id("hypothese", "neu", "--text", "H", "--prueft", "a", "--prueft", "b", "--widerlegt", "c")
        f1 = self.neue_id("frage", "neu", "--text", "F", "--hypothese", h1, "--plan", "Plan", "--mensch")
        self.ok("suche", "notieren", "--anfrage", "S", "--frage", f1, "--hypothese", h1, "--richtung", "contra", "--treffer", "3")
        q1 = self.quelle(TEXT, "gericht", "A", titel="Urteil")
        with tempfile.TemporaryDirectory() as ordner:
            pfad = os.path.join(ordner, "akte.txt")
            with open(pfad, "w", encoding="utf-8") as f:
                f.write(TEXT2)
            q2 = self.neue_id("quelle", "datei", pfad, "--titel", "Akte", "--typ", "medium")
        self.ok("quelle", "setzen", q2, "--zuverlaessigkeit", "B", "--datum", "2026-05", "--ursprung", q1)
        b1 = self.beleg(q1, ZITAT, direkt=True)
        b2 = self.beleg(q2, ZITAT2)
        a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", b1, "--contra", b2, "--hypothese", h1)
        a2 = self.behauptung("Folge", "schlussfolgerung", "--aus", a1, "--belastend", "--zuschreibung")
        p1 = self.neue_id("akteur", "neu", "--art", "person", "--name", "Max Müller", "--kennung", "k=v", "--beleg", b1)
        o1 = self.neue_id("akteur", "neu", "--art", "organisation", "--name", "Stadtwerke")
        self.ok("behauptung", "setzen", a2, "--betrifft", "%s,%s" % (p1, o1))
        self.ok("beziehung", "neu", "--von", p1, "--zu", o1, "--art", "Geschäftsführer", "--von-datum", "2020", "--beleg", b1)
        self.ok("ereignis", "neu", "--datum", "2026-05-05", "--text", "Beschluss", "--beleg", b1, "--akteur", p1)
        k1 = self.neue_id("konfrontation", "neu", "--akteur", p1, "--frage", "Stimmt das?", "--zu", a1)
        self.ok("konfrontation", "status", k1, "gesendet", "--am", "2026-05-10")
        self.ok("konfrontation", "antwort", k1, "--text", "Ja", "--quelle", q2)
        self.ok("behauptung", "pruefen", a1, "--status", "strittig", "--vermerk", "v", "--pruefer", "Anna")
        daten = self.export()
        self.pruefe_format(daten, gefuellt=True)
        self.assertEqual(daten["hypothesen"][0]["prueft"], ["a", "b"])
        self.assertEqual(daten["quellen"][1]["art"], "datei")
        self.assertEqual(daten["quellen"][0]["art"], "text")
        self.assertEqual(daten["quellen"][1]["ursprung"], q1)
        self.assertEqual(daten["behauptungen"][0]["obergrenze"], "belegt")
        self.assertEqual(daten["behauptungen"][1]["aus"], [a1])
        self.assertEqual(daten["akteure"][0]["kennungen"], {"k": "v"})
        self.assertEqual(daten["konfrontationen"][0]["antwort_quelle"], q2)
        self.assertEqual(daten["beziehungen"][0]["bis_datum"], "")

    def test_export_in_datei_und_fall_zeigen(self):
        self.neuer_fall()
        ziel = os.path.join(self.wurzel, "export.json")
        self.ok("export", "--datei", ziel)
        with open(ziel, encoding="utf-8") as f:
            self.assertIn('"schema": 1', f.read())
        self.assertLessEqual(len(self.ok("fall", "zeigen").zeilen), 40)
        for i in range(30):
            self.ok("frage", "neu", "--text", "Frage %d" % i)
            self.ok("hypothese", "neu", "--text", "Hypothese %d" % i)
        ergebnis = self.ok("fall", "zeigen")
        self.assertLessEqual(len(ergebnis.zeilen), 40)
        self.assertIn("… und", ergebnis.out)
        self.assertIn("Probleme: Sperren 0 | vor Veröffentlichung 0 | Hinweise 60", ergebnis.out)


class LesenUndListenTest(FallTest):
    def setUp(self):
        super().setUp()
        self.neuer_fall()

    def test_hypothese_und_frage_liste(self):
        h1 = self.neue_id("hypothese", "neu", "--text", "Der Haushalt ist rechtswidrig",
                          "--prueft", "Beschluss ohne Quorum", "--prueft", "Frist verpasst", "--widerlegt", "Quorum war da")
        self.ok("hypothese", "neu", "--text", "Zweite Hypothese")
        self.ok("hypothese", "status", h1, "geschwaecht", "--vermerk", "Quorum belegt")
        self.assertEqual(self.ok("hypothese", "liste").zeilen, [
            "H1 [geschwaecht] Der Haushalt ist rechtswidrig",
            "  prüft: Beschluss ohne Quorum", "  prüft: Frist verpasst", "  widerlegt: Quorum war da",
            "  vermerk: Quorum belegt",
            "H2 [offen] Zweite Hypothese"])
        f1 = self.neue_id("frage", "neu", "--text", "Gab es ein Quorum?", "--hypothese", h1, "--plan", "Protokoll lesen")
        f2 = self.neue_id("frage", "neu", "--text", "Anruf beim Büro", "--mensch")
        self.ok("frage", "status", f1, "beantwortet", "--ergebnis", "Ja, 31 von 40")
        self.assertEqual(self.ok("frage", "liste").zeilen, [
            "F1 [beantwortet] Gab es ein Quorum?", "  hypothese: H1", "  plan: Protokoll lesen",
            "  ergebnis: Ja, 31 von 40", "F2 [offen] Anruf beim Büro (Mensch)"])
        self.assertEqual([z for z in self.ok("frage", "liste", "--status", "offen").zeilen if z.startswith("F")],
                         ["F2 [offen] Anruf beim Büro (Mensch)"])
        self.assertEqual(self.ok("frage", "liste", "--hypothese", h1).zeilen[0], "F1 [beantwortet] Gab es ein Quorum?")
        self.assertEqual(f2, "F2")

    def test_fall_zeigen_nennt_hypothesen_und_offene_fragen(self):
        self.ok("hypothese", "neu", "--text", "Lange Hypothese " + "x" * 300)
        self.ok("frage", "neu", "--text", "Offene Frage")
        f2 = self.neue_id("frage", "neu", "--text", "Laufende Frage")
        self.ok("frage", "status", f2, "in_arbeit")
        f3 = self.neue_id("frage", "neu", "--text", "Erledigte Frage")
        self.ok("frage", "status", f3, "beantwortet")
        ergebnis = self.ok("fall", "zeigen")
        zeilen = ergebnis.zeilen
        hypothese = [z for z in zeilen if z.strip().startswith("H1 [offen]")][0]
        self.assertLessEqual(len(hypothese.strip()), len("H1 [offen] ") + 160)
        self.assertIn("  F1 Offene Frage", zeilen)
        self.assertIn("  F2 Laufende Frage", zeilen)
        self.assertNotIn("Erledigte Frage", ergebnis.out)
        self.assertLessEqual(len(zeilen), 40)

    def test_stelle_in_beleg_zeigen_und_behauptung_zeigen(self):
        q1 = self.quelle("Vorspann\n\n\n" + TEXT, "medium", "B")
        b1 = self.beleg(q1, ZITAT)
        stelle = self.export()["belege"][0]["stelle"]
        self.assertEqual(stelle, len("Vorspann\n\n\n"))
        self.assertIn("Stelle: %d" % stelle, self.ok("beleg", "zeigen", b1).out)
        a1 = self.behauptung("Haushalt", "tatsache", "--pro", b1)
        self.assertIn("| Stelle %d" % stelle, self.ok("behauptung", "zeigen", a1).out)


class SichernUndLadenTest(FallTest):
    def fuelle(self):
        self.neuer_fall()
        q1 = self.quelle(TEXT, "gericht", "A", titel="Urteil")
        b1 = self.beleg(q1, ZITAT, direkt=True)
        a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", b1)
        self.ok("behauptung", "pruefen", a1, "--status", "belegt", "--vermerk", "ok", "--pruefer", "Anna")
        self.ok("hypothese", "neu", "--text", "Eine Hypothese")
        self.ok("akteur", "neu", "--art", "person", "--name", "Max Müller")
        return q1

    def ohne_stand(self):
        daten = self.export()
        daten["fall"].pop("stand")
        return daten

    def test_sichern_loeschen_laden(self):
        q1 = self.fuelle()
        with open(os.path.join(self.wurzel, "t", "dossier.md"), "w") as f:
            f.write("erzeugt")
        vorher = self.ohne_stand()
        pruefe_vorher = self.cli("pruefe")
        with tempfile.TemporaryDirectory() as ziel:
            ergebnis = self.ok("fall", "sichern", "--ziel", ziel)
            self.assertRegex(ergebnis.zeilen[0], r"^gesichert: .*t-\d{8}-\d{4}\.zip \(\d+ Dateien, \d+ KB\)$")
            archiv = ergebnis.zeilen[0].split("gesichert: ")[1].split(" (")[0]
            with zipfile.ZipFile(archiv) as z:
                namen = z.namelist()
            self.assertIn("t/fall.db", namen)
            self.assertIn("t/quellen/%s/text.txt" % q1, namen)
            self.assertIn("t/quellen/%s/roh" % q1, namen)
            self.assertFalse(any("dossier" in n or n.endswith("-wal") for n in namen))
            self.assertIn("(%d Dateien" % len(namen), ergebnis.out)
            shutil.rmtree(os.path.join(self.wurzel, "t"))
            self.assertIn("kein Fall vorhanden", self.fehler("fall", "zeigen").err)
            self.assertEqual(self.ok("fall", "laden", archiv).zeilen, ["geladen: t"])
            self.assertEqual(self.ohne_stand(), vorher)
            nachher = self.cli("pruefe")
            self.assertEqual((nachher.code, nachher.out), (pruefe_vorher.code, pruefe_vorher.out))
            self.assertTrue(self.export()["belege"][0]["zitat_ok"])
            self.assertIn("existiert bereits: t", self.fehler("fall", "laden", archiv).err)
            self.ok("hypothese", "neu", "--text", "läuft weiter")  # geladener Fall ist beschreibbar

    def test_unzulaessige_archivpfade(self):
        with tempfile.TemporaryDirectory() as ordner:
            for name in ("../x", "/abs/x", "t/../../x", "t/quellen/../../../x"):
                archiv = os.path.join(ordner, "boese.zip")
                with zipfile.ZipFile(archiv, "w") as z:
                    z.writestr("t/fall.db", b"")
                    z.writestr(name, "boom")
                ergebnis = self.fehler("fall", "laden", archiv)
                self.assertEqual(ergebnis.err.strip(), "fehler: unzulässiger Pfad im Archiv", name)
                self.assertFalse(os.path.exists(os.path.join(self.wurzel, "t")))
                self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.wurzel), "x")))
            kaputt = os.path.join(ordner, "kaputt.zip")
            with open(kaputt, "w") as f:
                f.write("kein zip")
            self.assertIn("Archiv nicht lesbar", self.fehler("fall", "laden", kaputt).err)


class ParallelTest(FallTest):
    def test_gleichzeitige_belege_haben_verschiedene_ids(self):
        self.neuer_fall()
        q1 = self.quelle(TEXT, "medium", "B")
        ids, fehler = [], []

        def arbeite(nr):
            for i in range(5):
                ergebnis = self.cli("beleg", "neu", "--quelle", q1, "--zitat", ZITAT,
                                    "--aussage", "Prozess %d Beleg %d" % (nr, i))
                if ergebnis.code == 0:
                    ids.append(ergebnis.zeilen[0])
                else:
                    fehler.append(ergebnis.err)

        threads = [threading.Thread(target=arbeite, args=(n,)) for n in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(fehler, [])
        self.assertEqual(len(ids), 10)
        self.assertEqual(len(set(ids)), 10)
        self.assertEqual(sorted(b["id"] for b in self.export()["belege"]), sorted(i.split(": ")[1] for i in ids))
        self.assertEqual({b["id"] for b in self.export()["belege"]}, {"B%d" % n for n in range(1, 11)})


if __name__ == "__main__":
    unittest.main()
