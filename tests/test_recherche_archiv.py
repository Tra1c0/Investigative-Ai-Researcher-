"""Laden gesicherter Akten: Prüfung des Status danach, Grenzen und beschädigte Archive."""

import errno
import os
import shutil
import tempfile
import zipfile
from types import SimpleNamespace
from unittest import mock

from test_recherche_basis import ArchivHilfen, FallTest

from recherche import store


class AkteLaden(ArchivHilfen, FallTest):
    def test_status_ueber_der_obergrenze_wird_beim_laden_zurueckgesetzt(self):
        archiv = self.manipulierte_akte()
        ergebnis = self.ok("fall", "laden", archiv)
        self.assertEqual(ergebnis.zeilen[0], "geladen: t")
        self.assertRegex(ergebnis.zeilen[1], r"^hinweis: Prüfung zurückgesetzt: A1 \(Status belegt liegt über der Obergrenze unbestaetigt")
        self.assertEqual(len(ergebnis.zeilen), 2)
        self.assertEqual(self.status("A1"), "ungeprueft")
        aktionen = [(a, o) for a, o, _ in self.protokoll()]
        self.assertIn(("fall laden", "t"), aktionen)
        self.assertIn(("behauptung zurueckgesetzt", "A1"), aktionen)

    def test_zulaessiger_status_bleibt_beim_laden(self):
        self.neuer_fall("t")
        qid = self.quelle("Er sagte klar und deutlich: Das ist belegt genug, wirklich. Mehr nicht.",
                          typ="amtlich", zuv="A")
        bid = self.beleg(qid, "Das ist belegt genug, wirklich.", direkt=True)
        aid = self.behauptung("Eine Tatsache", "tatsache", "--pro", bid)
        self.ok("behauptung", "pruefen", aid, "--status", "belegt", "--vermerk", "ok", "--pruefer", "p")
        archiv = self.gesichertes_archiv("t")
        shutil.rmtree(os.path.join(self.wurzel, "t"))
        self.assertEqual(self.ok("fall", "laden", archiv).zeilen, ["geladen: t"])
        self.assertEqual(self.status("A1"), "belegt")

    def test_status_nach_dem_laden_erscheint_in_pruefe_als_sperre(self):
        archiv = self.manipulierte_akte()
        self.ok("fall", "laden", archiv)
        self.setze_status("A1", "belegt")
        ergebnis = self.fehler("pruefe")
        zeile = [z for z in ergebnis.zeilen if "STATUS A1" in z][0]
        self.assertTrue(zeile.startswith("SPERRE STATUS A1: Status belegt liegt über der Obergrenze"), zeile)

    def test_unzulaessige_arten_und_unbekannte_status_in_pruefe(self):
        self.neuer_fall("t")
        qid = self.quelle("Er sagte klar und deutlich: Das ist belegt genug, wirklich. Mehr nicht.",
                          typ="amtlich", zuv="A")
        bid = self.beleg(qid, "Das ist belegt genug, wirklich.", direkt=True)
        tat = self.behauptung("Eine Tatsache", "tatsache", "--pro", bid)
        bew = self.behauptung("Eine Bewertung", "bewertung", "--aus", tat)
        for aid, status, teil in ((bew, "belegt", "Eine Bewertung hat immer den Status werturteil"),
                                  (tat, "werturteil", "werturteil gibt es nur bei Bewertungen"),
                                  (tat, "erfunden", "unbekannter Status")):
            self.setze_status(aid, status)
            probleme = [p for p in self.export()["probleme"] if p["art"] == "STATUS"]
            self.assertEqual([(p["stufe"], p["objekt"]) for p in probleme], [("sperre", aid)])
            self.assertIn(teil, probleme[0]["text"])
            self.setze_status(aid, "ungeprueft" if aid == tat else "werturteil")
        # Beim Laden werden sie alle zurückgesetzt, auch die Bewertung mit Status belegt (kein Absturz).
        self.setze_status(bew, "belegt")
        self.setze_status(tat, "werturteil")
        archiv = self.gesichertes_archiv("t")
        shutil.rmtree(os.path.join(self.wurzel, "t"))
        ergebnis = self.ok("fall", "laden", archiv)
        self.assertEqual(len([z for z in ergebnis.zeilen if z.startswith("hinweis:")]), 2)
        self.assertEqual((self.status(tat), self.status(bew)), ("ungeprueft", "werturteil"))

    def test_akte_ohne_gueltige_datenbank_hinterlaesst_nichts(self):
        ziel = os.path.join(self.wurzel, "..", "kaputt-%d.zip" % os.getpid())
        self.addCleanup(lambda: os.path.exists(ziel) and os.remove(ziel))
        with zipfile.ZipFile(ziel, "w") as z:
            z.writestr("t/fall.db", b"das ist keine Datenbank" * 20)
        ergebnis = self.fehler("fall", "laden", ziel)
        self.assertIn("beschädigt", ergebnis.err)
        self.assertEqual(os.listdir(self.wurzel), [])


