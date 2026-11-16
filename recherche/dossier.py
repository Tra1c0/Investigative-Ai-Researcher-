"""Dossier: die lesbare Darstellung einer Fallakte (Markdown und HTML).

Reine Funktionen des Exportformats (Schema 1). Nichts wird erzeugt, was nicht
in den Daten steht. Alle Werte stammen aus untrusted Quellen: Markdown-Werte
werden maskiert, HTML-Werte mit html.escape (quote=True); aus Daten entsteht
nie aktiver Inhalt (nur http(s)-URLs werden zu Links, keine Skripte).

Aufbau: `_Ansicht` bereitet die Daten einmal auf (ID-Auflösung, Gruppierung,
Sortierung, Zählungen). `render_markdown` und `render_html` formatieren nur.
"""

import html
import re
from types import SimpleNamespace

__all__ = ["render_markdown", "render_html"]

# --- Beschriftungen und Reihenfolgen ---------------------------------------

STATUS_LABEL = {
    "belegt": "belegt", "gestuetzt": "gestützt", "unbestaetigt": "unbestätigt",
    "strittig": "strittig", "widerlegt": "widerlegt", "ungeprueft": "ungeprüft",
    "werturteil": "Werturteil", "geschwaecht": "geschwächt", "offen": "offen",
    "in_arbeit": "in Arbeit", "beantwortet": "beantwortet",
    "sackgasse": "Sackgasse", "entwurf": "Entwurf", "gesendet": "gesendet",
    "keine_antwort": "keine Antwort",
}
STUFE_LABEL = {"sperre": "Sperre", "veroeffentlichung": "vor Veröffentlichung",
               "hinweis": "Hinweis"}
ZUVERL_LABEL = {
    "A": "zuverlässig", "B": "meist zuverlässig", "C": "ziemlich zuverlässig",
    "D": "meist nicht zuverlässig", "E": "unzuverlässig",
    "F": "nicht beurteilbar", "": "nicht bewertet",
}
# Reihenfolge der Behauptungen innerhalb einer Gruppe (einzige Stelle).
BEFUND_REIHENFOLGE = ["belegt", "gestuetzt", "strittig", "unbestaetigt",
                      "ungeprueft", "widerlegt", "werturteil"]
STUFEN = ["sperre", "veroeffentlichung", "hinweis"]
RICHTUNGEN = ["pro", "contra", "neutral"]
QUELLENTYPEN = ["amtlich", "register", "gericht", "parlament", "eigenangabe",
                "agentur", "medium", "wissenschaft", "ngo", "datenbank",
                "social", "blog", "archiv", "sonstiges", "unbekannt"]
# Stärke nur für Status, die auf einer Skala liegen (für die Obergrenze).
STAERKE = {"ungeprueft": 1, "unbestaetigt": 2, "gestuetzt": 3, "belegt": 4}
# Farbklasse je Status; Unbekanntes wird neutral.
BADGE_KLASSE = {
    "belegt": "belegt", "gestuetzt": "gestuetzt", "unbestaetigt": "unbestaetigt",
    "strittig": "strittig", "widerlegt": "widerlegt", "ungeprueft": "ungeprueft",
    "werturteil": "werturteil", "geschwaecht": "unbestaetigt",
    "offen": "ungeprueft", "in_arbeit": "unbestaetigt",
    "beantwortet": "gestuetzt", "sackgasse": "werturteil",
    "entwurf": "ungeprueft", "gesendet": "unbestaetigt",
    "keine_antwort": "strittig",
}
ABSCHNITT_TITEL = {
    "kurzfassung": "Kurzfassung", "offen": "Offene Punkte",
    "hypothesen": "Hypothesen", "befunde": "Befunde",
    "chronologie": "Chronologie", "akteure": "Akteure und Beziehungen",
    "fragen": "Fragen und Aufgaben", "konfrontation": "Konfrontation",
    "methode": "Methode und Grenzen", "quellen": "Quellenverzeichnis",
}
GRENZEN_SATZ = ("Dieses Dossier enthält nur, was in der Fallakte mit "
                "wörtlichem Zitat belegt ist. Es ersetzt keine Gespräche mit "
                "Beteiligten, keine Akteneinsicht und keine rechtliche Prüfung.")


# Anzeigenamen für Arten, Quellentypen und Kategorien (Rohwerte bleiben in den Daten).
BEGRIFF_LABEL = {
    "tatsache": "Tatsache", "verdacht": "Verdacht",
    "schlussfolgerung": "Schlussfolgerung", "bewertung": "Bewertung",
    "person": "Person", "organisation": "Organisation",
    "amtstraeger": "Amts- oder Mandatsträger", "oeffentlich": "öffentliche Person",
    "funktion": "Funktionsträger", "privat": "Privatperson",
    "register": "Register", "gericht": "Gericht", "parlament": "Parlament",
    "eigenangabe": "Eigenangabe", "agentur": "Agentur", "medium": "Medium",
    "wissenschaft": "Wissenschaft", "ngo": "NGO", "datenbank": "Datenbank",
    "social": "soziale Medien", "blog": "Blog", "archiv": "Archiv",
    "sonstiges": "Sonstiges",
}


def label(wert):
    return STATUS_LABEL.get(wert) or BEGRIFF_LABEL.get(wert, wert)


# --- Normalisierung der Eingabe --------------------------------------------

# je Objektart: Textfelder, Listenfelder, Wahrheitsfelder, Zahlenfelder
_SCHEMA = {
    "hypothesen": ("id text status vermerk", "prueft widerlegt", "", ""),
    "fragen": ("id text hypothese plan status ergebnis", "", "mensch", ""),
    "suchen": ("id frage hypothese anfrage richtung notiz zeit wer", "", "",
               "treffer"),
    "quellen": ("id url titel herausgeber autor datum abgerufen sha256 typ "
                "zuverlaessigkeit ursprung interesse archiv_url art", "", "",
                "zeichen"),
    "belege": ("id quelle zitat aussage frage wer zeit", "",
               "direkt zitat_ok", "stelle"),
    "behauptungen": ("id text art hypothese status obergrenze "
                     "obergrenze_grund vermerk pruefer geprueft klaerung",
                     "pro contra aus betrifft", "belastend zuschreibung", ""),
    "akteure": ("id art name kategorie notiz", "belege", "", ""),
    "beziehungen": ("id von zu art von_datum bis_datum", "belege", "", ""),
    "ereignisse": ("id datum text", "belege akteure", "", ""),
    "konfrontationen": ("id akteur frage status gesendet_am frist antwort "
                        "antwort_quelle vermerk", "zu", "", ""),
    "probleme": ("stufe art objekt text", "", "", ""),
}
_BOOL_STANDARD = {"zitat_ok": True}


