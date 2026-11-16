"""Bewertung: Statusregeln für Behauptungen, Unabhängigkeit der Quellen, Integritätsprüfung, Export."""

import shutil
import sqlite3
from pathlib import Path

from . import quellen as q
from .store import (BEHAUPTUNGS_STATUS, Fall, Fehler, PRUEFBARE_STATUS, jetzt, lade_fall,
                    zu_dict, zu_liste)

PRIMAER_TYPEN = ("amtlich", "register", "gericht", "parlament")
PRIMAER_BEZEICHNUNG = {"amtlich": "amtlicher Quelle", "register": "Registerquelle",
                       "gericht": "Gerichtsquelle", "parlament": "parlamentarischer Quelle"}
STARKE_BEWERTUNG = ("A", "B", "C")
RANG = {"unbestaetigt": 0, "gestuetzt": 1, "belegt": 2}
GEPRUEFT = PRUEFBARE_STATUS
WIDERSPRUCHS_STATUS = ("strittig", "widerlegt", "unbestaetigt")

STUFEN = ("sperre", "veroeffentlichung", "hinweis")
STUFE_ANZEIGE = {"sperre": "SPERRE", "veroeffentlichung": "VOR VERÖFFENTLICHUNG",
                 "hinweis": "HINWEIS"}


# ===========================================================================
# Unabhängigkeit und Obergrenze (reine Funktionen)
# ===========================================================================

def ursprungs_schluessel(text):
    return " ".join((text or "").casefold().split())


def unabhaengigkeitsgruppen(quellen):
    """{Quellen-ID: Gruppenkennung}. Quellen gehören zur selben Gruppe, wenn eine
    die andere (auch über Zwischenquellen) als Ursprung nennt oder beide denselben
    Ursprungstext haben."""
    eltern = {quelle["id"]: quelle["id"] for quelle in quellen}

    def wurzel(x):
        while eltern[x] != x:
            eltern[x] = eltern[eltern[x]]
            x = eltern[x]
        return x

    def vereine(a, b):
        eltern[wurzel(a)] = wurzel(b)

    erste_mit_text = {}
    for quelle in quellen:
        ursprung = (quelle.get("ursprung") or "").strip()
        if not ursprung:
            continue
        if ursprung.upper() in eltern:
            vereine(quelle["id"], ursprung.upper())
        schluessel = ursprungs_schluessel(ursprung)
        vereine(quelle["id"], erste_mit_text.setdefault(schluessel, quelle["id"]))
    return {quelle["id"]: wurzel(quelle["id"]) for quelle in quellen}


def _primaerbeleg(pro, quellen_nach_id, zuschreibung):
    """Text, welcher Fall von `primaer` zutrifft, sonst None.

    Immer nötig: direkter Beleg einer Quelle mit Zuverlässigkeit A-C. Dazu
    entweder ein Primärquellen-Typ oder eine Zuschreibung (beliebiger Typ)."""
    direkte = [(b, quellen_nach_id[b["quelle"]]) for b in pro if b["direkt"]]
    verlaesslich = [(b, x) for b, x in direkte if x["zuverlaessigkeit"] in STARKE_BEWERTUNG]
    for beleg, quelle in verlaesslich:
        if quelle["typ"] in PRIMAER_TYPEN:
            return "Primärbeleg aus %s (%s)" % (PRIMAER_BEZEICHNUNG[quelle["typ"]], beleg["id"])
    if zuschreibung and verlaesslich:
        return "Zuschreibung, von der Quelle selbst direkt belegt (%s)" % verlaesslich[0][0]["id"]
    return None


def _obergrenze_tatsache(zuschreibung, pro, quellen_nach_id, gruppen):
    if not pro:
        return "unbestaetigt", "keine Belege"
    nach_gruppe = {}
    for beleg in pro:
        nach_gruppe.setdefault(gruppen[beleg["quelle"]], set()).add(beleg["quelle"])
    starke = [g for g, ids in nach_gruppe.items()
              if any(quellen_nach_id[i]["zuverlaessigkeit"] in STARKE_BEWERTUNG for i in ids)]
    primaer = _primaerbeleg(pro, quellen_nach_id, zuschreibung)
    fakten = "Quellengruppen: %d, davon mit Zuverlässigkeit A-C: %d" % (len(nach_gruppe), len(starke))
    if primaer:
        return "belegt", "%s; %s" % (primaer, fakten)
    if len(starke) >= 2:
        return "belegt", fakten
    if starke:
        kein = "kein direkter Primärbeleg" + (" und keine direkte Zuschreibung" if zuschreibung else "")
        return "gestuetzt", "%s; %s" % (fakten, kein)
    return "unbestaetigt", "%s; keine zuverlässige Quelle" % fakten