class Archivgrenzen(ArchivHilfen, FallTest):
    def setUp(self):
        super().setUp()
        self.neuer_fall("t")
        self.gut = self.gesichertes_archiv("t")
        shutil.rmtree(os.path.join(self.wurzel, "t"))
        with zipfile.ZipFile(self.gut) as z:
            self.db_bytes = z.read("t/fall.db")

    def zip(self, eintraege, kompression=zipfile.ZIP_DEFLATED):
        ziel = os.path.join(tempfile.mkdtemp(), "a.zip")
        self.addCleanup(shutil.rmtree, os.path.dirname(ziel), True)
        with zipfile.ZipFile(ziel, "w", kompression) as z:
            for name, inhalt in eintraege:
                z.writestr(name, inhalt)
        return ziel

    def laden(self, archiv):
        return store.lade_fall(self.wurzel, archiv)

    def nichts_zurueck(self):
        self.assertEqual(os.listdir(self.wurzel), [])

    def test_stark_komprimiertes_archiv_wird_abgelehnt(self):
        archiv = self.zip([("t/fall.db", self.db_bytes), ("t/quellen/Q1/text.txt", b"\0" * 300000)])
        with mock.patch.object(store, "MAX_OHNE_VERHAELTNIS", 100 * 1024):
            with self.assertRaisesRegex(store.Fehler, "stark komprimiert"):
                self.laden(archiv)
        self.nichts_zurueck()
        # Unter der Schwelle ohne Verhältnisprüfung, über der Schwelle mit niedrigem Verhältnis erlaubt.
        self.assertEqual(self.laden(archiv), "t")

    def test_zu_wenig_freier_speicher(self):
        knapp = SimpleNamespace(total=100, used=90, free=10)
        with mock.patch.object(store.shutil, "disk_usage", return_value=knapp):
            with self.assertRaisesRegex(store.Fehler, "Nicht genug freier Speicher"):
                self.laden(self.gut)
        self.nichts_zurueck()
        # Die Reserve zählt: frei = Größe der Akte reicht nicht.
        with zipfile.ZipFile(self.gut) as z:
            gesamt = sum(i.file_size for i in z.infolist())
        genau = SimpleNamespace(total=1, used=0, free=gesamt)
        with mock.patch.object(store.shutil, "disk_usage", return_value=genau):
            with self.assertRaisesRegex(store.Fehler, "Reserve"):
                self.laden(self.gut)
        self.nichts_zurueck()
        weit = SimpleNamespace(total=1, used=0, free=gesamt + store.SPEICHER_RESERVE)
        with mock.patch.object(store.shutil, "disk_usage", return_value=weit):
            self.assertEqual(self.laden(self.gut), "t")

    def test_pruefsummenfehler(self):
        archiv = self.zip([("t/fall.db", self.db_bytes), ("t/quellen/Q1/text.txt", b"a" * 64)],
                          zipfile.ZIP_STORED)
        with open(archiv, "rb") as datei:
            roh = datei.read()
        stelle = roh.index(b"a" * 64)
        with open(archiv, "wb") as datei:
            datei.write(roh[:stelle + 10] + b"b" + roh[stelle + 11:])
        with self.assertRaisesRegex(store.Fehler, "beschädigt oder unvollständig"):
            self.laden(archiv)
        self.nichts_zurueck()

    def test_beschaedigter_datenstrom(self):
        zufall = os.urandom(6000)
        archiv = self.zip([("t/fall.db", self.db_bytes), ("t/quellen/Q1/roh", zufall + b"x" * 6000)])
        with open(archiv, "rb") as datei:
            roh = bytearray(datei.read())
        stelle = roh.index(zufall[:50]) if zufall[:50] in roh else len(roh) // 2
        for i in range(stelle + 100, stelle + 140):
            roh[i] ^= 0xFF
        with open(archiv, "wb") as datei:
            datei.write(bytes(roh))
        with self.assertRaisesRegex(store.Fehler, "beschädigt oder unvollständig"):
            self.laden(archiv)
        self.nichts_zurueck()

    def test_abgeschnittener_datenstrom(self):
        # Eintrag, dessen Daten kürzer sind als angegeben: EOFError beim Lesen.
        archiv = self.zip([("t/fall.db", self.db_bytes), ("t/quellen/Q1/text.txt", b"z" * 5000)], zipfile.ZIP_STORED)
        with mock.patch.object(store.shutil, "copyfileobj", side_effect=EOFError("Compressed file ended")):
            with self.assertRaisesRegex(store.Fehler, "beschädigt oder unvollständig"):
                self.laden(archiv)
        self.nichts_zurueck()

    def test_speicher_voll_beim_entpacken(self):
        voll = OSError(errno.ENOSPC, "No space left on device")
        with mock.patch.object(store.shutil, "copyfileobj", side_effect=voll):
            with self.assertRaisesRegex(store.Fehler, "Speicher .* voll"):
                self.laden(self.gut)
        self.nichts_zurueck()
