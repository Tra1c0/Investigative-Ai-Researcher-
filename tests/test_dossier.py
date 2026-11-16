"""Tests für recherche/dossier.py (lädt das Modul direkt über den Dateipfad)."""

import copy
import importlib.util
import json
import re
import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

HIER = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "dossier_unter_test", HIER.parent / "recherche" / "dossier.py")
dossier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dossier)

FIXTURE = json.loads((HIER / "daten" / "dossier_beispiel.json").read_text("utf-8"))

# ein `<`, das weder maskiert noch Beginn eines http(s)-Autolinks ist
UNMASKIERT = r"(?<!\\)<(?!https?://)"
LEER_KEYS = ["hypothesen", "fragen", "suchen", "quellen", "belege",
             "behauptungen", "akteure", "beziehungen", "ereignisse",
             "konfrontationen", "probleme"]


def fixture():
    return copy.deepcopy(FIXTURE)


def minimal():
    d = {"schema": 1, "fall": {}}
    d.update({k: [] for k in LEER_KEYS})
    return d


class Seite(HTMLParser):
    """Sammelt Tags, Attribute, IDs und Links einer HTML-Ausgabe."""

    def __init__(self, text):
        super().__init__()
        self.tags, self.ids, self.hrefs, self.attrs = [], [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        for name, wert in attrs:
            self.attrs.append((tag, name, wert))
            if name == "id":
                self.ids.append(wert)
            if name == "href":
                self.hrefs.append(wert)


class Laeuft(unittest.TestCase):
    def test_fixture_beide_formate(self):
        self.assertIn("# Beispiel GmbH", dossier.render_markdown(fixture()))
        self.assertTrue(dossier.render_html(fixture()).startswith("<!DOCTYPE html>"))

    def test_minimal_leere_listen(self):
        md = dossier.render_markdown(minimal())
        self.assertIn("Keine Kurzfassung hinterlegt.", md)
        self.assertIn("Methode und Grenzen", md)
        self.assertNotIn("Quellenverzeichnis", md)
        html_text = dossier.render_html(minimal())
        self.assertIn('lang="de"', html_text)
        self.assertNotIn("sec-hypothesen", html_text)

    def test_leere_strings_und_null_referenzen(self):
        d = fixture()
        for art in LEER_KEYS:
            for rec in d[art]:
                for k, v in list(rec.items()):
                    if isinstance(v, str):
                        rec[k] = ""
                    elif v is not None and not isinstance(v, (list, dict, bool)):
                        rec[k] = None
        d["fall"] = {k: "" for k in d["fall"]}
        d["behauptungen"][0]["hypothese"] = None
        d["behauptungen"][1]["pro"] = [None, "B99"]
        for render in (dossier.render_markdown, dossier.render_html):
            self.assertIsInstance(render(d), str)
        for render in (dossier.render_markdown, dossier.render_html):
            render({})
            render({"schema": 1})

    def test_unbekannte_enums_werden_ausgegeben(self):
        d = fixture()
        d["behauptungen"][0]["status"] = "seltsam"
        d["hypothesen"][0]["status"] = "ratlos"
        d["probleme"].append({"stufe": "wasauchimmer", "art": "x", "objekt": "", "text": "t"})
        self.assertIn("seltsam", dossier.render_markdown(d))
        self.assertIn("ratlos", dossier.render_html(d))
        self.assertIn("wasauchimmer", dossier.render_markdown(d))


class Bereitschaft(unittest.TestCase):
    def test_drei_faelle(self):
        d = fixture()
        self.assertIn("Arbeitsstand: 1 Sperre offen. Aussagen nicht belastbar.",
                      dossier.render_markdown(d))
        d["probleme"] = [p for p in d["probleme"] if p["stufe"] != "sperre"]
        self.assertIn("Recherchestand geprüft. Vor einer Veröffentlichung offen: 2 Punkte.",
                      dossier.render_markdown(d))
        self.assertIn("Recherchestand geprüft. Vor einer Veröffentlichung offen: 2 Punkte.",
                      dossier.render_html(d))
        d["probleme"] = [p for p in d["probleme"] if p["stufe"] == "hinweis"]
        md = dossier.render_markdown(d)
        self.assertIn("**Recherchestand geprüft.**", md)
        self.assertNotIn("Vor einer Veröffentlichung offen", md)

    def test_zaehlung_je_status(self):
        md = dossier.render_markdown(fixture())
        self.assertIn("Behauptungen: 8 — belegt: 2, gestützt: 1, strittig: 1, "
                      "unbestätigt: 1, ungeprüft: 1, widerlegt: 1, Werturteil: 1", md)


class Kurzfassung(unittest.TestCase):
    def test_markdown(self):
        md = dossier.render_markdown(fixture())
        self.assertIn("[A1 · belegt]", md)
        self.assertIn("Musterstadt [A1 · belegt]. Die", md)
        self.assertIn("[A2 · gestützt]", md)
        self.assertIn("[A9 · unbekannt]", md)
        self.assertIn("[A5 · strittig]", md)
        self.assertIn("Verweis auf unbekannte Behauptung: [A9]", md)
        self.assertEqual(md.count("(ohne Belegverweis)"), 1)
        self.assertIn("Dieser Absatz enthält keinen Verweis auf eine Behauptung. "
                      "(ohne Belegverweis)", md)

    def test_html(self):
        h = dossier.render_html(fixture())
        self.assertIn('<a href="#A1">[A1 · belegt]</a>', h)
        self.assertIn("[A9 · unbekannt]", h)
        self.assertNotIn('href="#A9"', h)
        self.assertEqual(h.count("(ohne Belegverweis)"), 1)

    def test_ersatz_ohne_zusammenfassung(self):
        d = fixture()
        d["fall"]["zusammenfassung"] = ""
        md = dossier.render_markdown(d)
        teil = md.split("## Kurzfassung")[1].split("\n## ")[0]
        self.assertIn("Keine Kurzfassung hinterlegt.", teil)
        zeilen = [z for z in teil.splitlines() if z.startswith("- ")]
        self.assertEqual([z[2:6] for z in zeilen], ["[A8]", "[A1]", "[A2]"])


class Reihenfolge(unittest.TestCase):
    def test_befunde_nach_status_und_gruppe(self):
        md = dossier.render_markdown(fixture())
        befunde = md.split("\n## Befunde")[1].split("\n## ")[0]
        ids = re.findall(r"^#### (A\d+) —", befunde, re.M)
        self.assertEqual(ids, ["A8", "A1", "A2", "A3", "A5", "A4", "A7", "A6"])
        self.assertLess(befunde.index("### Ohne Hypothese"), befunde.index("#### A6"))
        self.assertGreater(befunde.index("### Ohne Hypothese"), befunde.index("#### A7"))

    def test_chronologie_gemischte_genauigkeit(self):
        md = dossier.render_markdown(fixture())
        teil = md.split("\n## Chronologie")[1].split("\n## ")[0]
        self.assertEqual(re.findall(r"\[(E\d)\]", teil), ["E3", "E2", "E1", "E4"])
        h = dossier.render_html(fixture())
        teil = h.split('id="sec-chronologie"')[1].split("</section>")[0]
        self.assertEqual(re.findall(r'<li id="(E\d)"', teil), ["E3", "E2", "E1", "E4"])


class HtmlAufSchmalemBildschirm(unittest.TestCase):
    def test_quellen_als_karten_mit_anker_und_link(self):
        h = dossier.render_html(fixture())
        teil = h.split('id="sec-quellen"')[1].split("</section>")[0]
        self.assertNotIn("<table", teil)
        self.assertEqual(re.findall(r'<div class="karte" id="(Q\d+)">', teil),
                         [q["id"] for q in fixture()["quellen"]])
        adressen = [q["url"] for q in fixture()["quellen"] if q["url"].startswith("http")]
        self.assertTrue(adressen)
        for adresse in adressen:
            self.assertIn('<strong>URL:</strong> <a href="%s"' % adresse.replace("&", "&amp;"), teil)

    def test_tabellenzellen_tragen_den_spaltennamen(self):
        h = dossier.render_html(fixture())
        teil = h.split('id="sec-akteure"')[1].split("</section>")[0]
        self.assertIn('<td data-spalte="Name">', teil)
        self.assertIn("td::before{content:attr(data-spalte)", h)


class HtmlSicherheit(unittest.TestCase):
    def gift(self):
        d = fixture()
        d["fall"]["titel"] = "<script>alert(1)</script>"
        d["behauptungen"][0]["text"] = '"onmouseover="x'
        d["belege"][0]["zitat"] = "<script>alert(1)</script>"
        d["quellen"][0]["url"] = "javascript:alert(1)"
        d["quellen"][0]["archiv_url"] = "javascript:alert(1)"
        d["quellen"][1]["titel"] = '"onmouseover="x'
        d["akteure"][0]["name"] = "<img src=x onerror=alert(1)>"
        return d

    def test_nur_escaped(self):
        h = dossier.render_html(self.gift())
        self.assertNotIn("<script", h.lower())
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", h)
        self.assertNotIn('"onmouseover="x', h)
        self.assertIn("&quot;onmouseover=&quot;x", h)
        self.assertNotIn("<img", h)

    def test_javascript_url_kein_link(self):
        seite = Seite(dossier.render_html(self.gift()))
        for tag, name, wert in seite.attrs:
            self.assertFalse(wert and wert.lower().startswith("javascript"),
                             (tag, name, wert))
            self.assertFalse(name.startswith("on"), (tag, name))
        self.assertIn("javascript:alert(1)", dossier.render_html(self.gift()))

    def test_externe_links_mit_rel(self):
        h = dossier.render_html(fixture())
        links = re.findall(r'<a href="https?://[^>]*>', h)
        self.assertTrue(links)
        for link in links:
            self.assertIn('rel="noopener noreferrer"', link)

    def test_markdown_url_kein_autolink(self):
        md = dossier.render_markdown(self.gift())
        self.assertNotIn("<javascript:", md)
        self.assertNotRegex(md, UNMASKIERT)


class HtmlStruktur(unittest.TestCase):
    def setUp(self):
        self.text = dossier.render_html(fixture())
        self.seite = Seite(self.text)

    def test_dokumentgeruest(self):
        t = self.text
        self.assertIn('<html lang="de">', t)
        self.assertIn('<meta charset="utf-8">', t)
        self.assertIn('name="viewport"', t)
        self.assertIn("<title>Beispiel GmbH und der Auftrag der Stadt Musterstadt</title>", t)
        self.assertIn("prefers-color-scheme: dark", t)
        self.assertEqual(t.count("<style>"), 1)
        self.assertIn("background:var(--bg)", t)

    def test_anker_genau_einmal(self):
        zaehler = Counter(self.seite.ids)
        for objekt in ("behauptungen", "belege", "quellen"):
            for rec in FIXTURE[objekt]:
                self.assertEqual(zaehler[rec["id"]], 1, rec["id"])
        for i, n in zaehler.items():
            self.assertEqual(n, 1, i)

    def test_interne_links_haben_ziel(self):
        ids = set(self.seite.ids)
        interne = [h for h in self.seite.hrefs if h.startswith("#")]
        self.assertTrue(interne)
        for h in interne:
            self.assertIn(h[1:], ids)

    def test_unbekannte_verweise_ohne_link(self):
        d = fixture()
        d["behauptungen"][0]["pro"] = ["B99"]
        d["behauptungen"][0]["aus"] = ["A99"]
        seite = Seite(dossier.render_html(d))
        self.assertNotIn("#B99", seite.hrefs)
        self.assertNotIn("#A99", seite.hrefs)
        for h in seite.hrefs:
            if h.startswith("#"):
                self.assertIn(h[1:], seite.ids)

    def test_keine_externen_ressourcen(self):
        verboten = {"img", "link", "script", "iframe", "object", "embed",
                    "audio", "video", "source", "form", "base"}
        self.assertFalse(verboten & set(self.seite.tags))
        for tag, name, wert in self.seite.attrs:
            self.assertNotIn(name, ("src", "srcset", "style", "action"))
            if wert and wert.startswith("http"):
                self.assertEqual((tag, name), ("a", "href"))
        self.assertNotIn("url(", self.text)
        self.assertNotIn("@import", self.text)
        self.assertNotIn("<script", self.text)

    def test_inhaltsverzeichnis(self):
        for k in ("kurzfassung", "befunde", "quellen", "methode"):
            self.assertIn(f'href="#sec-{k}"', self.text)
            self.assertIn(f'id="sec-{k}"', self.text)

    def test_beleg_markierungen(self):
        t = self.text
        self.assertIn("Primärbeleg", t)
        self.assertEqual(t.count("Zitat nicht mehr im Schnappschuss</p>"), 1)
        self.assertIn("<blockquote>Zuschlag erteilt an die Beispiel GmbH.</blockquote>", t)

    def test_badge_hat_text(self):
        self.assertIn('class="badge b-belegt">belegt</span>', self.text)
        self.assertIn('class="badge b-werturteil">Werturteil</span>', self.text)

    def test_obergrenze(self):
        t = self.text
        self.assertIn("Nur eine unzuverlässige Quelle.", t)       # A3 unbestätigt < gestützt
        self.assertIn("Keine direkte Evidenz für Motiv.", t)       # A4 ungeprüft
        d = fixture()
        d["behauptungen"][1]["obergrenze"] = "belegt"             # A2 gestützt < belegt
        d["behauptungen"][1]["obergrenze_grund"] = "Grund-A2"
        d["behauptungen"][2]["obergrenze"] = "gestuetzt"          # A8 belegt, nicht darunter
        d["behauptungen"][2]["obergrenze_grund"] = "Grund-A8"
        h = dossier.render_html(d)
        self.assertIn("Grund-A2", h)
        self.assertNotIn("Grund-A8", h)


class Zuschreibung(unittest.TestCase):
    SATZ = "Zuschreibung: Belegt ist, dass die Quelle dies selbst angibt, nicht, dass es zutrifft."

    def test_markierung_und_satz(self):
        md = dossier.render_markdown(fixture())
        self.assertEqual(md.count(self.SATZ), 1)
        self.assertIn("Tatsache (Zuschreibung) · gestützt", md)
        self.assertLess(md.index(self.SATZ), md.index("#### A8"))
        self.assertIn("(gestützt (Zuschreibung))", md)  # Liste unter Hypothesen
        h = dossier.render_html(fixture())
        self.assertEqual(h.count(self.SATZ), 1)
        self.assertIn('<span class="badge b-werturteil">Zuschreibung</span>', h)

    def test_ersatzliste(self):
        d = fixture()
        d["fall"]["zusammenfassung"] = ""
        d["behauptungen"][1]["status"] = "belegt"
        self.assertIn("(belegt (Zuschreibung))", dossier.render_markdown(d))

    def test_ohne_flag_und_altdaten(self):
        d = fixture()
        for c in d["behauptungen"]:
            c.pop("zuschreibung", None)
        for render in (dossier.render_markdown, dossier.render_html):
            out = render(d)
            self.assertNotIn(self.SATZ, out)
            self.assertNotIn("Zuschreibung", out)


class MarkdownTests(unittest.TestCase):
    def setUp(self):
        self.md = dossier.render_markdown(fixture())

    def test_pipe_im_titel_bricht_tabelle_nicht(self):
        teil = self.md.split("## Quellenverzeichnis")[1]
        zeilen = [z for z in teil.splitlines() if z.startswith("|")]
        self.assertEqual(len(zeilen), 2 + len(FIXTURE["quellen"]))
        spalten = {len(re.split(r"(?<!\\)\|", z)) for z in zeilen}
        self.assertEqual(len(spalten), 1)
        self.assertIn("Kritik an Vergabe \\| Kommentar", teil)

    def test_zitat_als_blockquote(self):
        self.assertIn("\n> Zuschlag erteilt an die Beispiel GmbH.\n", self.md)
        self.assertIn("> Die Stadt habe den Auftrag ohne Ausschreibung vergeben.\n"
                      "> Das sagt der Stadtrat.", self.md)

    def test_zeilenanfaenge_maskiert(self):
        d = fixture()
        d["behauptungen"][0]["text"] = "# Titel\n> zitat\n- liste"
        d["fall"]["auftrag"] = "- auftrag"
        md = dossier.render_markdown(d)
        self.assertIn("#### A3 — \\# Titel \\> zitat - liste", md)
        self.assertIn("**Auftrag:** \\- auftrag", md)

    def test_keine_html_tags(self):
        d = fixture()
        d["behauptungen"][0]["text"] = "<b>fett</b>"
        md = dossier.render_markdown(d)
        self.assertNotRegex(md, UNMASKIERT)
        self.assertIn("\\<b\\>fett", md)

    def test_markierungen_und_felder(self):
        md = self.md
        self.assertIn("Primärbeleg", md)
        self.assertIn("**Warnung:** Zitat nicht mehr im Schnappschuss", md)
        self.assertIn("belastend", md)
        self.assertIn("Prüfer: Prüferin Muster, geprüft: 2024-05-10", md)
        self.assertIn("Klärung", md)
        self.assertIn("Erika Musterfrau ([P1])", md)
        self.assertIn("Beruht auf:** [A1]", md)
        self.assertIn("Beispiel GmbH — Auftragnehmer von → Stadt Musterstadt", md)
        self.assertIn("HRB: 000000; Sitz: Musterstadt", md)
        self.assertIn("aaaaaaaaaaaa", md)
        self.assertNotIn("aaaaaaaaaaaa1", md)

    def test_fragen_und_aufgaben(self):
        teil = self.md.split("## Fragen und Aufgaben")[1].split("\n## ")[0]
        offen = teil.split("### Sackgassen")[0]
        self.assertIn("[F1]", offen)
        self.assertIn("[F2]", offen)
        self.assertNotIn("[F3]", teil)
        sack = teil.split("### Sackgassen")[1].split("### Aufgaben")[0]
        self.assertIn("Protokoll nicht öffentlich", sack)
        self.assertIn("[F5]", teil.split("### Aufgaben für Menschen")[1])

    def test_belege_ohne_behauptung_und_konfrontation(self):
        self.assertIn("### Belege ohne Behauptung", self.md)
        teil = self.md.split("## Konfrontation")[1].split("\n## ")[0]
        for k in ("K1", "K2", "K3", "K4"):
            self.assertIn(f"### {k} —", teil)
        self.assertIn("Wir weisen die Vorwürfe zurück.", teil)

    def test_hypothesen_suchen(self):
        teil = self.md.split("## Hypothesen")[1].split("\n## ")[0]
        self.assertIn("pro: 1, contra: 1, neutral: 0", teil)
        self.assertIn("pro: 1, contra: 1, neutral: 1", teil)


class Methode(unittest.TestCase):
    def test_zahlen(self):
        md = dossier.render_markdown(fixture())
        teil = md.split("## Methode und Grenzen")[1].split("\n## ")[0]
        self.assertIn("amtlich: 1, Register: 1, Gericht: 1, Eigenangabe: 1, "
                      "Medium: 1, Blog: 1", teil)
        self.assertIn("Quellen der Art text (nicht selbst abgerufen): 1", teil)
        self.assertIn("Suchen je Richtung: pro: 2, contra: 2, neutral: 1", teil)
        self.assertIn("Belege: 9", teil)
        self.assertIn("belegt: 2 (25,0 %)", teil)
        self.assertIn("gestützt: 1 (12,5 %)", teil)
        self.assertIn(dossier.GRENZEN_SATZ, teil)
        self.assertIn(dossier.GRENZEN_SATZ.replace("ü", "ü"), dossier.render_html(fixture()))

    def test_ohne_behauptungen(self):
        teil = dossier.render_markdown(minimal())
        self.assertIn("keine Behauptungen", teil)
        self.assertIn("Belege: 0", teil)


if __name__ == "__main__":
    unittest.main()