def _obergrenze_schlussfolgerung(aus_stati):
    if not aus_stati:
        return "unbestaetigt", "keine Prämissen (--aus)"
    schwach = ["%s (%s)" % (i, s) for i, s in aus_stati if s not in ("belegt", "gestuetzt")]
    if schwach:
        return "unbestaetigt", "Prämissen nicht belegt oder gestützt: " + ", ".join(schwach)
    return "gestuetzt", "alle Prämissen belegt oder gestützt; eine Schlussfolgerung ist nie belegt"


def obergrenze(art, zuschreibung, pro, quellen_nach_id, gruppen, aus_stati):
    """Höchster zulässiger Status einer Behauptung samt Begründung.

    pro: Belege (dicts mit id, quelle, direkt); quellen_nach_id: {ID: Quelle};
    gruppen: Ergebnis von unabhaengigkeitsgruppen; aus_stati: [(ID, Status)]."""
    if art == "bewertung":
        return "werturteil", "Bewertung: Werturteil, keine Tatsachenbehauptung"
    if art == "schlussfolgerung":
        return _obergrenze_schlussfolgerung(aus_stati)
    return _obergrenze_tatsache(zuschreibung, pro, quellen_nach_id, gruppen)


# ===========================================================================
# Daten eines Falls für Prüfung, Statusregeln und Export
# ===========================================================================

class Kontext:
    """Momentaufnahme aller Objekte eines Falls (einmal gelesen, vielfach genutzt)."""

    def __init__(self, fall):
        self.fall = fall
        self.quellen = {x["id"]: x for x in fall.alle("quelle")}
        self.gruppen = unabhaengigkeitsgruppen(list(self.quellen.values()))
        self.belege = {x["id"]: x for x in fall.alle("beleg")}
        self.behauptungen = {x["id"]: x for x in fall.alle("behauptung")}
        self.akteure = {x["id"]: x for x in fall.alle("akteur")}
        self.pro = fall.verknuepfungen("pro")
        self.contra = fall.verknuepfungen("contra")
        self.aus = fall.verknuepfungen("aus")
        self.betrifft = fall.verknuepfungen("betrifft")
        self._normtexte = {}

    def belege_von(self, liste):
        return [self.belege[i] for i in liste]

    def obergrenze(self, behauptung):
        aid = behauptung["id"]
        aus_stati = [(i, self.behauptungen[i]["status"]) for i in self.aus.get(aid, [])]
        return obergrenze(behauptung["art"], bool(behauptung["zuschreibung"]),
                          self.belege_von(self.pro.get(aid, [])), self.quellen, self.gruppen,
                          aus_stati)

    def normtext(self, quelle_id):
        if quelle_id not in self._normtexte:
            self._normtexte[quelle_id] = q.normalisiere(self.fall.lies_text(quelle_id))
        return self._normtexte[quelle_id]

    def zitat_ok(self, beleg):
        teile = q.zitat_teile(beleg["zitat"])
        return q.finde_teile(teile, self.normtext(beleg["quelle"])) is not None

    def gruppen_der(self, belege):
        return {self.gruppen[b["quelle"]] for b in belege}


# ===========================================================================
# Statusänderungen
# ===========================================================================

def pruefe_status(fall, behauptung_id, status, vermerk, pruefer):
    """`behauptung pruefen`: erzwingt Obergrenze und Widerspruchsregel."""
    kontext = Kontext(fall)
    a = kontext.behauptungen[behauptung_id]
    if a["art"] == "bewertung":
        raise Fehler("Eine Bewertung hat immer den Status werturteil.")
    grenze, grund = kontext.obergrenze(a)
    if status in ("belegt", "gestuetzt") and RANG[status] > RANG[grenze]:
        raise Fehler("Status %s nicht zulässig. Obergrenze: %s (%s)" % (status, grenze, grund))
    contra = kontext.contra.get(behauptung_id, [])
    if contra and not a["klaerung"].strip() and status not in WIDERSPRUCHS_STATUS:
        raise Fehler("Widerspruch ungeklärt (%s). Erst mit behauptung setzen --klaerung "
                     "begründen oder Status strittig wählen." % ", ".join(contra))
    fall.aendern("behauptung", behauptung_id, status=status, vermerk=vermerk, pruefer=pruefer,
                 geprueft=jetzt())
    fall.log("behauptung pruefen", behauptung_id, "%s: %s" % (status, vermerk))


