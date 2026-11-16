"""Laden gesicherter Akten: Prüfung des Status danach, Grenzen und beschädigte Archive."""

import errno
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from types import SimpleNamespace
from unittest import mock

from test_recherche_basis import ArchivHilfen, FallTest

from recherche import bewertung, store


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
        self.assertIn("keine lesbare Datenbank", ergebnis.err)
        self.assertEqual(os.listdir(self.wurzel), [])

    def test_fehler_beim_pruefen_nach_dem_laden_hinterlaesst_nichts(self):
        # Richtiger Aufbau, aber die Prüfung scheitert an den Daten: Die schon abgelegte Akte verschwindet wieder.
        self.neuer_fall("t")
        archiv = self.gesichertes_archiv("t")
        shutil.rmtree(os.path.join(self.wurzel, "t"))
        with mock.patch.object(bewertung, "_nachziehen", side_effect=sqlite3.DatabaseError("kaputte Seite")):
            with self.assertRaisesRegex(store.Fehler, "beschädigt oder unvollständig"):
                bewertung.lade_akte(self.wurzel, archiv, "tester", "Test")
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


class FremderAufbau(ArchivHilfen, FallTest):
    """Die Datenbank einer geladenen Akte darf nur die Tabellen des Werkzeugs enthalten."""

    def archiv_mit(self, *anweisungen):
        self.neuer_fall("t")
        db = sqlite3.connect(os.path.join(self.wurzel, "t", "fall.db"))
        with db:
            for anweisung in anweisungen:
                db.execute(anweisung)
        db.close()
        archiv = self.gesichertes_archiv("t")
        shutil.rmtree(os.path.join(self.wurzel, "t"))
        return archiv

    def abgelehnt(self, archiv, teil):
        ergebnis = self.fehler("fall", "laden", archiv)
        self.assertIn(teil, ergebnis.err)
        self.assertIn("nichts wurde geladen", ergebnis.err)
        self.assertEqual(os.listdir(self.wurzel), [])

    def test_ausloeser_der_einen_zurueckgesetzten_status_wiederherstellt(self):
        self.abgelehnt(self.archiv_mit(
            "CREATE TRIGGER zurueck AFTER UPDATE ON behauptung WHEN NEW.status = 'ungeprueft' "
            "BEGIN UPDATE behauptung SET status = 'belegt' WHERE id = NEW.id; END"),
            "fremden Aufbau (trigger zurueck)")

    def test_ansicht(self):
        self.abgelehnt(self.archiv_mit("CREATE VIEW sicht AS SELECT * FROM quelle"),
                       "fremden Aufbau (view sicht)")

    def test_zusaetzliche_tabelle(self):
        self.abgelehnt(self.archiv_mit("CREATE TABLE extra (x TEXT)"), "fremden Aufbau (table extra)")

    def test_eigener_index(self):
        self.abgelehnt(self.archiv_mit("CREATE INDEX nach_status ON behauptung (status)"),
                       "fremden Aufbau (index nach_status)")

    def test_geaenderte_tabelle(self):
        self.abgelehnt(self.archiv_mit("ALTER TABLE behauptung ADD COLUMN zusatz TEXT"),
                       "fremden Aufbau (table behauptung)")

    def test_fehlende_tabelle(self):
        self.abgelehnt(self.archiv_mit("DROP TABLE ereignis"), "fehlen Tabellen (ereignis)")


class Fallliste(FallTest):
    def test_nur_verzeichnisse_in_slug_form_sind_faelle(self):
        self.neuer_fall("t")
        for name in (".loeschen-0a1b", "Gross", "mit leer"):
            os.mkdir(os.path.join(self.wurzel, name))
            shutil.copy(os.path.join(self.wurzel, "t", "fall.db"), os.path.join(self.wurzel, name, "fall.db"))
        self.assertEqual(store.faelle_liste(self.wurzel), ["t"])