def _s(wert):
    return "" if wert is None else str(wert)


def _liste(wert):
    return [x for x in wert if isinstance(x, dict)] if isinstance(wert, list) else []


def _ids(wert):
    if not isinstance(wert, list):
        return []
    return [_s(x) for x in wert if x is not None and _s(x) != ""]


def _zahl(wert):
    return wert if isinstance(wert, int) and not isinstance(wert, bool) else None


def _norm(rec, objektart):
    texte, listen, bools, zahlen = (f.split() for f in _SCHEMA[objektart])
    werte = {k: _s(rec.get(k)) for k in texte}
    werte.update({k: _ids(rec.get(k)) for k in listen})
    werte.update({k: (rec.get(k) is not False) if k in _BOOL_STANDARD
                  else bool(rec.get(k)) for k in bools})
    werte.update({k: _zahl(rec.get(k)) for k in zahlen})
    if objektart == "akteure":
        kennungen = rec.get("kennungen")
        werte["kennungen"] = ({_s(k): _s(v) for k, v in kennungen.items()}
                              if isinstance(kennungen, dict) else {})
    return SimpleNamespace(**werte)


def _zaehle(werte, reihenfolge, mit_null=False):
    """[(wert, anzahl)] in der Reihenfolge; Unbekanntes am Ende."""
    zaehler = {}
    for w in werte:
        zaehler[w] = zaehler.get(w, 0) + 1
    paare = [(w, zaehler.get(w, 0)) for w in reihenfolge
             if mit_null or w in zaehler]
    return paare + [(w, n) for w, n in zaehler.items() if w not in reihenfolge]


def _zaehlung_text(paare):
    return ", ".join(f"{label(w) or 'ohne Angabe'}: {n}" for w, n in paare)


def _anteil(n, gesamt):
    return f"{n} ({100 * n / gesamt:.1f} %)".replace(".", ",") if gesamt else f"{n}"


def zeitraum(von, bis):
    if von and bis:
        return f"{von} – {bis}"
    if von:
        return f"seit {von}"
    return f"bis {bis}" if bis else ""


ZUSCHREIBUNG_SATZ = ("Zuschreibung: Belegt ist, dass die Quelle dies selbst "
                     "angibt, nicht, dass es zutrifft.")


def status_text(c):
    """Statusbezeichnung für Listen; Zuschreibungen werden gekennzeichnet."""
    return (label(c.status) or "ohne Status") + (
        " (Zuschreibung)" if c.zuschreibung else "")


def zeige_obergrenze(c):
    """Obergrenze zeigen, wenn ungeprüft oder der Status darunter liegt."""
    if not c.obergrenze:
        return False
    if c.status == "ungeprueft":
        return True
    status, grenze = STAERKE.get(c.status), STAERKE.get(c.obergrenze)
    return status is not None and grenze is not None and status < grenze


_VERWEIS = re.compile(r"\[(A\d+)\]")


# --- Gemeinsame Datenaufbereitung ------------------------------------------