def zuruecksetzen(fall, behauptung_id):
    """Setzt die Prüfung zurück. True, wenn eine echte Prüfung verworfen wurde."""
    a = fall.hole(behauptung_id, "A")
    neu = "werturteil" if a["art"] == "bewertung" else "ungeprueft"
    war_geprueft = a["status"] in GEPRUEFT
    if a["status"] != neu or a["pruefer"] or a["geprueft"]:
        fall.aendern("behauptung", behauptung_id, status=neu, pruefer="", geprueft=None)
        fall.log("behauptung zurueckgesetzt", behauptung_id, a["status"])
    return war_geprueft


def status_unzulaessig(art, status, kontext, behauptung):
    """Warum der Status der Behauptung nicht stehen darf, sonst None.

    Eine Stelle für die Nachführung nach Änderungen, das Laden einer Akte und `pruefe`:
    bekannter Status, Bewertung nur als Werturteil, Werturteil nur bei Bewertungen, belegt
    und gestützt höchstens bis zur Obergrenze."""
    if status not in BEHAUPTUNGS_STATUS:
        return "unbekannter Status %r" % status
    if art == "bewertung":
        return None if status == "werturteil" else "Eine Bewertung hat immer den Status werturteil"
    if status == "werturteil":
        return "Status werturteil gibt es nur bei Bewertungen"
    if status in ("belegt", "gestuetzt"):
        grenze, grund = kontext.obergrenze(behauptung)
        if RANG[status] > RANG[grenze]:
            return "Status %s liegt über der Obergrenze %s (%s)" % (status, grenze, grund)
    return None


def _nachziehen(fall):
    """Setzt jede Behauptung mit unzulässigem Status zurück; gibt [(ID, Grund)] zurück."""
    zurueckgesetzt = []
    geaendert = True
    while geaendert:
        geaendert = False
        kontext = Kontext(fall)
        for a in kontext.behauptungen.values():
            grund = status_unzulaessig(a["art"], a["status"], kontext, a)
            if grund:
                zuruecksetzen(fall, a["id"])
                zurueckgesetzt.append((a["id"], grund))
                geaendert = True
    return zurueckgesetzt


def obergrenzen_nachziehen(fall):
    """Setzt jede Behauptung zurück, deren Status unzulässig ist (nach Änderung von Quellen
    oder Prämissen, nach dem Laden einer Akte). Gibt die IDs zurück."""
    return [aid for aid, _grund in _nachziehen(fall)]


def lade_akte(wurzel, archivpfad, wer, herkunft):
    """Lädt eine gesicherte Akte und prüft sie sofort: Ein Archiv kann Status tragen, die die
    Belege nicht tragen. Gibt (Slug, [(ID, Grund)]) der zurückgesetzten Behauptungen zurück.
    Einziger Weg, eine Akte zu laden."""
    wurzel = Path(wurzel)
    slug = lade_fall(wurzel, archivpfad)
    try:
        fall = Fall.oeffnen(wurzel, slug, wer)
        try:
            fall.conn.execute("PRAGMA journal_mode=WAL")
            with fall.schreiben():
                fall.log("fall laden", slug, herkunft)
                zurueck = _nachziehen(fall)
        finally:
            fall.conn.close()
    except (sqlite3.Error, KeyError, ValueError, TypeError, OSError) as fehler:
        shutil.rmtree(str(wurzel / slug), ignore_errors=True)
        raise Fehler("Die Akte im Archiv ist beschädigt oder unvollständig (%s); nichts wurde geladen."
                     % fehler)
    return slug, zurueck


