"""Tests für die Statusregeln: Obergrenze, Unabhängigkeit, `behauptung pruefen`."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_recherche_basis import FallTest  # noqa: E402
from recherche import bewertung  # noqa: E402


def quelle(qid, typ="medium", zuv="B", ursprung=""):
    return {"id": qid, "typ": typ, "zuverlaessigkeit": zuv, "ursprung": ursprung}


def beleg(bid, qid, direkt=False):
    return {"id": bid, "quelle": qid, "direkt": direkt}


def grenze(quellen, belege, art="tatsache", zuschreibung=False, aus=()):
    nach_id = {x["id"]: x for x in quellen}
    gruppen = bewertung.unabhaengigkeitsgruppen(quellen)
    return bewertung.obergrenze(art, zuschreibung, belege, nach_id, gruppen, list(aus))


class ObergrenzeTest(unittest.TestCase):
    def status(self, *args, **kwargs):
        return grenze(*args, **kwargs)[0]

    def test_ohne_belege(self):
        self.assertEqual(grenze([], []), ("unbestaetigt", "keine Belege"))

    def test_direktes_gericht_mit_bewertung_erlaubt_belegt(self):
        self.assertEqual(self.status([quelle("Q1", "gericht", "A")], [beleg("B1", "Q1", True)]), "belegt")

    def test_primaertypen(self):
        for typ in ("amtlich", "register", "gericht", "parlament"):
            self.assertEqual(self.status([quelle("Q1", typ, "C")], [beleg("B1", "Q1", True)]), "belegt", typ)

    def test_primaerquelle_ohne_direkt_nur_gestuetzt(self):
        self.assertEqual(self.status([quelle("Q1", "gericht", "A")], [beleg("B1", "Q1", False)]), "gestuetzt")

    def test_amtlich_ohne_bewertung_traegt_nicht_zu_belegt(self):
        quellen = [quelle("Q1", "amtlich", "")]
        self.assertEqual(self.status(quellen, [beleg("B1", "Q1", True)]), "unbestaetigt")
        quellen = [quelle("Q1", "amtlich", "D")]
        self.assertEqual(self.status(quellen, [beleg("B1", "Q1", True)]), "unbestaetigt")
        quellen = [quelle("Q1", "amtlich", "A")]
        self.assertEqual(self.status(quellen, [beleg("B1", "Q1", True)]), "belegt")

    def test_zwei_unabhaengige_b_quellen_erlauben_belegt(self):
        quellen = [quelle("Q1"), quelle("Q2")]
        self.assertEqual(self.status(quellen, [beleg("B1", "Q1"), beleg("B2", "Q2")]), "belegt")

    def test_eine_b_quelle_gestuetzt(self):
        self.assertEqual(self.status([quelle("Q1")], [beleg("B1", "Q1")]), "gestuetzt")

    def test_zwei_unabhaengige_unbewertete_bleiben_unbestaetigt(self):
        quellen = [quelle("Q1", zuv=""), quelle("Q2", zuv="E")]
        status, grund = grenze(quellen, [beleg("B1", "Q1"), beleg("B2", "Q2")])
        self.assertEqual(status, "unbestaetigt")
        self.assertIn("Quellengruppen: 2, davon mit Zuverlässigkeit A-C: 0; keine zuverlässige Quelle", grund)

    def test_eine_starke_und_eine_schwache_gruppe_gestuetzt(self):
        quellen = [quelle("Q1", zuv="B"), quelle("Q2", zuv="E")]
        self.assertEqual(self.status(quellen, [beleg("B1", "Q1"), beleg("B2", "Q2")]), "gestuetzt")

    def test_eine_unbewertete_quelle_unbestaetigt(self):
        self.assertEqual(self.status([quelle("Q1", zuv="")], [beleg("B1", "Q1")]), "unbestaetigt")

    def test_gleicher_ursprungstext_ist_eine_gruppe(self):
        quellen = [quelle("Q1", ursprung="dpa 2026-05-01"), quelle("Q2", ursprung="  DPA   2026-05-01 ")]
        status, grund = grenze(quellen, [beleg("B1", "Q1"), beleg("B2", "Q2")])
        self.assertEqual(status, "gestuetzt")
        self.assertIn("Quellengruppen: 1", grund)

    def test_ursprung_per_id_ist_transitiv(self):
        quellen = [quelle("Q1", ursprung="Q2"), quelle("Q2", ursprung="Q3"), quelle("Q3"),
                   quelle("Q4", ursprung="Q3"), quelle("Q5")]
        gruppen = bewertung.unabhaengigkeitsgruppen(quellen)
        self.assertEqual(len({gruppen[i] for i in ("Q1", "Q2", "Q3", "Q4")}), 1)
        self.assertNotEqual(gruppen["Q5"], gruppen["Q1"])
        self.assertEqual(self.status(quellen, [beleg("B1", "Q1"), beleg("B2", "Q4")]), "gestuetzt")
        self.assertEqual(self.status(quellen, [beleg("B1", "Q1"), beleg("B2", "Q5")]), "belegt")

    def test_zuschreibung(self):
        eigen_b = [quelle("Q1", "eigenangabe", "B")]
        status, grund = grenze(eigen_b, [beleg("B1", "Q1", True)], zuschreibung=True)
        self.assertEqual(status, "belegt")
        self.assertIn("Zuschreibung, von der Quelle selbst direkt belegt", grund)
        self.assertEqual(self.status(eigen_b, [beleg("B1", "Q1", True)]), "gestuetzt")
        self.assertEqual(self.status(eigen_b, [beleg("B1", "Q1", False)], zuschreibung=True), "gestuetzt")
        eigen_d = [quelle("Q1", "eigenangabe", "D")]
        self.assertEqual(self.status(eigen_d, [beleg("B1", "Q1", True)], zuschreibung=True), "unbestaetigt")

    def test_grund_nennt_primaerfall(self):
        grund = grenze([quelle("Q1", "amtlich", "A")], [beleg("B1", "Q1", True)])[1]
        self.assertIn("Primärbeleg aus amtlicher Quelle", grund)

    def test_schlussfolgerung_folgt_den_praemissen(self):
        self.assertEqual(self.status([], [], "schlussfolgerung", aus=[("A1", "belegt"), ("A2", "gestuetzt")]), "gestuetzt")
        self.assertEqual(self.status([], [], "schlussfolgerung", aus=[("A1", "belegt"), ("A2", "ungeprueft")]), "unbestaetigt")
        self.assertEqual(self.status([], [], "schlussfolgerung", aus=[("A1", "strittig")]), "unbestaetigt")
        self.assertEqual(self.status([], [], "schlussfolgerung", aus=[]), "unbestaetigt")
        # eigene Belege heben die Grenze einer Schlussfolgerung nicht an
        quellen = [quelle("Q1", "gericht", "A")]
        self.assertEqual(self.status(quellen, [beleg("B1", "Q1", True)], "schlussfolgerung",
                                     aus=[("A1", "belegt")]), "gestuetzt")

    def test_bewertung_ist_werturteil(self):
        self.assertEqual(self.status([], [], "bewertung", aus=[("A1", "belegt")]), "werturteil")


class PruefenTest(FallTest):
    TEXT_A = "Der Stadtrat hat am 5. Mai 2026 den Haushalt mit 31 zu 12 Stimmen beschlossen."
    TEXT_B = "Laut Protokoll wurde der Haushalt 2026 am Montag im Stadtrat verabschiedet."

    def setUp(self):
        super().setUp()
        self.neuer_fall()

    def zwei_b_quellen(self):
        q1 = self.quelle(self.TEXT_A, "medium", "B", titel="Zeitung A")
        q2 = self.quelle(self.TEXT_B, "medium", "B", titel="Zeitung B")
        b1 = self.beleg(q1, "Der Stadtrat hat am 5. Mai 2026 den Haushalt")
        b2 = self.beleg(q2, "der Haushalt 2026 am Montag im Stadtrat")
        return q1, q2, b1, b2

    def pruefen(self, aid, status, vermerk_klaerung=False):
        if vermerk_klaerung:
            self.ok("behauptung", "setzen", aid, "--klaerung", "Gegenbeleg erklärt")
        return self.cli("behauptung", "pruefen", aid, "--status", status, "--vermerk", "ok", "--pruefer", "Anna")

    def test_ablehnung_ueber_der_obergrenze_mit_grund(self):
        q1 = self.quelle(self.TEXT_A, "medium", "B")
        b1 = self.beleg(q1, "Der Stadtrat hat am 5. Mai 2026 den Haushalt")
        a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", b1)
        ergebnis = self.pruefen(a1, "belegt")
        self.assertEqual(ergebnis.code, 1)
        self.assertRegex(ergebnis.err, r"^fehler: Status belegt nicht zulässig\. Obergrenze: gestuetzt \(.+\)")
        self.assertEqual(self.status(a1), "ungeprueft")
        self.assertEqual(self.pruefen(a1, "gestuetzt").code, 0)
        self.assertEqual(self.status(a1), "gestuetzt")
        daten = self.export()["behauptungen"][0]
        self.assertEqual((daten["pruefer"], daten["vermerk"]), ("Anna", "ok"))
        self.assertIsNotNone(daten["geprueft"])

    def test_belegt_mit_zwei_unabhaengigen_quellen(self):
        _, _, b1, b2 = self.zwei_b_quellen()
        a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", "%s,%s" % (b1, b2))
        self.assertEqual(self.pruefen(a1, "belegt").code, 0)

    def test_amtliche_quelle_erst_nach_bewertung(self):
        q1 = self.quelle(self.TEXT_A, "amtlich", titel="Beschluss")
        b1 = self.beleg(q1, "Der Stadtrat hat am 5. Mai 2026 den Haushalt", direkt=True)
        a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", b1)
        self.assertEqual(self.pruefen(a1, "belegt").code, 1)
        self.ok("quelle", "setzen", q1, "--zuverlaessigkeit", "A")
        self.assertEqual(self.pruefen(a1, "belegt").code, 0)

    def test_zuschreibung_in_der_praxis(self):
        q1 = self.quelle("Laut Geschäftsbericht 2025 beschäftigt die Firma 120 Mitarbeitende in Hamburg.",
                         "eigenangabe", "B", titel="Geschäftsbericht")
        b1 = self.beleg(q1, "beschäftigt die Firma 120 Mitarbeitende", direkt=True)
        mit = self.behauptung("Die Firma gibt 120 Mitarbeitende an", "tatsache", "--pro", b1, "--zuschreibung")
        ohne = self.behauptung("Die Firma hat 120 Mitarbeitende", "tatsache", "--pro", b1)
        self.assertEqual(self.pruefen(mit, "belegt").code, 0)
        ergebnis = self.pruefen(ohne, "belegt")
        self.assertEqual(ergebnis.code, 1)
        self.assertIn("Obergrenze: gestuetzt", ergebnis.err)
        self.assertEqual(self.pruefen(ohne, "gestuetzt").code, 0)
        self.assertIn("Zuschreibung: ja", self.ok("behauptung", "zeigen", mit).out)
        self.assertIn("| Zuschreibung", self.ok("behauptung", "liste").out)
        self.assertTrue(self.export()["behauptungen"][0]["zuschreibung"])

    def test_zuschreibung_ohne_direkt_bleibt_gestuetzt(self):
        q1 = self.quelle("Laut Geschäftsbericht 2025 beschäftigt die Firma 120 Mitarbeitende.",
                         "eigenangabe", "B")
        b1 = self.beleg(q1, "beschäftigt die Firma 120 Mitarbeitende", direkt=False)
        a1 = self.behauptung("Die Firma gibt 120 Mitarbeitende an", "tatsache", "--pro", b1, "--zuschreibung")
        self.assertEqual(self.pruefen(a1, "belegt").code, 1)
        self.assertEqual(self.pruefen(a1, "gestuetzt").code, 0)

    def test_zuschreibung_ausschalten_setzt_zurueck(self):
        q1 = self.quelle("Laut Geschäftsbericht 2025 beschäftigt die Firma 120 Mitarbeitende.",
                         "eigenangabe", "B")
        b1 = self.beleg(q1, "beschäftigt die Firma 120 Mitarbeitende", direkt=True)
        a1 = self.behauptung("Die Firma gibt 120 Mitarbeitende an", "tatsache", "--pro", b1, "--zuschreibung")
        self.pruefen(a1, "belegt")
        ergebnis = self.ok("behauptung", "setzen", a1, "--keine-zuschreibung")
        self.assertIn("hinweis: Prüfung zurückgesetzt", ergebnis.out)
        self.assertEqual(self.status(a1), "ungeprueft")
        self.ok("behauptung", "setzen", a1, "--zuschreibung")
        self.assertEqual(self.status(a1), "ungeprueft")

    def test_widerspruch_ohne_klaerung(self):
        q1 = self.quelle(self.TEXT_A, "gericht", "A")
        q2 = self.quelle(self.TEXT_B, "medium", "C")
        b1 = self.beleg(q1, "Der Stadtrat hat am 5. Mai 2026 den Haushalt", direkt=True)
        b2 = self.beleg(q2, "der Haushalt 2026 am Montag im Stadtrat")
        a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", b1, "--contra", b2)
        ergebnis = self.pruefen(a1, "belegt")
        self.assertEqual(ergebnis.code, 1)
        self.assertIn("fehler: Widerspruch ungeklärt (%s)." % b2, ergebnis.err)
        for status in ("gestuetzt", "belegt"):
            self.assertEqual(self.pruefen(a1, status).code, 1)
        for status in ("strittig", "widerlegt", "unbestaetigt"):
            self.assertEqual(self.pruefen(a1, status).code, 0, status)
        self.ok("behauptung", "setzen", a1, "--klaerung", "Gegenbeleg betrifft anderen Haushalt")
        self.assertEqual(self.pruefen(a1, "belegt").code, 0)

    def test_weiterer_beleg_setzt_zurueck(self):
        q1, q2, b1, b2 = self.zwei_b_quellen()
        a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", b1)
        self.pruefen(a1, "gestuetzt")
        ergebnis = self.ok("behauptung", "beleg", a1, "--pro", b2)
        self.assertIn("hinweis: Prüfung zurückgesetzt", ergebnis.out)
        self.assertEqual(self.status(a1), "ungeprueft")
        daten = self.export()["behauptungen"][0]
        self.assertEqual((daten["pruefer"], daten["geprueft"]), ("", None))
        self.pruefen(a1, "belegt")
        self.ok("behauptung", "beleg", a1, "--contra", self.beleg(self.quelle("Ganz andere Quelle über den Haushalt der Stadt.", "medium", "B"),
                                                                    "Ganz andere Quelle über den Haushalt"))
        self.assertEqual(self.status(a1), "ungeprueft")

    def test_aenderung_von_text_und_art_setzt_zurueck(self):
        q1 = self.quelle(self.TEXT_A, "medium", "B")
        b1 = self.beleg(q1, "Der Stadtrat hat am 5. Mai 2026 den Haushalt")
        a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", b1)
        for aenderung in (["--text", "Haushalt knapp beschlossen"], ["--art", "verdacht"]):
            self.pruefen(a1, "gestuetzt")
            self.assertIn("Prüfung zurückgesetzt", self.ok("behauptung", "setzen", a1, *aenderung).out)
            self.assertEqual(self.status(a1), "ungeprueft")
        self.pruefen(a1, "gestuetzt")
        self.ok("behauptung", "setzen", a1, "--belastend")
        self.assertEqual(self.status(a1), "gestuetzt")

    def test_absenken_der_zuverlaessigkeit_setzt_betroffene_zurueck(self):
        q1, q2, b1, b2 = self.zwei_b_quellen()
        belegt = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", "%s,%s" % (b1, b2))
        gestuetzt = self.behauptung("Haushalt ist beschlossen", "tatsache", "--pro", b1)
        self.pruefen(belegt, "belegt")
        self.pruefen(gestuetzt, "gestuetzt")
        ergebnis = self.ok("quelle", "setzen", q2, "--zuverlaessigkeit", "E")
        self.assertIn("Prüfung zurückgesetzt: %s" % belegt, ergebnis.out)
        self.assertEqual(self.status(belegt), "ungeprueft")
        self.assertEqual(self.status(gestuetzt), "gestuetzt")
        ergebnis = self.ok("quelle", "setzen", q1, "--zuverlaessigkeit", "E")
        self.assertIn(gestuetzt, ergebnis.out)
        self.assertEqual(self.status(gestuetzt), "ungeprueft")

    def test_aenderung_des_ursprungs_setzt_zurueck(self):
        q1, q2, b1, b2 = self.zwei_b_quellen()
        a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", "%s,%s" % (b1, b2))
        self.pruefen(a1, "belegt")
        self.ok("quelle", "setzen", q2, "--ursprung", q1)
        self.assertEqual(self.status(a1), "ungeprueft")
        self.fehler("quelle", "setzen", q2, "--ursprung", "Q99")

    def test_quelle_zeigen_nennt_gruppe_und_belege(self):
        q1, q2, b1, b2 = self.zwei_b_quellen()
        q3 = self.quelle("Eine dritte, unabhängige Quelle über etwas anderes.", "medium", "C", titel="Dritte")
        self.ok("quelle", "setzen", q2, "--ursprung", q1, "--herausgeber", "Verlag")
        ergebnis = self.ok("quelle", "zeigen", q1)
        felder = dict(z.split(": ", 1) for z in ergebnis.zeilen)
        self.assertEqual(list(felder), ["id", "titel", "url", "herausgeber", "autor", "datum", "abgerufen", "typ",
                                        "zuverlaessigkeit", "ursprung", "interesse", "archiv", "art", "zeichen",
                                        "sha256", "gruppe", "belege"])
        self.assertEqual((felder["titel"], felder["typ"], felder["zuverlaessigkeit"]), ("Zeitung A", "medium", "B"))
        self.assertEqual((felder["url"], felder["autor"], felder["ursprung"]), ("-", "-", "-"))
        self.assertEqual((felder["gruppe"], felder["belege"]), ("%s, %s" % (q1, q2), b1))
        self.assertEqual(self.ok("quelle", "zeigen", q2).zeilen[3], "herausgeber: Verlag")
        self.assertEqual(dict(z.split(": ", 1) for z in self.ok("quelle", "zeigen", q3).zeilen)["gruppe"], q3)
        self.fehler("quelle", "zeigen", "B1")

    def test_beleg_loesen_mit_ohne(self):
        q1, q2, b1, b2 = self.zwei_b_quellen()
        b3 = self.beleg(self.quelle("Ganz andere Quelle über den Haushalt der Stadt.", "medium", "B"),
                        "Ganz andere Quelle über den Haushalt")
        a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", "%s,%s" % (b1, b2), "--contra", b3)
        self.pruefen(a1, "belegt", vermerk_klaerung=True)
        ergebnis = self.cli("behauptung", "beleg", a1, "--ohne", "B1,B3")
        self.assertEqual(ergebnis.code, 0, ergebnis.err)
        self.assertIn("hinweis: Prüfung zurückgesetzt", ergebnis.out)
        self.assertEqual(self.status(a1), "ungeprueft")
        daten = self.export()["behauptungen"][0]
        self.assertEqual((daten["pro"], daten["contra"]), ([b2], []))
        self.assertEqual(len(self.export()["belege"]), 3)  # die Belege selbst bleiben
        self.assertIn("verwendet in: -", self.ok("beleg", "zeigen", b1).out)
        fehler = self.fehler("behauptung", "beleg", a1, "--ohne", b1)
        self.assertEqual(fehler.err.strip(), "fehler: %s ist nicht mit %s verknüpft" % (b1, a1))
        self.assertIn("unbekannt: B9", self.fehler("behauptung", "beleg", a1, "--ohne", "B9").err)
        self.fehler("behauptung", "beleg", a1, code=2)
        # erst lösen, dann hinzufügen in einem Aufruf
        self.ok("behauptung", "beleg", a1, "--ohne", b2, "--pro", b1)
        self.assertEqual(self.export()["behauptungen"][0]["pro"], [b1])

    def test_beleg_setzen_nicht_direkt_setzt_zurueck(self):
        q1 = self.quelle(self.TEXT_A, "gericht", "A", titel="Urteil")
        b1 = self.beleg(q1, "Der Stadtrat hat am 5. Mai 2026 den Haushalt", direkt=True)
        a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", b1)
        a2 = self.behauptung("Also gilt der Haushalt", "schlussfolgerung", "--aus", a1)
        self.pruefen(a1, "belegt")
        self.pruefen(a2, "gestuetzt")
        zitat_vorher = self.export()["belege"][0]["zitat"]
        ergebnis = self.ok("beleg", "setzen", b1, "--nicht-direkt")
        self.assertIn("hinweis: Prüfung zurückgesetzt: %s (Beleg %s geändert)" % (a1, b1), ergebnis.out)
        self.assertEqual(self.status(a1), "ungeprueft")
        self.assertEqual(self.status(a2), "ungeprueft")  # Prämisse fiel weg
        beleg = self.export()["belege"][0]
        self.assertFalse(beleg["direkt"])
        self.assertEqual(beleg["zitat"], zitat_vorher)
        self.assertEqual(self.pruefen(a1, "belegt").code, 1)
        self.ok("beleg", "setzen", b1, "--direkt")
        self.assertEqual(self.pruefen(a1, "belegt").code, 0)

    def test_beleg_setzen_aussage_setzt_nutzer_zurueck_und_zitat_ist_unveraenderlich(self):
        q1 = self.quelle(self.TEXT_A, "medium", "B")
        b1 = self.beleg(q1, "Der Stadtrat hat am 5. Mai 2026 den Haushalt")
        a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", b1)
        a2 = self.behauptung("Unverbunden", "tatsache", "--pro", self.beleg(self.quelle("Eine andere Quelle zum Thema Haushalt.", "medium", "B"),
                                                                              "Eine andere Quelle zum Thema"))
        self.pruefen(a1, "gestuetzt")
        self.pruefen(a2, "gestuetzt")
        ergebnis = self.ok("beleg", "setzen", b1, "--aussage", "Neue Aussage")
        self.assertIn(a1, ergebnis.out)
        self.assertEqual((self.status(a1), self.status(a2)), ("ungeprueft", "gestuetzt"))
        self.pruefen(a1, "gestuetzt")
        self.assertNotIn("zurückgesetzt", self.ok("beleg", "setzen", b1, "--aussage", "Neue Aussage").out)  # keine Änderung
        self.assertEqual(self.status(a1), "gestuetzt")
        zitat = self.export()["belege"][0]["zitat"]
        for optionen in (["--zitat", "Etwas völlig anderes als zuvor"], ["--zitat", "-"], ["--stelle", "3"]):
            self.fehler("beleg", "setzen", b1, *optionen, code=2)
        self.fehler("beleg", "setzen", b1, code=2)
        self.assertEqual(self.export()["belege"][0]["zitat"], zitat)
        self.assertIn("unbekannt: B9", self.fehler("beleg", "setzen", "B9", "--direkt").err)

    def test_schlussfolgerung_und_bewertung(self):
        q1 = self.quelle(self.TEXT_A, "medium", "B")
        b1 = self.beleg(q1, "Der Stadtrat hat am 5. Mai 2026 den Haushalt")
        a1 = self.behauptung("Haushalt beschlossen", "tatsache", "--pro", b1)
        self.fehler("behauptung", "neu", "--text", "Folge", "--art", "schlussfolgerung")
        a2 = self.behauptung("Also gilt der Haushalt", "schlussfolgerung", "--aus", a1)
        ergebnis = self.pruefen(a2, "gestuetzt")
        self.assertEqual(ergebnis.code, 1)
        self.assertIn("Obergrenze: unbestaetigt", ergebnis.err)
        self.pruefen(a1, "gestuetzt")
        self.assertEqual(self.pruefen(a2, "gestuetzt").code, 0)
        self.assertEqual(self.pruefen(a2, "belegt").code, 1)
        # fällt die Prämisse, fällt die Schlussfolgerung
        self.pruefen(a1, "widerlegt")
        self.assertEqual(self.status(a2), "ungeprueft")
        a3 = self.behauptung("Das ist unfair", "bewertung", "--aus", a1)
        self.assertEqual(self.status(a3), "werturteil")
        self.assertEqual(self.pruefen(a3, "gestuetzt").code, 1)


if __name__ == "__main__":
    unittest.main()


class BetroffeneFehlenTest(FallTest):
    def test_belastend_ohne_betroffene_wird_gemeldet(self):
        self.neuer_fall()
        q1 = self.quelle("Die Firma hat Auflagen nachweislich missachtet, sagt die Behörde.",
                         typ="amtlich", zuv="A")
        b1 = self.beleg(q1, "Die Firma hat Auflagen nachweislich missachtet", direkt=True)
        a1 = self.behauptung("Die Firma hat Auflagen missachtet.", "tatsache", "--pro", b1, "--belastend")
        self.assertIn("VOR VERÖFFENTLICHUNG BETROFFENE %s" % a1, self.cli("pruefe").out)
        o1 = self.neue_id("akteur", "neu", "--art", "organisation", "--name", "Firma")
        self.ok("behauptung", "setzen", a1, "--betrifft", o1)
        aus = self.cli("pruefe").out
        self.assertNotIn("BETROFFENE", aus)
        self.assertIn("STELLUNGNAHME %s/%s" % (a1, o1), aus)