class _Ansicht:
    """Löst IDs auf und berechnet alle Gruppierungen, einmal für beide Formate."""

    def __init__(self, daten):
        daten = daten if isinstance(daten, dict) else {}
        fall = daten.get("fall") if isinstance(daten.get("fall"), dict) else {}
        self.fall = SimpleNamespace(**{
            k: _s(fall.get(k)) for k in
            "slug titel auftrag interesse zusammenfassung erstellt stand".split()})
        for art in _SCHEMA:
            setattr(self, art, [_norm(r, art) for r in _liste(daten.get(art))])
        self.claim = {c.id: c for c in self.behauptungen}
        self.beleg = {b.id: b for b in self.belege}
        self.quelle = {q.id: q for q in self.quellen}
        self.akteur = {p.id: p for p in self.akteure}
        self.hyp = {h.id: h for h in self.hypothesen}
        self.frage = {f.id: f for f in self.fragen}
        self._berechne_fragen()
        self.gruppen = self._gruppiere_behauptungen()
        self.belege_ohne_behauptung = self._unbelegte_belege()
        self.ereignisse_sortiert = sorted(
            self.ereignisse, key=lambda e: (e.datum == "", e.datum))
        self.status_zaehlung = _zaehle(
            [c.status for c in self.behauptungen], BEFUND_REIHENFOLGE)
        self.bereitschaft = self._bereitschaft()
        self.probleme_gruppen = self._gruppiere_probleme()
        self.suchen_je_hypothese = self._zaehle_suchen()
        self.kurzfassung = self._kurzfassung()
        self.abschnitte = self._abschnitte()
        self.ziele = self._ziele()

    # -- Auflösung ----------------------------------------------------------

    def bekannt(self, id_):
        return id_ in self.ziele

    def name(self, akteur_id):
        akteur = self.akteur.get(akteur_id)
        return (akteur.name or akteur.id) if akteur else akteur_id

    def quelle_info(self, quelle_id):
        q = self.quelle.get(quelle_id)
        if q is None:
            return None
        return SimpleNamespace(
            id=q.id, titel=q.titel, herausgeber=q.herausgeber, datum=q.datum,
            typ=label(q.typ), zuverlaessigkeit=ZUVERL_LABEL.get(
                q.zuverlaessigkeit, q.zuverlaessigkeit))

    def _ziele(self):
        """IDs, die in beiden Formaten als Ziel eines Verweises existieren."""
        objekte = (self.hypothesen, self.behauptungen, self.belege,
                   self.quellen, self.akteure, self.beziehungen,
                   self.ereignisse, self.konfrontationen)
        ziele = {o.id for liste in objekte for o in liste if o.id}
        ziele.update(f.id for f in self.fragen_sichtbar if f.id)
        return ziele

    # -- Fragen -------------------------------------------------------------

    def _berechne_fragen(self):
        self.fragen_offen = [f for f in self.fragen
                             if f.status not in ("beantwortet", "sackgasse")]
        self.fragen_sackgassen = [f for f in self.fragen if f.status == "sackgasse"]
        self.fragen_aufgaben = [f for f in self.fragen if f.mensch]
        gesehen = []
        for f in self.fragen_offen + self.fragen_sackgassen + self.fragen_aufgaben:
            if f not in gesehen:
                gesehen.append(f)
        self.fragen_sichtbar = gesehen

    # -- Behauptungen und Belege -------------------------------------------

    def _gruppiere_behauptungen(self):
        rang = {s: i for i, s in enumerate(BEFUND_REIHENFOLGE)}
        gruppen = {}
        for c in self.behauptungen:
            gruppen.setdefault(c.hypothese if c.hypothese in self.hyp else None,
                               []).append(c)
        ergebnis = []
        for h in self.hypothesen + [None]:
            claims = gruppen.get(h.id if h else None, [])
            if claims:
                ergebnis.append((h, sorted(
                    claims, key=lambda c: rang.get(c.status, len(rang)))))
        return ergebnis

    def claims_von(self, hypothese):
        for h, claims in self.gruppen:
            if h is hypothese:
                return claims
        return []

    def _unbelegte_belege(self):
        genutzt = {b for c in self.behauptungen for b in c.pro + c.contra}
        return [b for b in self.belege if b.id not in genutzt]

    # -- Kopf, Probleme -----------------------------------------------------

    def _bereitschaft(self):
        zaehler = dict(_zaehle([p.stufe for p in self.probleme], STUFEN))
        sperren = zaehler.get("sperre")
        if sperren:
            wort = "Sperre" if sperren == 1 else "Sperren"
            return f"Arbeitsstand: {sperren} {wort} offen. Aussagen nicht belastbar."
        offen = zaehler.get("veroeffentlichung")
        if offen:
            wort = "Punkt" if offen == 1 else "Punkte"
            return ("Recherchestand geprüft. Vor einer Veröffentlichung "
                    f"offen: {offen} {wort}.")
        return "Recherchestand geprüft."

    def _gruppiere_probleme(self):
        return [(stufe, [p for p in self.probleme if p.stufe == stufe])
                for stufe, _ in _zaehle([p.stufe for p in self.probleme], STUFEN)]

    # -- Suchen -------------------------------------------------------------

    def _suche_hypothese(self, suche):
        if suche.hypothese:
            return suche.hypothese
        frage = self.frage.get(suche.frage)
        return frage.hypothese if frage else ""

    def _zaehle_suchen(self):
        return {h.id: _zaehle(
            [s.richtung for s in self.suchen if self._suche_hypothese(s) == h.id],
            RICHTUNGEN, mit_null=True) for h in self.hypothesen}

    # -- Kurzfassung --------------------------------------------------------

    def _segmente(self, absatz):
        segmente, pos = [], 0
        for m in _VERWEIS.finditer(absatz):
            if m.start() > pos:
                segmente.append(("text", absatz[pos:m.start()]))
            c = self.claim.get(m.group(1))
            segmente.append(("ref", m.group(1), c is not None,
                             (label(c.status) or "ohne Status") if c else "unbekannt"))
            pos = m.end()
        if pos < len(absatz):
            segmente.append(("text", absatz[pos:]))
        return segmente

    def _kurzfassung(self):
        absaetze = [p.strip() for p in re.split(r"\n\s*\n", self.fall.zusammenfassung)
                    if p.strip()]
        geparst = [self._segmente(p) for p in absaetze]
        unbekannt = []
        for segmente in geparst:
            for seg in segmente:
                if seg[0] == "ref" and not seg[2] and seg[1] not in unbekannt:
                    unbekannt.append(seg[1])
        ersatz = [c for s in ("belegt", "gestuetzt") for c in self.behauptungen
                  if c.status == s] if not geparst else []
        return SimpleNamespace(
            absaetze=[(segs, any(s[0] == "ref" for s in segs)) for segs in geparst],
            unbekannt=unbekannt, ersatz=ersatz)

    # -- Abschnitte, Methode -----------------------------------------------

    def _abschnitte(self):
        vorhanden = {
            "kurzfassung": True, "offen": self.probleme,
            "hypothesen": self.hypothesen,
            "befunde": self.behauptungen or self.belege,
            "chronologie": self.ereignisse,
            "akteure": self.akteure or self.beziehungen,
            "fragen": self.fragen_sichtbar, "konfrontation": self.konfrontationen,
            "methode": True, "quellen": self.quellen,
        }
        return [k for k in ABSCHNITT_TITEL if vorhanden[k]]

    def methode(self):
        gesamt = len(self.behauptungen)
        return SimpleNamespace(
            quellen_typ=_zaehle([q.typ or "unbekannt" for q in self.quellen],
                                QUELLENTYPEN),
            quellen_text=sum(1 for q in self.quellen if q.art == "text"),
            suchen=_zaehle([s.richtung for s in self.suchen], RICHTUNGEN,
                           mit_null=True),
            belege=len(self.belege),
            anteile=[(s, _anteil(n, gesamt)) for s, n in self.status_zaehlung],
            gesamt=gesamt)


# --- Markdown ---------------------------------------------------------------

_MD_SONDER = re.compile(r"([\\`*_\[\]<>|&~])")
_HTTP_URL = re.compile(r"https?://[^\s<>\"'\x00-\x1f]+\Z", re.IGNORECASE)


def md(wert, kuerzen=True):
    """Einzeiliger, maskierter Text; Zeilenanfänge können keine Struktur bilden."""
    text = re.sub(r"\s+", " ", _s(wert))
    text = _MD_SONDER.sub(r"\\\1", text.strip() if kuerzen else text)
    text = re.sub(r"^(\d+)([.)])", r"\1\\\2", text)
    return re.sub(r"^([#+\-=])", r"\\\1", text)


def md_zitat(wert):
    zeilen = _s(wert).splitlines() or [""]
    return "\n".join(("> " + md(z)) if z.strip() else ">" for z in zeilen)


def md_url(url):
    return f"<{url}>" if _HTTP_URL.match(url) else md(url)


def md_ref(a, id_):
    return f"[{id_}]" if a.bekannt(id_) else f"{md(id_)} (unbekannt)"


def md_refs(a, ids):
    return ", ".join(md_ref(a, i) for i in ids) if ids else "—"


def md_namen(a, ids):
    return ", ".join(f"{md(a.name(i))} ({md_ref(a, i)})" if a.bekannt(i)
                     else md(i) for i in ids)