def nach_aenderung(fall, behauptung_id=None):
    """Nach jeder Änderung an Behauptung, Beleg oder Quelle; gibt Hinweiszeilen zurück."""
    meldungen = []
    if behauptung_id and zuruecksetzen(fall, behauptung_id):
        meldungen.append("hinweis: Prüfung zurückgesetzt")
    for abgesenkt in obergrenzen_nachziehen(fall):
        meldungen.append("hinweis: Prüfung zurückgesetzt: %s (Obergrenze gesunken)" % abgesenkt)
    return meldungen


def nach_beleg_aenderung(fall, beleg_id):
    """Nach Änderung eines Belegs: jede geprüfte Behauptung, die ihn nutzt, wird
    zurückgesetzt (sie wurde gegen die alte Fassung geprüft); danach greift die
    Obergrenzen-Nachführung. Gibt Hinweiszeilen zurück."""
    meldungen = []
    for art in ("pro", "contra"):
        for behauptung_id, belege in fall.verknuepfungen(art).items():
            if beleg_id in belege and zuruecksetzen(fall, behauptung_id):
                meldungen.append("hinweis: Prüfung zurückgesetzt: %s (Beleg %s geändert)"
                                 % (behauptung_id, beleg_id))
    for abgesenkt in obergrenzen_nachziehen(fall):
        meldungen.append("hinweis: Prüfung zurückgesetzt: %s (Obergrenze gesunken)" % abgesenkt)
    return meldungen


# ===========================================================================
# Integritätsprüfung
# ===========================================================================

def _problem(stufe, art, objekt, text):
    return {"stufe": stufe, "art": art, "objekt": objekt, "text": text}


def _zitate(k):
    return [_problem("sperre", "ZITAT", b["id"],
                     "Zitat aus %s ist im gespeicherten Text nicht mehr auffindbar" % b["quelle"])
            for b in k.belege.values() if not k.zitat_ok(b)]


def _unbelegt(k):
    probleme = []
    for a in k.behauptungen.values():
        if a["art"] in ("tatsache", "verdacht") and not k.pro.get(a["id"]):
            probleme.append(_problem("sperre", "UNBELEGT", a["id"], "%s ohne Beleg (pro)" % a["art"]))
        elif a["art"] in ("schlussfolgerung", "bewertung") and not k.aus.get(a["id"]):
            probleme.append(_problem("sperre", "UNBELEGT", a["id"],
                                     "%s ohne Prämissen (--aus)" % a["art"]))
    return probleme


def _status(k):
    probleme = []
    for a in k.behauptungen.values():
        grund = status_unzulaessig(a["art"], a["status"], k, a)
        if grund:
            probleme.append(_problem("sperre", "STATUS", a["id"], grund))
    return probleme


def _ungeprueft(k):
    return [_problem("sperre", "UNGEPRUEFT", a["id"], "Status ungeprueft; Prüfung mit behauptung pruefen")
            for a in k.behauptungen.values() if a["status"] == "ungeprueft"]


def _widerspruch(k):
    return [_problem("sperre", "WIDERSPRUCH", a["id"],
                     "Gegenbeleg %s ohne Klärung, Status %s" % (", ".join(k.contra[a["id"]]), a["status"]))
            for a in k.behauptungen.values()
            if k.contra.get(a["id"]) and not a["klaerung"].strip()
            and a["status"] not in ("strittig", "widerlegt")]


def _quelle_unbewertet(k):
    probleme = []
    belegte = {b["quelle"] for b in k.belege.values()}
    for quelle in k.quellen.values():
        if quelle["id"] in belegte and (quelle["typ"] == "unbekannt" or not quelle["zuverlaessigkeit"]):
            probleme.append(_problem("sperre", "QUELLE_UNBEWERTET", quelle["id"],
                                     "mit Beleg zitiert, aber Typ (%s) oder Zuverlässigkeit (%s) nicht bewertet"
                                     % (quelle["typ"], quelle["zuverlaessigkeit"] or "fehlt")))
    return probleme


def _betroffene(k, nur_personen=True):
    """{Akteur-ID: [Behauptungs-IDs]} für Akteure in `betrifft`."""
    ergebnis = {}
    for aid, akteure in k.betrifft.items():
        for pid in akteure:
            if not nur_personen or k.akteure[pid]["art"] == "person":
                ergebnis.setdefault(pid, []).append(aid)
    return ergebnis