class FeindlicheAkte(ArchivHilfen, FallTest):
    """Zustände, die kein Befehl herstellen kann, ein präpariertes Archiv aber schon."""

    TEXT = "Er sagte klar und deutlich: Das ist belegt genug, wirklich. Mehr nicht."
    ZITAT = "Das ist belegt genug, wirklich."

    def grundfall(self):
        self.neuer_fall("t")
        qid = self.quelle(self.TEXT, typ="amtlich", zuv="A")
        bid = self.beleg(qid, self.ZITAT, direkt=True)
        aid = self.behauptung("Eine Tatsache", "tatsache", "--pro", bid)
        self.ok("behauptung", "pruefen", aid, "--status", "belegt", "--vermerk", "ok", "--pruefer", "p")
        return qid, bid, aid

    def sql(self, *anweisungen):
        db = sqlite3.connect(os.path.join(self.wurzel, "t", "fall.db"))
        with db:
            for anweisung in anweisungen:
                db.execute(anweisung)
        db.close()

    def archiv_und_weg(self):
        archiv = self.gesichertes_archiv("t")
        shutil.rmtree(os.path.join(self.wurzel, "t"))
        return archiv

    def abgelehnt(self, archiv, teil):
        ergebnis = self.fehler("fall", "laden", archiv)
        self.assertIn(teil, ergebnis.err)
        self.assertIn("nichts wurde geladen", ergebnis.err)
        self.assertEqual(os.listdir(self.wurzel), [])

    def test_ids_die_sich_nur_in_der_schreibung_unterscheiden(self):
        # `hole` schreibt IDs groß: Das Zurücksetzen von a1 traf A1, a1 blieb belegt, ohne Ende.
        self.grundfall()
        self.sql("INSERT INTO behauptung (id, text, art, status) VALUES ('a1', 'Zweite', 'tatsache', 'belegt')")
        self.abgelehnt(self.archiv_und_weg(), "unzulässige ID in behauptung")

    def test_zuruecksetzen_endet_auch_bei_widerspruechlichen_daten(self):
        self.grundfall()
        self.sql("UPDATE behauptung SET status = 'ungeprueft', pruefer = '', geprueft = NULL WHERE id = 'A1'",
                 "INSERT INTO behauptung (id, text, art, status) VALUES ('a1', 'Zweite', 'tatsache', 'belegt')")
        fall = store.Fall.oeffnen(self.wurzel, "t", "tester")
        self.addCleanup(fall.conn.close)
        with self.assertRaisesRegex(store.Fehler, "bleibt nach dem Zurücksetzen unzulässig"):
            with fall.schreiben():
                bewertung._nachziehen(fall, streng=True)

    def test_verweis_der_kein_objekt_meint(self):
        # Aus der Quellen-ID wird ein Verzeichnisname.
        self.grundfall()
        self.sql("UPDATE beleg SET quelle = '../../anderswo'")
        self.abgelehnt(self.archiv_und_weg(), "unzulässiger Verweis in beleg.quelle")

    def test_zaehler_unter_der_hoechsten_id(self):
        self.grundfall()
        self.sql("UPDATE zaehler SET n = 0 WHERE praefix = 'A'")
        self.abgelehnt(self.archiv_und_weg(), "Zähler für A")

    def test_unlesbare_liste(self):
        self.grundfall()
        self.ok("hypothese", "neu", "--text", "Eine Hypothese", "--prueft", "a", "--widerlegt", "b")
        self.sql("UPDATE hypothese SET prueft = '{\"kein\": \"Liste\"}'")
        self.abgelehnt(self.archiv_und_weg(), "Liste oder Zuordnung in hypothese")

    def test_kurzname_in_der_akte_passt_nicht(self):
        self.grundfall()
        self.sql("UPDATE meta SET wert = 'anders' WHERE schluessel = 'slug'")
        self.abgelehnt(self.archiv_und_weg(), "Kurzname in der Akte passt nicht")

    def test_wert_vom_falschen_typ_trotz_richtigem_schematext(self):
        # Die Prüfung des Schemas sieht nur den Text in sqlite_master, nicht die gespeicherten Werte.
        self.grundfall()
        pfad = os.path.join(self.wurzel, "t", "fall.db")
        try:
            db = sqlite3.connect(pfad)
            original = db.execute("SELECT sql FROM sqlite_master WHERE name = 'quelle'").fetchone()[0]
            self.assertIn("ursprung TEXT NOT NULL", original)
            db.execute("PRAGMA writable_schema = ON")
            db.execute("UPDATE sqlite_master SET sql = ? WHERE name = 'quelle'",
                       (original.replace("ursprung TEXT NOT NULL", "ursprung NOT NULL"),))
            db.commit()
            db.close()
            db = sqlite3.connect(pfad)
            db.execute("UPDATE quelle SET ursprung = 42")
            db.commit()
            db.execute("PRAGMA writable_schema = ON")
            db.execute("UPDATE sqlite_master SET sql = ? WHERE name = 'quelle'", (original,))
            db.commit()
            db.close()
            db = sqlite3.connect(pfad)
            typ = db.execute("SELECT typeof(ursprung) FROM quelle").fetchone()[0]
            db.close()
        except sqlite3.Error as fehler:
            self.skipTest("Diese SQLite-Fassung lässt das Umschreiben des Schemas nicht zu: %s" % fehler)
        if typ != "integer":
            self.skipTest("Der Wert wurde nicht als Zahl gespeichert")
        self.abgelehnt(self.archiv_und_weg(), "Werte vom falschen Typ")

    def test_schlussfolgerungen_im_kreis_stuetzen_sich_nicht(self):
        _qid, _bid, a1 = self.grundfall()
        a2 = self.behauptung("Folgerung eins", "schlussfolgerung", "--aus", a1)
        a3 = self.behauptung("Folgerung zwei", "schlussfolgerung", "--aus", a2)
        self.sql("DELETE FROM verknuepfung WHERE art = 'aus' AND von = '%s'" % a2,
                 "INSERT INTO verknuepfung (art, von, zu) VALUES ('aus', '%s', '%s')" % (a2, a3),
                 "UPDATE behauptung SET status = 'gestuetzt', pruefer = 'x', geprueft = '2026-01-01T00:00:00Z' "
                 "WHERE id IN ('%s', '%s')" % (a2, a3))
        probleme = [p for p in self.export()["probleme"] if p["art"] == "STATUS"]
        self.assertEqual(sorted(p["objekt"] for p in probleme), [a2, a3])
        self.assertIn("im Kreis", probleme[0]["text"])
        self.ok("fall", "laden", self.archiv_und_weg())
        self.assertEqual((self.status(a1), self.status(a2), self.status(a3)), ("belegt", "ungeprueft", "ungeprueft"))

    def test_beleg_dessen_zitat_nicht_im_text_steht_traegt_nichts(self):
        qid, bid, aid = self.grundfall()
        with open(os.path.join(self.wurzel, "t", "quellen", qid, "text.txt"), "w", encoding="utf-8") as datei:
            datei.write("Hier steht etwas ganz anderes, und zwar ausführlich genug.")
        daten = self.export()
        behauptung = [a for a in daten["behauptungen"] if a["id"] == aid][0]
        self.assertEqual(behauptung["obergrenze"], "unbestaetigt")
        self.assertIn("nicht gezählt, weil das Zitat nicht im gespeicherten Text steht: " + bid,
                      behauptung["obergrenze_grund"])
        sperren = {p["art"]: p["objekt"] for p in daten["probleme"] if p["stufe"] == "sperre"}
        self.assertEqual((sperren.get("ZITAT"), sperren.get("STATUS")), (bid, aid))
        self.fehler("behauptung", "pruefen", aid, "--status", "belegt", "--vermerk", "x", "--pruefer", "p")
        ergebnis = self.ok("fall", "laden", self.archiv_und_weg())
        self.assertIn("hinweis: Prüfung zurückgesetzt: %s (Status belegt liegt über der Obergrenze" % aid, ergebnis.out)
        self.assertEqual(self.status(aid), "ungeprueft")

    def test_ungeklaerter_gegenbeleg_laesst_belegt_nicht_stehen(self):
        qid, _bid, aid = self.grundfall()
        gegen = self.beleg(qid, "Er sagte klar und deutlich")
        self.sql("INSERT INTO verknuepfung (art, von, zu) VALUES ('contra', '%s', '%s')" % (aid, gegen))
        ergebnis = self.ok("fall", "laden", self.archiv_und_weg())
        self.assertIn("hinweis: Prüfung zurückgesetzt: %s (Status belegt trotz ungeklärtem Gegenbeleg (%s))"
                      % (aid, gegen), ergebnis.out)
        self.assertEqual(self.status(aid), "ungeprueft")


class Arbeitsverzeichnisse(FallTest):
    def test_alte_reste_werden_entfernt_frische_bleiben(self):
        self.neuer_fall("t")
        vor_zwei_stunden = time.time() - 7200
        for name, alt in ((".laden-alt", True), (".loeschen-alt", True), (".upload-frisch", False), (".anderes", True)):
            pfad = os.path.join(self.wurzel, name)
            os.makedirs(os.path.join(pfad, "t"))
            if alt:
                os.utime(pfad, (vor_zwei_stunden, vor_zwei_stunden))
        store.raeume_arbeitsverzeichnisse(self.wurzel)
        self.assertEqual(sorted(os.listdir(self.wurzel)), [".anderes", ".upload-frisch", "t"])