def md_quelle(a, quelle_id):
    info = a.quelle_info(quelle_id)
    if info is None:
        return f"{md(quelle_id)} (unbekannt)" if quelle_id else "—"
    teile = [info.titel, info.herausgeber, info.datum, info.typ,
             info.zuverlaessigkeit]
    return f"[{info.id}] " + " · ".join(md(t) for t in teile if t)


def md_beleg(a, bid):
    b = a.beleg.get(bid)
    if b is None:
        return f"**{md(bid)}** (unbekannt)"
    kopf = f"**[{b.id}]**"
    if b.direkt:
        kopf += " · Primärbeleg"
    if b.stelle is not None:
        kopf += f" · Stelle {b.stelle}"
    zeilen = [kopf, md_zitat(b.zitat)]
    if b.aussage:
        zeilen.append(f"Aussage: {md(b.aussage)}")
    if not b.zitat_ok:
        zeilen.append("**Warnung:** Zitat nicht mehr im Schnappschuss")
    zeilen.append(f"Quelle: {md_quelle(a, b.quelle)}")
    return "\n\n".join(zeilen)


def md_felder(paare):
    return "\n".join(f"- **{k}:** {v}" for k, v in paare if v)


def md_behauptung(a, c):
    felder = [
        ("Art / Status", " · ".join(
            [md(label(c.art)) + (" (Zuschreibung)" if c.zuschreibung else ""),
             label(c.status) or "ohne Status"]
            + (["belastend"] if c.belastend else []))),
        ("Betrifft", md_namen(a, c.betrifft)),
    ]
    if zeige_obergrenze(c):
        grund = f" — {md(c.obergrenze_grund)}" if c.obergrenze_grund else ""
        felder.append(("Obergrenze", md(label(c.obergrenze)) + grund))
    if c.vermerk or c.pruefer or c.geprueft:
        von = ", ".join(x for x in (
            f"Prüfer: {md(c.pruefer)}" if c.pruefer else "",
            f"geprüft: {md(c.geprueft)}" if c.geprueft else "") if x)
        felder.append(("Vermerk", md(c.vermerk) + (f" ({von})" if von else "")))
    felder.append(("Klärung", md(c.klaerung)))
    felder.append(("Beruht auf", md_refs(a, c.aus) if c.aus else ""))
    teile = [f"#### {c.id} — {md(c.text)}", md_felder(felder),
             "**Belege dafür:**"]
    teile += [md_beleg(a, b) for b in c.pro] or ["keine"]
    if c.contra:
        teile.append("**Belege dagegen:**")
        teile += [md_beleg(a, b) for b in c.contra]
    return "\n\n".join(teile)


def _md_kopf(a):
    f = a.fall
    teile = [f"# {md(f.titel) or 'Dossier'}"]
    if f.auftrag:
        teile.append(f"**Auftrag:** {md(f.auftrag)}")
    if f.interesse:
        teile.append(f"**Öffentliches Interesse:** {md(f.interesse)}")
    if f.stand:
        teile.append(f"Stand: {md(f.stand)}")
    teile.append(f"**{a.bereitschaft}**")
    teile.append(f"Behauptungen: {len(a.behauptungen)}"
                 + (f" — {_zaehlung_text(a.status_zaehlung)}" if a.behauptungen else ""))
    return "\n\n".join(teile)


def _md_kurzfassung(a):
    k = a.kurzfassung
    teile = ["## Kurzfassung"]
    if not k.absaetze:
        teile.append("Keine Kurzfassung hinterlegt.")
        if k.ersatz:
            teile.append("\n".join(f"- [{c.id}] {md(c.text)} ({status_text(c)})"
                                   for c in k.ersatz))
        return "\n\n".join(teile)
    for segmente, hat_verweis in k.absaetze:
        text = "".join(md(s[1], kuerzen=False) if s[0] == "text" else f"[{s[1]} · {s[3]}]"
                       for s in segmente)
        teile.append(text if hat_verweis else f"{text} (ohne Belegverweis)")
    if k.unbekannt:
        teile.append("**Warnung:** Verweis auf unbekannte Behauptung: "
                     + ", ".join(f"[{i}]" for i in k.unbekannt))
    return "\n\n".join(teile)


def _md_offen(a):
    teile = ["## Offene Punkte"]
    for stufe, probleme in a.probleme_gruppen:
        zeilen = [f"- {md(p.art)} · {md_ref(a, p.objekt) if p.objekt else '—'}: "
                  f"{md(p.text)}" for p in probleme]
        teile += [f"### {md(STUFE_LABEL.get(stufe, stufe))} ({len(probleme)})",
                  "\n".join(zeilen)]
    return "\n\n".join(teile)


def kriterien_von(h):
    """Die frei formulierten Prüfkriterien einer Hypothese als (Titel, Punkte)."""
    return [(titel, punkte) for titel, punkte in (
        ("Müsste wahr sein", h.prueft), ("Würde sie widerlegen", h.widerlegt))
        if punkte]


def _md_hypothese(a, h):
    suchen = _zaehlung_text(a.suchen_je_hypothese[h.id])
    claims = "\n".join(f"- [{c.id}] ({status_text(c)}) {md(c.text)}"
                       for c in a.claims_von(h))
    felder = md_felder([
        ("Status", md(label(h.status))), ("Vermerk", md(h.vermerk)),
        ("Suchen", suchen)])
    kriterien = []
    for titel, punkte in kriterien_von(h):
        kriterien += [f"**{titel}:**", "\n".join(f"- {md(p)}" for p in punkte)]
    return "\n\n".join([f"### {h.id} — {md(h.text)}", felder] + kriterien
                       + (["**Behauptungen:**", claims]
                          if claims else []))


def _md_befunde(a):
    teile = ["## Befunde"]
    if any(c.zuschreibung for c in a.behauptungen):
        teile.append(ZUSCHREIBUNG_SATZ)
    for h, claims in a.gruppen:
        teile.append(f"### {h.id} — {md(h.text)}" if h else "### Ohne Hypothese")
        teile += [md_behauptung(a, c) for c in claims]
    if a.belege_ohne_behauptung:
        teile.append("### Belege ohne Behauptung")
        teile += [md_beleg(a, b.id) for b in a.belege_ohne_behauptung]
    return "\n\n".join(teile)