def _kategorie(k):
    return [_problem("sperre", "KATEGORIE", pid,
                     "%s: Kategorie unbekannt (betrifft %s)" % (k.akteure[pid]["name"], ", ".join(aids)))
            for pid, aids in _betroffene(k).items() if k.akteure[pid]["kategorie"] == "unbekannt"]


def _suchen_contra(k):
    """Hypothesen-IDs mit mindestens einer Gegen-Suche (direkt oder über eine Frage)."""
    fragen = {f["id"]: f for f in k.fall.alle("frage")}
    hypothesen = set()
    for s in k.fall.alle("suche", "WHERE richtung = 'contra'"):
        if s["hypothese"]:
            hypothesen.add(s["hypothese"])
        if s["frage"] and fragen[s["frage"]]["hypothese"]:
            hypothesen.add(fragen[s["frage"]]["hypothese"])
    return hypothesen


def _gegenrecherche(k):
    mit_contra = _suchen_contra(k)
    sperren, hinweise = [], []
    for h in k.fall.alle("hypothese"):
        if h["id"] in mit_contra:
            continue
        if h["status"] != "offen":
            sperren.append(_problem("sperre", "GEGENRECHERCHE", h["id"],
                                    "Status %s ohne Gegen-Suche (suche notieren --richtung contra)" % h["status"]))
        else:
            hinweise.append(_problem("hinweis", "GEGENRECHERCHE", h["id"],
                                     "noch keine Gegen-Suche (suche notieren --richtung contra)"))
    return sperren, hinweise


def _stellungnahme(k):
    konfrontationen = k.fall.alle("konfrontation")
    zu = k.fall.verknuepfungen("konfrontation_zu")
    erledigt = {(kf["akteur"], a) for kf in konfrontationen
                if kf["status"] in ("beantwortet", "keine_antwort") for a in zu.get(kf["id"], [])}
    probleme = []
    for a in k.behauptungen.values():
        if not a["belastend"] or a["status"] == "widerlegt":
            continue
        for pid in k.betrifft.get(a["id"], []):
            if (pid, a["id"]) not in erledigt:
                probleme.append(_problem("veroeffentlichung", "STELLUNGNAHME", "%s/%s" % (a["id"], pid),
                                         "belastende Behauptung über %s ohne beantwortete Konfrontation"
                                         % k.akteure[pid]["name"]))
    return probleme


def _betroffene_fehlen(k):
    return [_problem("veroeffentlichung", "BETROFFENE", a["id"],
                     "belastende Behauptung ohne --betrifft: Wer ist betroffen?")
            for a in k.behauptungen.values()
            if a["belastend"] and a["status"] != "widerlegt" and not k.betrifft.get(a["id"])]


def _privatperson(k):
    return [_problem("veroeffentlichung", "PRIVATPERSON", "%s/%s" % (aid, pid),
                     "betrifft Privatperson %s" % k.akteure[pid]["name"])
            for aid, akteure in k.betrifft.items() for pid in akteure
            if k.akteure[pid]["art"] == "person" and k.akteure[pid]["kategorie"] == "privat"]


def _identitaet(k):
    return [_problem("veroeffentlichung", "IDENTITAET", pid,
                     "%s: keine Kennung (betrifft %s)" % (k.akteure[pid]["name"], ", ".join(aids)))
            for pid, aids in _betroffene(k).items() if not zu_dict(k.akteure[pid]["kennungen"])]


def _abhaengig(k):
    probleme = []
    for a in k.behauptungen.values():
        pro = k.belege_von(k.pro.get(a["id"], []))
        if a["status"] in ("belegt", "gestuetzt") and pro and len(k.gruppen_der(pro)) == 1:
            probleme.append(_problem("hinweis", "ABHAENGIG", a["id"],
                                     "alle Belege aus einer Quellengruppe (%s)"
                                     % ", ".join(sorted({b["quelle"] for b in pro}))))
    return probleme


def _fragen_offen(k):
    return [_problem("hinweis", "FRAGE_OFFEN", f["id"], "Frage noch %s" % f["status"])
            for f in k.fall.alle("frage")
            if f["status"] in ("offen", "in_arbeit") and not f["mensch"]]