def _md_chronologie(a):
    zeilen = []
    for e in a.ereignisse_sortiert:
        zusatz = "; ".join(x for x in (
            f"Akteure: {md_namen(a, e.akteure)}" if e.akteure else "",
            f"Belege: {md_refs(a, e.belege)}" if e.belege else "") if x)
        zeilen.append(f"- [{e.id}] {md(e.datum) or 'ohne Datum'} — {md(e.text)}"
                      + (f" ({zusatz})" if zusatz else ""))
    return "## Chronologie\n\n" + "\n".join(zeilen)


def md_tabelle(kopf, zeilen):
    rows = ["| " + " | ".join(kopf) + " |", "|" + " --- |" * len(kopf)]
    rows += ["| " + " | ".join(z) + " |" for z in zeilen]
    return "\n".join(rows)


def kennungen_text(p):
    return "; ".join(f"{k}: {v}" for k, v in p.kennungen.items())


def _md_akteure(a):
    teile = ["## Akteure und Beziehungen"]
    if a.akteure:
        teile.append(md_tabelle(
            ["ID", "Name", "Art", "Kategorie", "Kennungen", "Belege"],
            [[p.id, md(p.name), md(label(p.art)), md(label(p.kategorie)),
              md(kennungen_text(p)), md_refs(a, p.belege)] for p in a.akteure]))
    zeilen = []
    for r in a.beziehungen:
        zeit = zeitraum(r.von_datum, r.bis_datum)
        zeilen.append(
            f"- [{r.id}] {md(a.name(r.von))} — {md(r.art)} → {md(a.name(r.zu))}"
            + (f" ({md(zeit)})" if zeit else "")
            + (f" — Belege: {md_refs(a, r.belege)}" if r.belege else ""))
    if zeilen:
        teile += ["### Beziehungen", "\n".join(zeilen)]
    return "\n\n".join(teile)


def _md_frage(a, f):
    teile = [f"[{f.id}] {md(f.text)}", f"Status: {md(label(f.status))}"]
    if f.hypothese:
        teile.append(f"Hypothese: {md_ref(a, f.hypothese)}")
    if f.plan:
        teile.append(f"Plan: {md(f.plan)}")
    if f.ergebnis:
        teile.append(f"Ergebnis: {md(f.ergebnis)}")
    return "- " + " — ".join(teile)


def _md_fragen(a):
    teile = ["## Fragen und Aufgaben"]
    for titel, fragen in (("Offene Fragen", a.fragen_offen),
                          ("Sackgassen", a.fragen_sackgassen),
                          ("Aufgaben für Menschen", a.fragen_aufgaben)):
        if fragen:
            teile += [f"### {titel}", "\n".join(_md_frage(a, f) for f in fragen)]
    return "\n\n".join(teile)


def _md_konfrontation(a):
    teile = ["## Konfrontation"]
    for k in a.konfrontationen:
        felder = md_felder([
            ("Frage", md(k.frage)),
            ("Bezieht sich auf", md_refs(a, k.zu) if k.zu else ""),
            ("Status", md(label(k.status))),
            ("Gesendet am", md(k.gesendet_am)), ("Frist", md(k.frist)),
            ("Antwort", md(k.antwort)),
            ("Quelle der Antwort",
             md_ref(a, k.antwort_quelle) if k.antwort_quelle else ""),
            ("Vermerk", md(k.vermerk))])
        teile += [f"### {k.id} — {md(a.name(k.akteur))}", felder]
    return "\n\n".join(teile)


def _md_methode(a):
    m = a.methode()
    zeilen = [
        f"Quellen je Typ: {_zaehlung_text(m.quellen_typ) or 'keine'}",
        f"Quellen der Art text (nicht selbst abgerufen): {m.quellen_text}",
        f"Suchen je Richtung: {_zaehlung_text(m.suchen)}",
        f"Belege: {m.belege}",
        "Anteil der Behauptungen je Status: "
        + (_zaehlung_text(m.anteile) if m.gesamt else "keine Behauptungen"),
    ]
    return "\n\n".join(["## Methode und Grenzen",
                        "\n".join(f"- {z}" for z in zeilen), GRENZEN_SATZ])


def quellen_zellen(q):
    return [q.id, q.titel, q.herausgeber, q.autor, q.datum, q.abgerufen, label(q.typ),
            ZUVERL_LABEL.get(q.zuverlaessigkeit, q.zuverlaessigkeit), q.ursprung,
            q.interesse, q.url, q.archiv_url, q.sha256[:12],
            "" if q.zeichen is None else str(q.zeichen), q.art]


QUELLEN_KOPF = ["ID", "Titel", "Herausgeber", "Autor", "Datum", "Abgerufen",
                "Typ", "Zuverlässigkeit", "Ursprung", "Interesse", "URL",
                "Archiv-URL", "SHA-256 (12)", "Zeichen", "Art"]


def _md_quellen(a):
    zeilen = []
    for q in a.quellen:
        z = quellen_zellen(q)
        zeilen.append([z[0]] + [md(x) for x in z[1:10]]
                      + [md_url(z[10]) if z[10] else "",
                         md_url(z[11]) if z[11] else ""]
                      + [md(x) for x in z[12:]])
    return "## Quellenverzeichnis\n\n" + md_tabelle(QUELLEN_KOPF, zeilen)


_MD_ABSCHNITTE = {
    "kurzfassung": _md_kurzfassung, "offen": _md_offen,
    "hypothesen": lambda a: "\n\n".join(
        ["## Hypothesen"] + [_md_hypothese(a, h) for h in a.hypothesen]),
    "befunde": _md_befunde, "chronologie": _md_chronologie,
    "akteure": _md_akteure, "fragen": _md_fragen,
    "konfrontation": _md_konfrontation, "methode": _md_methode,
    "quellen": _md_quellen,
}


def render_markdown(daten):
    a = _Ansicht(daten)
    bloecke = [_md_kopf(a)] + [_MD_ABSCHNITTE[k](a) for k in a.abschnitte]
    return "\n\n".join(bloecke) + "\n"


# --- HTML -------------------------------------------------------------------

CSS = """
:root{color-scheme:light dark;--bg:#fafaf7;--fg:#1d1d1b;--muted:#5a5a55;
--karte:#fff;--rand:#d6d6cc;--link:#0b5cad;--warn-bg:#fff4d6;--warn-fg:#6b4500;
--sperre:#a61b1b;
--belegt-bg:#dcf2e2;--belegt-fg:#12502a;--gestuetzt-bg:#dbe8fb;--gestuetzt-fg:#1b3a82;
--unbestaetigt-bg:#fdf0c4;--unbestaetigt-fg:#6b4500;--strittig-bg:#eadffb;--strittig-fg:#45228a;
--widerlegt-bg:#fbdcdc;--widerlegt-fg:#7a1818;--ungeprueft-bg:#e6e7ea;--ungeprueft-fg:#363940;
--werturteil-bg:#f4f4f1;--werturteil-fg:#2a2a28}
@media (prefers-color-scheme: dark){:root{--bg:#15171a;--fg:#e8e8e4;--muted:#a3a39c;
--karte:#1d2024;--rand:#3a3d42;--link:#7db4f0;--warn-bg:#3a2e0e;--warn-fg:#f3d58a;
--sperre:#ff8a8a;
--belegt-bg:#143a24;--belegt-fg:#a9e8bf;--gestuetzt-bg:#16294f;--gestuetzt-fg:#b4cdf6;
--unbestaetigt-bg:#3d3210;--unbestaetigt-fg:#f3d98a;--strittig-bg:#2c1d52;--strittig-fg:#d3bdf7;
--widerlegt-bg:#4a1717;--widerlegt-fg:#f6b5b5;--ungeprueft-bg:#2c2f35;--ungeprueft-fg:#c9ccd3;
--werturteil-bg:#222426;--werturteil-fg:#d8d8d3}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);line-height:1.55;
font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
overflow-wrap:anywhere}
main{max-width:46rem;margin:0 auto;padding:16px}
a{color:var(--link)}
h1{font-size:1.7rem;line-height:1.2;margin:.5rem 0}
h2{font-size:1.3rem;margin:2.2rem 0 .6rem;padding-top:.6rem;border-top:2px solid var(--rand)}
h3{font-size:1.1rem;margin:1.6rem 0 .4rem}
h4{font-size:1rem;margin:0 0 .4rem}
nav ol{padding-left:1.3rem;columns:2 12rem}
.bereitschaft{font-weight:600;padding:.6rem .8rem;border:2px solid var(--rand);
border-radius:6px;background:var(--karte)}
.bereitschaft.sperre{border-color:var(--sperre);color:var(--sperre)}
.muted{color:var(--muted)}
.karte{background:var(--karte);border:1px solid var(--rand);border-radius:6px;
padding:.7rem .9rem;margin:.8rem 0}
.beleg{border-left:3px solid var(--rand);padding-left:.8rem;margin:.8rem 0}
blockquote{margin:.4rem 0;padding:.2rem .8rem;border-left:4px solid var(--rand);
background:var(--bg);white-space:pre-wrap}
.badge{display:inline-block;padding:0 .5rem;border-radius:999px;font-size:.85rem;
font-weight:600;border:1px solid currentColor;white-space:nowrap}
.b-belegt{background:var(--belegt-bg);color:var(--belegt-fg)}
.b-gestuetzt{background:var(--gestuetzt-bg);color:var(--gestuetzt-fg)}
.b-unbestaetigt{background:var(--unbestaetigt-bg);color:var(--unbestaetigt-fg)}
.b-strittig{background:var(--strittig-bg);color:var(--strittig-fg)}
.b-widerlegt{background:var(--widerlegt-bg);color:var(--widerlegt-fg)}
.b-ungeprueft{background:var(--ungeprueft-bg);color:var(--ungeprueft-fg)}
.b-werturteil{background:var(--werturteil-bg);color:var(--werturteil-fg);border-style:dashed}
.warnung{background:var(--warn-bg);color:var(--warn-fg);padding:.3rem .6rem;
border-radius:4px;margin:.4rem 0}
.felder{padding-left:1.2rem;margin:.4rem 0}
.tabelle{overflow-x:auto;margin:.6rem 0}
table{border-collapse:collapse;font-size:.9rem;min-width:100%}
th,td{border:1px solid var(--rand);padding:.3rem .5rem;text-align:left;vertical-align:top}
th{background:var(--karte)}
"""


def e(wert):
    return html.escape(_s(wert), quote=True)


def h_klasse(status):
    return "b-" + BADGE_KLASSE.get(status, "werturteil")


def h_badge(status, text=None):
    return f'<span class="badge {h_klasse(status)}">{e(text or label(status) or "ohne Status")}</span>'


def h_url(url, text=None):
    """Nur http(s)-URLs werden Links; alles andere bleibt escapter Text."""
    if not url:
        return ""
    if _HTTP_URL.match(url):
        return (f'<a href="{e(url)}" rel="noopener noreferrer">'
                f'{e(text or url)}</a>')
    return e(url)


def zuschreibung_marke(c):
    return (' <span class="badge b-werturteil">Zuschreibung</span>'
            if c.zuschreibung else "")