def pruefe(fall):
    """Alle Probleme in der Ausgabereihenfolge (Sperren, Vor Veröffentlichung, Hinweise)."""
    k = Kontext(fall)
    sperren_h2, hinweise_h1 = _gegenrecherche(k)
    return (_zitate(k) + _status(k) + _unbelegt(k) + _ungeprueft(k) + _widerspruch(k)
            + _quelle_unbewertet(k) + _kategorie(k) + sperren_h2
            + _stellungnahme(k) + _betroffene_fehlen(k) + _privatperson(k) + _identitaet(k)
            + _abhaengig(k) + hinweise_h1 + _fragen_offen(k))


def formatiere_problem(p):
    return "%s %s %s: %s" % (STUFE_ANZEIGE[p["stufe"]], p["art"], p["objekt"], p["text"])


# ===========================================================================
# Export
# ===========================================================================

def _teil(zeile, *spalten):
    return {s: zeile[s] for s in spalten}


def export_daten(fall):
    """Das Austauschformat für Dossier-Renderer (Schema 1)."""
    k = Kontext(fall)
    meta = fall.meta()
    verk = {art: fall.verknuepfungen(art) for art in
            ("akteur_beleg", "beziehung_beleg", "ereignis_beleg", "ereignis_akteur",
             "konfrontation_zu")}
    return {
        "schema": 1,
        "fall": dict({s: meta.get(s, "") for s in ("slug", "titel", "auftrag", "interesse",
                                                   "zusammenfassung", "erstellt")}, stand=jetzt()),
        "hypothesen": [dict(_teil(h, "id", "text", "status", "vermerk"),
                            prueft=zu_liste(h["prueft"]), widerlegt=zu_liste(h["widerlegt"]))
                       for h in fall.alle("hypothese")],
        "fragen": [dict(_teil(f, "id", "text", "hypothese", "plan", "status", "ergebnis"),
                        mensch=bool(f["mensch"])) for f in fall.alle("frage")],
        "suchen": [_teil(s, "id", "frage", "hypothese", "anfrage", "richtung", "treffer",
                         "notiz", "zeit", "wer") for s in fall.alle("suche")],
        "quellen": [_export_quelle(x) for x in k.quellen.values()],
        "belege": [dict(_teil(b, "id", "quelle", "zitat", "stelle", "aussage", "frage", "wer", "zeit"),
                        direkt=bool(b["direkt"]), zitat_ok=k.zitat_ok(b)) for b in k.belege.values()],
        "behauptungen": [_export_behauptung(k, a) for a in k.behauptungen.values()],
        "akteure": [dict(_teil(a, "id", "art", "name", "kategorie", "notiz"),
                         kennungen=zu_dict(a["kennungen"]), belege=verk["akteur_beleg"].get(a["id"], []))
                    for a in k.akteure.values()],
        "beziehungen": [dict(_teil(r, "id", "von", "zu", "art", "von_datum", "bis_datum"),
                             belege=verk["beziehung_beleg"].get(r["id"], []))
                        for r in fall.alle("beziehung")],
        "ereignisse": [dict(_teil(e, "id", "datum", "text"), belege=verk["ereignis_beleg"].get(e["id"], []),
                            akteure=verk["ereignis_akteur"].get(e["id"], []))
                       for e in fall.alle("ereignis")],
        "konfrontationen": [dict(_teil(c, "id", "akteur", "frage", "status", "gesendet_am", "frist",
                                       "antwort", "antwort_quelle", "vermerk"),
                                 zu=verk["konfrontation_zu"].get(c["id"], []))
                            for c in fall.alle("konfrontation")],
        "probleme": pruefe(fall),
    }


def _export_quelle(x):
    daten = _teil(x, "id", "url", "titel", "herausgeber", "autor", "datum", "abgerufen", "sha256",
                  "typ", "zuverlaessigkeit", "ursprung", "interesse", "archiv_url", "art")
    daten["zeichen"] = int(x["zeichen"])
    return daten


def _export_behauptung(k, a):
    aid = a["id"]
    grenze, grund = k.obergrenze(a)
    daten = _teil(a, "id", "text", "art", "hypothese", "status", "vermerk", "pruefer", "geprueft",
                  "klaerung")
    daten.update(pro=k.pro.get(aid, []), contra=k.contra.get(aid, []), aus=k.aus.get(aid, []),
                 betrifft=k.betrifft.get(aid, []), belastend=bool(a["belastend"]),
                 zuschreibung=bool(a["zuschreibung"]), obergrenze=grenze, obergrenze_grund=grund)
    return daten