class _Html:
    def __init__(self, a):
        self.a = a
        self.gesehen = set()

    # -- Bausteine ----------------------------------------------------------

    def anker(self, id_):
        """` id="X"` beim ersten Aufruf je ID, danach leer (IDs sind eindeutig)."""
        if not id_ or id_ in self.gesehen:
            return ""
        self.gesehen.add(id_)
        return f' id="{e(id_)}"'

    def ref(self, id_, text=None):
        if self.a.bekannt(id_):
            return f'<a href="#{e(id_)}">{e(text or f"[{id_}]")}</a>'
        return f"{e(id_)} (unbekannt)"

    def refs(self, ids):
        return ", ".join(self.ref(i) for i in ids) if ids else "—"

    def namen(self, ids):
        return ", ".join(
            f'<a href="#{e(i)}">{e(self.a.name(i))}</a>' if self.a.bekannt(i)
            else e(i) for i in ids)

    def objekt(self, id_):
        return self.ref(id_) if id_ else "—"

    def felder(self, paare):
        items = "".join(f"<li><strong>{e(k)}:</strong> {v}</li>"
                        for k, v in paare if v)
        return f'<ul class="felder">{items}</ul>' if items else ""

    def tabelle(self, kopf, zeilen):
        th = "".join(f"<th>{e(k)}</th>" for k in kopf)
        tr = "".join(f"<tr{i}>" + "".join(f"<td>{z}</td>" for z in zelle) + "</tr>"
                     for i, zelle in zeilen)
        return (f'<div class="tabelle"><table><thead><tr>{th}</tr></thead>'
                f"<tbody>{tr}</tbody></table></div>")

    def quelle(self, quelle_id):
        info = self.a.quelle_info(quelle_id)
        if info is None:
            return f"{e(quelle_id)} (unbekannt)" if quelle_id else "—"
        titel = self.ref(info.id, info.titel or info.id)
        rest = [e(x) for x in (info.herausgeber, info.datum, info.typ,
                               info.zuverlaessigkeit) if x]
        return " · ".join([titel] + rest)

    # -- Belege und Behauptungen -------------------------------------------

    def beleg(self, bid):
        b = self.a.beleg.get(bid)
        if b is None:
            return f'<div class="beleg">{e(bid)} (unbekannt)</div>'
        kennung = (f"<strong>{e(b.id)}</strong>" if b.id not in self.gesehen
                   else self.ref(b.id))
        marken = (" · Primärbeleg" if b.direkt else "") + (
            f" · Stelle {b.stelle}" if b.stelle is not None else "")
        teile = [f"<p>{kennung}{e(marken)}</p>",
                 f"<blockquote>{e(b.zitat)}</blockquote>"]
        if b.aussage:
            teile.append(f"<p>Aussage: {e(b.aussage)}</p>")
        if not b.zitat_ok:
            teile.append('<p class="warnung">Zitat nicht mehr im Schnappschuss</p>')
        teile.append(f'<p class="muted">Quelle: {self.quelle(b.quelle)}</p>')
        return f'<div class="beleg"{self.anker(b.id)}>' + "".join(teile) + "</div>"

    def behauptung(self, c):
        a = self.a
        kopf = (f"<p>{e(label(c.art))}{zuschreibung_marke(c)} {h_badge(c.status)}"
                + (' <span class="badge b-widerlegt">belastend</span>'
                   if c.belastend else "") + "</p>")
        felder = [("Betrifft", self.namen(c.betrifft))]
        if zeige_obergrenze(c):
            felder.append(("Obergrenze", e(label(c.obergrenze))
                           + (f" — {e(c.obergrenze_grund)}" if c.obergrenze_grund else "")))
        if c.vermerk or c.pruefer or c.geprueft:
            von = ", ".join(x for x in (
                f"Prüfer: {e(c.pruefer)}" if c.pruefer else "",
                f"geprüft: {e(c.geprueft)}" if c.geprueft else "") if x)
            felder.append(("Vermerk", e(c.vermerk) + (f" ({von})" if von else "")))
        felder.append(("Klärung", e(c.klaerung)))
        felder.append(("Beruht auf", self.refs(c.aus) if c.aus else ""))
        teile = [f'<article class="karte"{self.anker(c.id)}>',
                 f"<h4>{e(c.id)} — {e(c.text)}</h4>", kopf, self.felder(felder),
                 "<p><strong>Belege dafür</strong></p>"]
        teile += [self.beleg(b) for b in c.pro] or ["<p>keine</p>"]
        if c.contra:
            teile.append("<p><strong>Belege dagegen</strong></p>")
            teile += [self.beleg(b) for b in c.contra]
        teile.append("</article>")
        return "".join(teile)

    # -- Abschnitte ---------------------------------------------------------

    def kopf(self):
        a, f = self.a, self.a.fall
        teile = [f"<header><h1>{e(f.titel) or 'Dossier'}</h1>"]
        if f.auftrag:
            teile.append(f"<p><strong>Auftrag:</strong> {e(f.auftrag)}</p>")
        if f.interesse:
            teile.append(f"<p><strong>Öffentliches Interesse:</strong> {e(f.interesse)}</p>")
        if f.stand:
            teile.append(f'<p class="muted">Stand: {e(f.stand)}</p>')
        klasse = "bereitschaft sperre" if a.bereitschaft.startswith("Arbeitsstand") \
            else "bereitschaft"
        teile.append(f'<p class="{klasse}">{e(a.bereitschaft)}</p>')
        teile.append(f"<p>Behauptungen: {len(a.behauptungen)}"
                     + (f" — {e(_zaehlung_text(a.status_zaehlung))}"
                        if a.behauptungen else "") + "</p></header>")
        return "".join(teile)

    def inhaltsverzeichnis(self):
        punkte = "".join(f'<li><a href="#sec-{k}">{e(ABSCHNITT_TITEL[k])}</a></li>'
                         for k in self.a.abschnitte)
        return f'<nav aria-label="Inhalt"><ol>{punkte}</ol></nav>'

    def s_kurzfassung(self):
        k = self.a.kurzfassung
        if not k.absaetze:
            ersatz = "".join(
                f"<li>{self.ref(c.id)} {e(c.text)} {h_badge(c.status)}{zuschreibung_marke(c)}</li>"
                for c in k.ersatz)
            return ("<p>Keine Kurzfassung hinterlegt.</p>"
                    + (f"<ul>{ersatz}</ul>" if ersatz else ""))
        teile = []
        for segmente, hat_verweis in k.absaetze:
            text = "".join(self.segment(s) for s in segmente)
            marke = "" if hat_verweis else ' <span class="muted">(ohne Belegverweis)</span>'
            teile.append(f"<p>{text}{marke}</p>")
        if k.unbekannt:
            teile.append('<p class="warnung">Verweis auf unbekannte Behauptung: '
                         + ", ".join(f"[{e(i)}]" for i in k.unbekannt) + "</p>")
        return "".join(teile)

    def segment(self, seg):
        if seg[0] == "text":
            return e(seg[1])
        _, id_, bekannt, status_label = seg
        text = f"[{id_} · {status_label}]"
        if bekannt:
            return f'<a href="#{e(id_)}">{e(text)}</a>'
        return f'<span class="warnung">{e(text)}</span>'

    def s_offen(self):
        teile = []
        for stufe, probleme in self.a.probleme_gruppen:
            items = "".join(f"<li>{e(p.art)} · {self.objekt(p.objekt)}: {e(p.text)}</li>"
                            for p in probleme)
            teile.append(f"<h3>{e(STUFE_LABEL.get(stufe, stufe))} ({len(probleme)})</h3>"
                         f"<ul>{items}</ul>")
        return "".join(teile)

    def s_hypothesen(self):
        a, teile = self.a, []
        for h in a.hypothesen:
            claims = "".join(
                f"<li>{self.ref(c.id)} {h_badge(c.status)}{zuschreibung_marke(c)} {e(c.text)}</li>"
                for c in a.claims_von(h))
            felder = self.felder([
                ("Status", h_badge(h.status)), ("Vermerk", e(h.vermerk)),
                ("Suchen", e(_zaehlung_text(a.suchen_je_hypothese[h.id])))])
            kriterien = "".join(
                f"<p><strong>{e(titel)}</strong></p><ul>"
                + "".join(f"<li>{e(p)}</li>" for p in punkte) + "</ul>"
                for titel, punkte in kriterien_von(h))
            teile.append(f'<article class="karte"{self.anker(h.id)}>'
                         f"<h3>{e(h.id)} — {e(h.text)}</h3>{felder}{kriterien}"
                         + (f"<p><strong>Behauptungen</strong></p><ul>{claims}</ul>"
                            if claims else "") + "</article>")
        return "".join(teile)

    def s_befunde(self):
        a, teile = self.a, []
        if any(c.zuschreibung for c in a.behauptungen):
            teile.append(f"<p>{e(ZUSCHREIBUNG_SATZ)}</p>")
        for h, claims in a.gruppen:
            teile.append(f"<h3>{e(h.id)} — {e(h.text)}</h3>" if h
                         else "<h3>Ohne Hypothese</h3>")
            teile += [self.behauptung(c) for c in claims]
        if a.belege_ohne_behauptung:
            teile.append("<h3>Belege ohne Behauptung</h3>")
            teile += [self.beleg(b.id) for b in a.belege_ohne_behauptung]
        return "".join(teile)

    def s_chronologie(self):
        a, items = self.a, []
        for ev in a.ereignisse_sortiert:
            zusatz = "; ".join(x for x in (
                f"Akteure: {self.namen(ev.akteure)}" if ev.akteure else "",
                f"Belege: {self.refs(ev.belege)}" if ev.belege else "") if x)
            items.append(f"<li{self.anker(ev.id)}><strong>{e(ev.datum) or 'ohne Datum'}</strong>"
                         f" — {e(ev.text)}" + (f" ({zusatz})" if zusatz else "") + "</li>")
        return f"<ul>{''.join(items)}</ul>"

    def s_akteure(self):
        a, teile = self.a, []
        if a.akteure:
            teile.append(self.tabelle(
                ["ID", "Name", "Art", "Kategorie", "Kennungen", "Belege"],
                [(self.anker(p.id), [e(p.id), e(p.name), e(label(p.art)), e(label(p.kategorie)),
                                     e(kennungen_text(p)), self.refs(p.belege)])
                 for p in a.akteure]))
        items = []
        for r in a.beziehungen:
            zeit = zeitraum(r.von_datum, r.bis_datum)
            items.append(
                f"<li{self.anker(r.id)}>{self.namen([r.von])} — {e(r.art)} → "
                f"{self.namen([r.zu])}" + (f" ({e(zeit)})" if zeit else "")
                + (f" — Belege: {self.refs(r.belege)}" if r.belege else "") + "</li>")
        if items:
            teile.append(f"<h3>Beziehungen</h3><ul>{''.join(items)}</ul>")
        return "".join(teile)

    def frage(self, f):
        felder = self.felder([
            ("Status", h_badge(f.status)),
            ("Hypothese", self.ref(f.hypothese) if f.hypothese else ""),
            ("Plan", e(f.plan)), ("Ergebnis", e(f.ergebnis))])
        return f"<li{self.anker(f.id)}><strong>{e(f.id)}</strong> {e(f.text)}{felder}</li>"

    def s_fragen(self):
        a, teile = self.a, []
        for titel, fragen in (("Offene Fragen", a.fragen_offen),
                              ("Sackgassen", a.fragen_sackgassen),
                              ("Aufgaben für Menschen", a.fragen_aufgaben)):
            if fragen:
                teile.append(f"<h3>{e(titel)}</h3><ul>"
                             + "".join(self.frage(f) for f in fragen) + "</ul>")
        return "".join(teile)

    def s_konfrontation(self):
        a, teile = self.a, []
        for k in a.konfrontationen:
            felder = self.felder([
                ("Frage", e(k.frage)),
                ("Bezieht sich auf", self.refs(k.zu) if k.zu else ""),
                ("Status", h_badge(k.status)),
                ("Gesendet am", e(k.gesendet_am)), ("Frist", e(k.frist)),
                ("Antwort", e(k.antwort)),
                ("Quelle der Antwort",
                 self.ref(k.antwort_quelle) if k.antwort_quelle else ""),
                ("Vermerk", e(k.vermerk))])
            teile.append(f'<article class="karte"{self.anker(k.id)}>'
                         f"<h4>{e(k.id)} — {self.namen([k.akteur])}</h4>{felder}</article>")
        return "".join(teile)

    def s_methode(self):
        m = self.a.methode()
        zeilen = [
            f"Quellen je Typ: {_zaehlung_text(m.quellen_typ) or 'keine'}",
            f"Quellen der Art text (nicht selbst abgerufen): {m.quellen_text}",
            f"Suchen je Richtung: {_zaehlung_text(m.suchen)}",
            f"Belege: {m.belege}",
            "Anteil der Behauptungen je Status: "
            + (_zaehlung_text(m.anteile) if m.gesamt else "keine Behauptungen"),
        ]
        return ("<ul>" + "".join(f"<li>{e(z)}</li>" for z in zeilen) + "</ul>"
                f"<p>{e(GRENZEN_SATZ)}</p>")

    def s_quellen(self):
        zeilen = []
        for q in self.a.quellen:
            z = quellen_zellen(q)
            zellen = ([e(z[0])] + [e(x) for x in z[1:10]]
                      + [h_url(z[10]), h_url(z[11])] + [e(x) for x in z[12:]])
            zeilen.append((self.anker(q.id), zellen))
        return self.tabelle(QUELLEN_KOPF, zeilen)

    # -- Dokument -----------------------------------------------------------

    def dokument(self):
        a = self.a
        abschnitte = "".join(
            f'<section id="sec-{k}"><h2>{e(ABSCHNITT_TITEL[k])}</h2>'
            f"{getattr(self, 's_' + k)()}</section>" for k in a.abschnitte)
        return (
            '<!DOCTYPE html>\n<html lang="de"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{e(a.fall.titel) or 'Dossier'}</title>"
            f"<style>{CSS}</style></head><body><main>"
            f"{self.kopf()}{self.inhaltsverzeichnis()}{abschnitte}"
            "</main></body></html>\n")


def render_html(daten):
    return _Html(_Ansicht(daten)).dokument()
