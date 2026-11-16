"""Kommandozeile: `python3 -m recherche [--fall SLUG] [--wer NAME] <bereich> <aktion> ...`."""

import argparse
import importlib
import json
import mimetypes
import os
import re
import sys
from pathlib import Path

from . import bewertung
from . import quellen as q
from .store import (BEHAUPTUNGS_ARTEN, FRAGEN_STATUS, HYPOTHESEN_STATUS, KATEGORIEN,
                    QUELLEN_TYPEN, RICHTUNGEN, ZUVERLAESSIGKEIT, Fall, Fehler, Nutzungsfehler,
                    aktiver_slug, faelle_liste, faelle_wurzel, jetzt, namensschluessel,
                    pflicht, sichere_fall,
                    pruefe_datum, teile_liste, zu_dict, zu_liste)

QUELLEN_ID = re.compile(r"[Qq]\d+")
LESEN_STANDARD = 2500
FENSTER_STANDARD = 3000
FENSTER_MAX = 12000
TREFFER_MAX = 8
KONTEXT = 250


# ===========================================================================
# Gemeinsame Helfer
# ===========================================================================

def _wer(args):
    return args.wer or os.environ.get("RECHERCHE_WER") or "unbekannt"


def _oeffne(args):
    wurzel = faelle_wurzel()
    return Fall.oeffnen(wurzel, aktiver_slug(wurzel, args.fall), _wer(args))


def _zeigen(*zeilen):
    print("\n".join(zeilen))


def _kurz(text, laenge=100):
    text = " ".join((text or "").split())
    return text if len(text) <= laenge else text[:laenge - 1] + "…"


def _strich(wert):
    return wert if wert not in (None, "") else "-"


def _ja_nein(wert):
    return "ja" if wert else "nein"


def _ids(fall, werte, erlaubt):
    """Mehrfach oder kommagetrennt angegebene IDs prüfen."""
    return fall.hole_liste(",".join(werte or []), erlaubt)


def _hypothese_optional(fall, wert):
    return fall.hole(wert, "H")["id"] if wert else None


def _frage_optional(fall, wert):
    return fall.hole(wert, "F")["id"] if wert else None


def _kennungen(paare):
    ergebnis = {}
    for paar in paare or []:
        schluessel, trenner, wert = paar.partition("=")
        if not trenner or not schluessel.strip():
            raise Fehler("Kennung muss die Form k=v haben: %s" % paar)
        ergebnis[schluessel.strip()] = wert.strip()
    return ergebnis


def _json(wert):
    return json.dumps(wert, ensure_ascii=False)


# ===========================================================================
# fall
# ===========================================================================

def fall_neu(args):
    wurzel = faelle_wurzel()
    titel = pflicht(args.titel, "--titel")
    auftrag = pflicht(args.auftrag, "--auftrag")
    fall = Fall.neu(wurzel, args.slug, _wer(args), titel, auftrag, args.interesse or "")
    _zeigen("angelegt: " + args.slug, "pfad: %s" % fall.verzeichnis)


def fall_setzen(args):
    fall = _oeffne(args)
    werte = {s: getattr(args, s) for s in ("titel", "auftrag", "interesse", "zusammenfassung")
             if getattr(args, s) is not None}
    if not werte:
        raise Nutzungsfehler("nichts zu ändern: --titel, --auftrag, --interesse oder --zusammenfassung angeben")
    for schluessel in ("titel", "auftrag"):
        if schluessel in werte:
            werte[schluessel] = pflicht(werte[schluessel], "--" + schluessel)
    with fall.schreiben():
        fall.setze_meta(**werte)
        fall.log("fall setzen", fall.slug, ", ".join(werte))
    _zeigen("geändert: " + ", ".join(werte))


def fall_liste(args):
    wurzel = faelle_wurzel()
    slugs = faelle_liste(wurzel)
    if not slugs:
        _zeigen("keine Fälle vorhanden (Verzeichnis: %s)" % wurzel)
    for slug in slugs:
        _zeigen("%s | %s" % (slug, Fall.oeffnen(wurzel, slug, "-").meta().get("titel", "")))


def fall_sichern(args):
    fall = _oeffne(args)
    pfad, anzahl, groesse = sichere_fall(fall, args.ziel or faelle_wurzel())
    _zeigen("gesichert: %s (%d Dateien, %d KB)" % (pfad, anzahl, (groesse + 1023) // 1024))


def fall_laden(args):
    slug, zurueck = bewertung.lade_akte(faelle_wurzel(), args.pfad, _wer(args), str(args.pfad))
    _zeigen("geladen: " + slug,
            *("hinweis: Prüfung zurückgesetzt: %s (%s)" % (aid, grund) for aid, grund in zurueck))


OBJEKT_TABELLEN = (("Hypothesen", "hypothese"), ("Fragen", "frage"), ("Suchen", "suche"),
                   ("Quellen", "quelle"), ("Belege", "beleg"), ("Behauptungen", "behauptung"),
                   ("Akteure", "akteur"), ("Beziehungen", "beziehung"),
                   ("Ereignisse", "ereignis"), ("Konfrontationen", "konfrontation"))


def fall_zeigen(args):
    fall = _oeffne(args)
    meta = fall.meta()
    zeilen = ["Fall %s: %s" % (fall.slug, meta["titel"]), "Auftrag: " + _kurz(meta["auftrag"], 160)]
    if meta["interesse"]:
        zeilen.append("Interesse: " + _kurz(meta["interesse"], 160))
    if meta["zusammenfassung"]:
        zeilen.append("Zusammenfassung: " + _kurz(meta["zusammenfassung"], 160))
    zeilen.append("Objekte: " + " | ".join("%s %d" % (n, fall.anzahl(t)) for n, t in OBJEKT_TABELLEN))
    zeilen.append(_status_zeile(fall))
    zeilen += _hypothesen_zeilen(fall)
    zeilen += _offene_fragen(fall)
    stufen = [p["stufe"] for p in bewertung.pruefe(fall)]
    zeilen.append("Probleme: Sperren %d | vor Veröffentlichung %d | Hinweise %d"
                  % tuple(stufen.count(s) for s in bewertung.STUFEN))
    _zeigen(*zeilen)


def _status_zeile(fall):
    stati = [a["status"] for a in fall.alle("behauptung")]
    teile = ["%s %d" % (s, stati.count(s)) for s in sorted(set(stati))]
    return "Behauptungen nach Status: " + (" | ".join(teile) or "keine")


def _begrenzt(zeilen, maximal):
    """Höchstens `maximal` Zeilen, der Rest als Sammelzeile."""
    if len(zeilen) <= maximal:
        return zeilen
    return zeilen[:maximal] + ["  … und %d weitere" % (len(zeilen) - maximal)]


def _hypothesen_zeilen(fall):
    hypothesen = fall.alle("hypothese")
    if not hypothesen:
        return ["Hypothesen: keine"]
    zeilen = ["  %s [%s] %s" % (h["id"], h["status"], _kurz(h["text"], 160)) for h in hypothesen]
    return ["Hypothesen:"] + _begrenzt(zeilen, 12)


def _offene_fragen(fall):
    offen = [f for f in fall.alle("frage") if f["status"] in ("offen", "in_arbeit")]
    if not offen:
        return ["Offene Fragen: keine"]
    zeilen = ["  %s %s%s" % (f["id"], _kurz(f["text"], 160), " (Mensch)" if f["mensch"] else "")
              for f in offen]
    return ["Offene Fragen: %d" % len(offen)] + _begrenzt(zeilen, 15)


# ===========================================================================
# hypothese, frage, suche
# ===========================================================================

def hypothese_neu(args):
    fall = _oeffne(args)
    text = pflicht(args.text, "--text")
    with fall.schreiben():
        hid = fall.erzeuge("H", "hypothese neu", text, text=text, prueft=_json(args.prueft or []),
                           widerlegt=_json(args.widerlegt or []))
    _zeigen("angelegt: " + hid)


def hypothese_status(args):
    fall = _oeffne(args)
    vermerk = pflicht(args.vermerk, "--vermerk")
    with fall.schreiben():
        h = fall.hole(args.id, "H")
        fall.aendern("hypothese", h["id"], status=args.status, vermerk=vermerk)
        fall.log("hypothese status", h["id"], "%s: %s" % (args.status, vermerk))
    _zeigen("%s: status %s" % (h["id"], args.status))


def hypothese_liste(args):
    for h in _oeffne(args).alle("hypothese"):
        zeilen = ["%s [%s] %s" % (h["id"], h["status"], h["text"])]
        zeilen += ["  prüft: " + eintrag for eintrag in zu_liste(h["prueft"])]
        zeilen += ["  widerlegt: " + eintrag for eintrag in zu_liste(h["widerlegt"])]
        if h["vermerk"]:
            zeilen.append("  vermerk: " + h["vermerk"])
        _zeigen(*zeilen)


def frage_liste(args):
    fall = _oeffne(args)
    hypothese = fall.hole(args.hypothese, "H")["id"] if args.hypothese else None
    for f in fall.alle("frage"):
        if (args.status and f["status"] != args.status) or (hypothese and f["hypothese"] != hypothese):
            continue
        zeilen = ["%s [%s] %s%s" % (f["id"], f["status"], f["text"], " (Mensch)" if f["mensch"] else "")]
        for name in ("hypothese", "plan", "ergebnis"):
            if f[name]:
                zeilen.append("  %s: %s" % (name, f[name]))
        _zeigen(*zeilen)


def frage_neu(args):
    fall = _oeffne(args)
    text = pflicht(args.text, "--text")
    with fall.schreiben():
        hypothese = _hypothese_optional(fall, args.hypothese)
        fid = fall.erzeuge("F", "frage neu", text, text=text, hypothese=hypothese,
                           plan=args.plan or "", mensch=int(args.mensch))
    _zeigen("angelegt: " + fid)


def frage_status(args):
    fall = _oeffne(args)
    with fall.schreiben():
        f = fall.hole(args.id, "F")
        werte = {"status": args.status}
        if args.ergebnis is not None:
            werte["ergebnis"] = args.ergebnis
        fall.aendern("frage", f["id"], **werte)
        fall.log("frage status", f["id"], args.status)
    _zeigen("%s: status %s" % (f["id"], args.status))


def suche_notieren(args):
    fall = _oeffne(args)
    anfrage = pflicht(args.anfrage, "--anfrage")
    if args.treffer is not None and args.treffer < 0:
        raise Fehler("--treffer darf nicht negativ sein")
    with fall.schreiben():
        frage = _frage_optional(fall, args.frage)
        hypothese = _hypothese_optional(fall, args.hypothese)
        sid = fall.erzeuge("S", "suche notieren", anfrage, frage=frage, hypothese=hypothese,
                           anfrage=anfrage, richtung=args.richtung, treffer=args.treffer,
                           notiz=args.notiz or "", zeit=jetzt(), wer=fall.wer)
    _zeigen("angelegt: " + sid)


# ===========================================================================
# quelle
# ===========================================================================

def _quelle_ausgeben(quelle_id, neu, zeile, hinweise=()):
    if not neu:
        _zeigen("bereits erfasst: " + quelle_id)
        return
    zeilen = ["angelegt: " + quelle_id,
              "titel: " + zeile["titel"],
              "herausgeber: %s | datum: %s | typ: %s" % (_strich(zeile["herausgeber"]),
                                                          _strich(zeile["datum"]), zeile["typ"]),
              "zeichen: %d | sha256: %s" % (zeile["zeichen"], zeile["sha256"][:12]),
              'lesen: python3 -m recherche quelle lesen %s --suche "<Begriff>"' % quelle_id]
    if zeile["zeichen"] < 200:
        zeilen.append("warnung: kaum Text extrahiert (JavaScript-Seite oder Bezahlschranke?)")
    if zeile["archiv_url"]:
        zeilen.append("archiv: " + zeile["archiv_url"])
    _zeigen(*zeilen, *hinweise)


def quelle_holen(args):
    fall = _oeffne(args)
    frage = _frage_optional(fall, args.frage)
    endgueltig, mime, charset, roh = q.hole_url(args.url)
    vorhanden = q.finde_duplikat(fall, q.sha256_von(roh))
    if vorhanden:
        _zeigen("bereits erfasst: " + vorhanden)
        return
    archiv_url, hinweise = "", []
    if args.archiv or args.sichern:
        archiv_url, hinweise = q.archiviere(endgueltig, args.sichern)
    quelle_id, neu, zeile = q.lege_quelle_an(
        fall, roh, "web", mime, charset or "", url=endgueltig, angefragt_url=args.url,
        typ=args.typ, archiv_url=archiv_url, frage=frage)
    _quelle_ausgeben(quelle_id, neu, zeile, hinweise)


def quelle_datei(args):
    fall = _oeffne(args)
    titel = pflicht(args.titel, "--titel")
    pfad = Path(args.pfad)
    try:
        if pfad.stat().st_size > q.MAX_BYTES:
            raise Fehler("Datei größer als 25 MB")
        roh = pfad.read_bytes()
    except OSError as fehler:
        raise Fehler("Datei nicht lesbar: %s" % fehler)
    mime = mimetypes.guess_type(pfad.name)[0] or ""
    quelle_id, neu, zeile = q.lege_quelle_an(fall, roh, "datei", mime, url=args.url or "",
                                             typ=args.typ, titel=titel, name=pfad.name)
    _quelle_ausgeben(quelle_id, neu, zeile)


def quelle_text(args):
    fall = _oeffne(args)
    titel = pflicht(args.titel, "--titel")
    roh = sys.stdin.buffer.read()
    if not roh.strip():
        raise Fehler("kein Text auf der Standardeingabe")
    quelle_id, neu, zeile = q.lege_quelle_an(fall, roh, "text", "text/plain; charset=utf-8",
                                             "utf-8", url=args.url or "", typ=args.typ, titel=titel)
    _quelle_ausgeben(quelle_id, neu, zeile)


def _quellenkopf(x):
    return "%s | %s | %s | %s | typ %s | %d Zeichen" % (
        x["id"], x["titel"], _strich(x["herausgeber"]), _strich(x["datum"]), x["typ"], x["zeichen"])


def quelle_lesen(args):
    fall = _oeffne(args)
    quelle = fall.hole(args.id, "Q")
    text = fall.lies_text(quelle["id"])
    zeilen = [_quellenkopf(quelle)]
    if args.suche:
        zeilen += _suchtreffer(text, args.suche)
    else:
        zeilen += _fenster(text, args)
    _zeigen(*zeilen)


def _bis_leerraum(text, position, richtung):
    """Rückt eine Fenstergrenze bis zum nächsten Leerraum, damit kein Wort zerschnitten wird.
    Höchstens 100 Zeichen, damit Texte ohne Leerraum nicht ganz ausgegeben werden."""
    schritt = 0
    if position <= 0 or position >= len(text) or text[position - 1].isspace() or text[position].isspace():
        return position  # schon an einer Wortgrenze
    if richtung < 0:
        while position > 0 and schritt < 100 and not text[position - 1].isspace():
            position -= 1
            schritt += 1
    else:
        while position < len(text) and schritt < 100 and not text[position].isspace():
            position += 1
            schritt += 1
    return position


def _suchfenster(text, treffer):
    """Kontextfenster der Treffer; überlappende oder aneinanderstoßende werden vereint."""
    fenster = []
    for t in treffer:
        start = _bis_leerraum(text, max(0, t.start() - KONTEXT), -1)
        ende = _bis_leerraum(text, min(len(text), t.end() + KONTEXT), 1)
        if fenster and start <= fenster[-1][1]:
            fenster[-1][1] = max(fenster[-1][1], ende)
        else:
            fenster.append([start, ende])
    return fenster


def _suchtreffer(text, begriff):
    treffer = list(re.finditer(re.escape(begriff), text, re.IGNORECASE))
    zeilen = []
    for start, ende in _suchfenster(text, treffer[:TREFFER_MAX]):
        zeilen += ["", "[Zeichen %d-%d]" % (start, ende), text[start:ende]]
    zeilen += ["", "%d Treffer" % len(treffer)]
    if len(treffer) > TREFFER_MAX:
        zeilen.append("(nur die ersten %d angezeigt)" % TREFFER_MAX)
    return zeilen


def _fenster(text, args):
    angegeben = args.ab is not None or args.laenge is not None
    start = max(0, args.ab or 0)
    laenge = min(args.laenge or FENSTER_STANDARD, FENSTER_MAX) if angegeben else LESEN_STANDARD
    ende = _bis_leerraum(text, min(len(text), start + laenge), 1)
    zeilen = ["", text[start:ende], "", "-- Zeichen %d bis %d von %d" % (start, ende, len(text))]
    if ende < len(text):
        zeilen[-1] += "; weiter mit --ab %d" % ende
    return zeilen


def quelle_setzen(args):
    fall = _oeffne(args)
    werte = {s: getattr(args, s) for s in ("typ", "titel", "herausgeber", "autor", "datum",
                                           "zuverlaessigkeit", "ursprung", "interesse")
             if getattr(args, s) is not None}
    if not werte:
        raise Nutzungsfehler("nichts zu ändern")
    with fall.schreiben():
        quelle = fall.hole(args.id, "Q")
        if "titel" in werte:
            werte["titel"] = pflicht(werte["titel"], "--titel")
        if werte.get("datum"):
            pruefe_datum(werte["datum"])
        if "ursprung" in werte:
            werte["ursprung"] = _ursprung(fall, quelle["id"], werte["ursprung"])
        fall.aendern("quelle", quelle["id"], **werte)
        fall.log("quelle setzen", quelle["id"], _json(werte))
        meldungen = []
        if set(werte) & {"typ", "zuverlaessigkeit", "ursprung"}:
            meldungen = bewertung.nach_aenderung(fall)
    _zeigen("geändert: %s (%s)" % (quelle["id"], ", ".join(werte)), *meldungen)


def _ursprung(fall, eigene_id, wert):
    """Ursprung: Quellen-ID (muss existieren) oder freier Text."""
    wert = wert.strip()
    if QUELLEN_ID.fullmatch(wert):
        ziel = fall.hole(wert, "Q")["id"]
        if ziel == eigene_id:
            raise Fehler("Eine Quelle kann nicht ihr eigener Ursprung sein")
        return ziel
    return wert


def quelle_zeigen(args):
    fall = _oeffne(args)
    kontext = bewertung.Kontext(fall)
    x = kontext.quellen[fall.hole(args.id, "Q")["id"]]
    gruppe = [i for i in kontext.quellen if kontext.gruppen[i] == kontext.gruppen[x["id"]]]
    belege = [b["id"] for b in kontext.belege.values() if b["quelle"] == x["id"]]
    felder = [("id", x["id"]), ("titel", x["titel"]), ("url", x["url"])]
    if x["angefragt_url"] != x["url"]:
        felder.append(("angefragt", x["angefragt_url"]))
    felder += [(name, x[name]) for name in ("herausgeber", "autor", "datum", "abgerufen", "typ",
                                            "zuverlaessigkeit", "ursprung", "interesse")]
    felder += [("archiv", x["archiv_url"]), ("art", x["art"]), ("zeichen", x["zeichen"]),
               ("sha256", x["sha256"]), ("gruppe", ", ".join(gruppe)), ("belege", ", ".join(belege))]
    _zeigen(*("%s: %s" % (name, _strich(wert)) for name, wert in felder))


def quelle_liste(args):
    fall = _oeffne(args)
    for x in fall.alle("quelle"):
        _zeigen("%s | typ %s | Zuverlässigkeit %s | %s | %s" % (
            x["id"], x["typ"], _strich(x["zuverlaessigkeit"]), _kurz(x["titel"], 70), _strich(x["datum"])))


# ===========================================================================
# beleg
# ===========================================================================

def beleg_neu(args):
    fall = _oeffne(args)
    zitat = pflicht(sys.stdin.read() if args.zitat == "-" else args.zitat, "--zitat")
    aussage = pflicht(args.aussage, "--aussage")
    with fall.schreiben():
        quelle = fall.hole(args.quelle, "Q")
        frage = _frage_optional(fall, args.frage)
        teile = q.pruefe_zitatform(zitat)
        text_norm, karte = q.normalisiere_mit_karte(fall.lies_text(quelle["id"]))
        gefunden = q.finde_teile(teile, text_norm)
        if gefunden is None:
            if q.finde_teile(teile, text_norm, max_spanne=None) is not None:
                raise Fehler("Zitatteile liegen mehr als %d Zeichen auseinander. "
                             "Für getrennte Stellen getrennte Belege anlegen." % q.MAX_ZITATSPANNE)
            raise Fehler(_zitat_nicht_gefunden(quelle["id"], teile, text_norm, karte))
        stelle = karte[gefunden]  # Position im gespeicherten Text, wie `quelle lesen` sie zählt
        bid = fall.erzeuge("B", "beleg neu", "%s: %s" % (quelle["id"], _kurz(zitat, 60)),
                           quelle=quelle["id"], zitat=zitat, stelle=stelle, aussage=aussage,
                           direkt=int(args.direkt), frage=frage, wer=fall.wer, zeit=jetzt())
    _zeigen("angelegt: " + bid, "quelle: %s | stelle: %d" % (quelle["id"], stelle),
            "kontext: python3 -m recherche quelle lesen %s --ab %d --laenge 1200"
            % (quelle["id"], max(0, stelle - 300)))


def beleg_setzen(args):
    fall = _oeffne(args)
    if args.direkt is None and args.aussage is None:
        raise Nutzungsfehler("nichts zu ändern: --direkt, --nicht-direkt oder --aussage angeben "
                             "(das Zitat selbst ist unveränderlich; ein anderes Zitat ist ein neuer Beleg)")
    with fall.schreiben():
        b = fall.hole(args.id, "B")
        werte = {}
        if args.direkt is not None and int(args.direkt) != b["direkt"]:
            werte["direkt"] = int(args.direkt)
        if args.aussage is not None and pflicht(args.aussage, "--aussage") != b["aussage"]:
            werte["aussage"] = args.aussage.strip()
        meldungen = []
        if werte:
            fall.aendern("beleg", b["id"], **werte)
            fall.log("beleg setzen", b["id"], _json(werte))
            meldungen = bewertung.nach_beleg_aenderung(fall, b["id"])
    _zeigen("geändert: %s (%s)" % (b["id"], ", ".join(werte) or "nichts, Werte waren schon so"), *meldungen)


def _zitat_nicht_gefunden(quelle_id, teile, text_norm, karte):
    gefunden, ausschnitt = q.aehnlichste_stelle(" ".join(teile), text_norm)
    stelle = karte[gefunden] if karte else 0
    return ("Zitat nicht im Text von %s gefunden.\n"
            'ähnlichste Stelle (Zeichen %d): "%s"\n'
            "Wörtlich aus `quelle lesen` zitieren; Auslassungen mit […] kennzeichnen."
            % (quelle_id, stelle, ausschnitt))


def beleg_zeigen(args):
    fall = _oeffne(args)
    kontext = bewertung.Kontext(fall)
    b = fall.hole(args.id, "B")
    quelle = kontext.quellen[b["quelle"]]
    verwendet = ["%s (%s)" % (a, rolle) for rolle, karte in (("pro", kontext.pro), ("contra", kontext.contra))
                 for a, belege in karte.items() if b["id"] in belege]
    _zeigen("%s | Quelle %s | %s" % (b["id"], quelle["id"], quelle["titel"]),
            'Zitat: "%s"' % b["zitat"],
            "Aussage: " + b["aussage"],
            "direkt: %s | Stelle: %d | Zitat im Text: %s" % (_ja_nein(b["direkt"]), b["stelle"],
                                                            _ja_nein(kontext.zitat_ok(b))),
            "erfasst: %s von %s" % (b["zeit"], b["wer"]),
            "verwendet in: " + (", ".join(verwendet) or "-"))


# ===========================================================================
# behauptung
# ===========================================================================

def _pruefe_struktur(art, aus):
    if art in ("schlussfolgerung", "bewertung") and not aus:
        raise Fehler("%s braucht --aus (die Behauptungen, auf denen sie beruht)" % art)
    if art not in ("schlussfolgerung", "bewertung") and aus:
        raise Fehler("--aus gibt es nur bei schlussfolgerung und bewertung")


def _pruefe_gegensaetze(pro, contra):
    doppelt = sorted(set(pro) & set(contra))
    if doppelt:
        raise Fehler("Beleg kann nicht zugleich pro und contra sein: %s" % ", ".join(doppelt))


def behauptung_neu(args):
    fall = _oeffne(args)
    text = pflicht(args.text, "--text")
    with fall.schreiben():
        pro = fall.hole_liste(args.pro, "B")
        contra = fall.hole_liste(args.contra, "B")
        aus = fall.hole_liste(args.aus, "A")
        betrifft = fall.hole_liste(args.betrifft, "PO")
        _pruefe_gegensaetze(pro, contra)
        _pruefe_struktur(args.art, aus)
        hypothese = _hypothese_optional(fall, args.hypothese)
        status = "werturteil" if args.art == "bewertung" else "ungeprueft"
        aid = fall.erzeuge("A", "behauptung neu", "%s: %s" % (args.art, _kurz(text, 60)),
                           text=text, art=args.art, hypothese=hypothese, status=status,
                           belastend=int(args.belastend), zuschreibung=int(args.zuschreibung))
        for art, ziele in (("pro", pro), ("contra", contra), ("aus", aus), ("betrifft", betrifft)):
            fall.verknuepfe(art, aid, ziele)
    _zeigen("angelegt: %s | status %s" % (aid, status))


def behauptung_beleg(args):
    fall = _oeffne(args)
    with fall.schreiben():
        a = fall.hole(args.id, "A")
        ohne = fall.hole_liste(args.ohne, "B")
        pro = fall.hole_liste(args.pro, "B")
        contra = fall.hole_liste(args.contra, "B")
        if not (pro or contra or ohne):
            raise Nutzungsfehler("--pro, --contra oder --ohne angeben")
        entfernt = _loese_belege(fall, a["id"], ohne)
        _pruefe_gegensaetze(pro + fall.verknuepfungen("pro").get(a["id"], []), contra)
        _pruefe_gegensaetze(pro, contra + fall.verknuepfungen("contra").get(a["id"], []))
        neu_pro = fall.verknuepfe("pro", a["id"], pro)
        neu_contra = fall.verknuepfe("contra", a["id"], contra)
        meldungen = []
        if entfernt or neu_pro or neu_contra:
            fall.log("behauptung beleg", a["id"], "pro +%s; contra +%s; ohne %s" % (neu_pro, neu_contra, entfernt))
            meldungen = bewertung.nach_aenderung(fall, a["id"])
    _zeigen("geändert: %s (pro +%d, contra +%d, entfernt %d)" % (a["id"], len(neu_pro), len(neu_contra), len(entfernt)),
            *meldungen)


def _loese_belege(fall, behauptung_id, beleg_ids):
    """Entfernt Belegverknüpfungen (pro oder contra); der Beleg selbst bleibt."""
    for beleg_id in beleg_ids:
        geloest = [fall.entferne_verknuepfung(art, behauptung_id, beleg_id) for art in ("pro", "contra")]
        if not any(geloest):
            raise Fehler("%s ist nicht mit %s verknüpft" % (beleg_id, behauptung_id))
    return beleg_ids


def behauptung_setzen(args):
    fall = _oeffne(args)
    angegeben = [args.text, args.art, args.aus, args.betrifft, args.belastend, args.zuschreibung,
                 args.klaerung]
    if all(wert is None for wert in angegeben):
        raise Nutzungsfehler("nichts zu ändern")
    with fall.schreiben():
        a = fall.hole(args.id, "A")
        werte, zuruecksetzen = _behauptung_aenderungen(fall, a, args)
        if werte:
            fall.aendern("behauptung", a["id"], **werte)
            fall.log("behauptung setzen", a["id"], ", ".join(sorted(werte)))
        meldungen = bewertung.nach_aenderung(fall, a["id"]) if zuruecksetzen else []
    _zeigen("geändert: " + a["id"], *meldungen)


def _behauptung_aenderungen(fall, a, args):
    """Wendet Verknüpfungsänderungen an; gibt (Spaltenwerte, Prüfung zurücksetzen?) zurück."""
    werte, zuruecksetzen = {}, False
    if args.text is not None:
        werte["text"] = pflicht(args.text, "--text")
    if args.art is not None:
        werte["art"] = args.art
    if args.belastend is not None:
        werte["belastend"] = int(args.belastend)
    if args.zuschreibung is not None:
        werte["zuschreibung"] = int(args.zuschreibung)
    if args.klaerung is not None:
        werte["klaerung"] = args.klaerung.strip()
    werte = {s: w for s, w in werte.items() if w != a[s]}
    zuruecksetzen = bool(set(werte) & {"text", "art", "zuschreibung"})
    aus_alt = fall.verknuepfungen("aus").get(a["id"], [])
    aus_neu = fall.hole_liste(args.aus, "A") if args.aus is not None else aus_alt
    if a["id"] in aus_neu:
        raise Fehler("Eine Behauptung kann nicht auf sich selbst beruhen")
    _pruefe_struktur(werte.get("art", a["art"]), aus_neu)
    if sorted(aus_neu) != sorted(aus_alt):
        fall.ersetze_verknuepfung("aus", a["id"], aus_neu)
        zuruecksetzen = True
    if args.betrifft is not None:
        fall.ersetze_verknuepfung("betrifft", a["id"], fall.hole_liste(args.betrifft, "PO"))
    return werte, zuruecksetzen


def behauptung_pruefen(args):
    fall = _oeffne(args)
    vermerk = pflicht(args.vermerk, "--vermerk")
    pruefer = pflicht(args.pruefer, "--pruefer")
    with fall.schreiben():
        a = fall.hole(args.id, "A")
        bewertung.pruefe_status(fall, a["id"], args.status, vermerk, pruefer)
        meldungen = bewertung.nach_aenderung(fall)
    _zeigen("%s: status %s (geprüft von %s)" % (a["id"], args.status, pruefer), *meldungen)


def _beleg_zeile(kontext, beleg_id):
    b = kontext.belege[beleg_id]
    quelle = kontext.quellen[b["quelle"]]
    return ['  %s | %s "%s" | typ %s | Zuverlässigkeit %s | Ursprung %s | Stelle %d%s'
            % (b["id"], quelle["id"], quelle["titel"], quelle["typ"], _strich(quelle["zuverlaessigkeit"]),
               _strich(quelle["ursprung"]), b["stelle"], " | direkt" if b["direkt"] else ""),
            '    "%s"' % b["zitat"]]


def behauptung_zeigen(args):
    fall = _oeffne(args)
    kontext = bewertung.Kontext(fall)
    a = kontext.behauptungen[fall.hole(args.id, "A")["id"]]
    grenze, grund = kontext.obergrenze(a)
    zeilen = ["%s | %s | status %s" % (a["id"], a["art"], a["status"]),
              "Text: " + a["text"],
              "Obergrenze: %s (%s)" % (grenze, grund),
              "belastend: %s | Zuschreibung: %s | Hypothese: %s" % (
                  _ja_nein(a["belastend"]), _ja_nein(a["zuschreibung"]), _strich(a["hypothese"]))]
    for beschriftung, karte in (("Pro", kontext.pro), ("Contra", kontext.contra)):
        zeilen.append("%s:%s" % (beschriftung, "" if karte.get(a["id"]) else " -"))
        for beleg_id in karte.get(a["id"], []):
            zeilen += _beleg_zeile(kontext, beleg_id)
    if kontext.aus.get(a["id"]):
        zeilen.append("Aus: " + ", ".join("%s (%s)" % (i, kontext.behauptungen[i]["status"])
                                          for i in kontext.aus[a["id"]]))
    if kontext.betrifft.get(a["id"]):
        zeilen.append("Betrifft: " + ", ".join("%s (%s)" % (i, kontext.akteure[i]["name"])
                                               for i in kontext.betrifft[a["id"]]))
    if a["geprueft"]:
        zeilen.append("Prüfung: %s von %s, %s" % (a["geprueft"], a["pruefer"], a["vermerk"]))
    if a["klaerung"]:
        zeilen.append("Klärung: " + a["klaerung"])
    _zeigen(*zeilen)


def behauptung_liste(args):
    fall = _oeffne(args)
    hypothese = fall.hole(args.hypothese, "H")["id"] if args.hypothese else None
    for a in fall.alle("behauptung"):
        if (args.status and a["status"] != args.status) or (hypothese and a["hypothese"] != hypothese):
            continue
        marken = "".join((" | belastend" if a["belastend"] else "",
                          " | Zuschreibung" if a["zuschreibung"] else ""))
        _zeigen("%s | %s | %s%s | %s" % (a["id"], a["art"], a["status"], marken, _kurz(a["text"])))


# ===========================================================================
# akteur, beziehung, ereignis, konfrontation
# ===========================================================================

def akteur_neu(args):
    fall = _oeffne(args)
    name = pflicht(args.name, "--name")
    kategorie = args.kategorie or ("organisation" if args.art == "organisation" else "unbekannt")
    with fall.schreiben():
        if not args.trotzdem:
            _pruefe_namensdublette(fall, name)
        belege = _ids(fall, args.beleg, "B")
        pid = fall.erzeuge("P" if args.art == "person" else "O", "akteur neu", name, art=args.art,
                           name=name, kategorie=kategorie, kennungen=_json(_kennungen(args.kennung)),
                           notiz=args.notiz or "")
        fall.verknuepfe("akteur_beleg", pid, belege)
    _zeigen("angelegt: " + pid)


def _pruefe_namensdublette(fall, name):
    for a in fall.alle("akteur"):
        if namensschluessel(a["name"]) == namensschluessel(name):
            raise Fehler("Akteur mit diesem Namen existiert bereits: %s. "
                         "Bei einer anderen Person gleichen Namens --trotzdem angeben." % a["id"])


def akteur_setzen(args):
    fall = _oeffne(args)
    with fall.schreiben():
        a = fall.hole(args.id, "PO")
        werte = {}
        if args.kategorie is not None:
            werte["kategorie"] = args.kategorie
        if args.notiz is not None:
            werte["notiz"] = args.notiz
        if args.kennung:
            kennungen = zu_dict(a["kennungen"])
            kennungen.update(_kennungen(args.kennung))
            werte["kennungen"] = _json(kennungen)
        belege = _ids(fall, args.beleg, "B")
        if not werte and not belege:
            raise Nutzungsfehler("nichts zu ändern")
        if werte:
            fall.aendern("akteur", a["id"], **werte)
        fall.verknuepfe("akteur_beleg", a["id"], belege)
        fall.log("akteur setzen", a["id"], ", ".join(list(werte) + (["beleg"] if belege else [])))
    _zeigen("geändert: " + a["id"])


def akteur_liste(args):
    for a in _oeffne(args).alle("akteur"):
        _zeigen("%s | %s | %s | %s" % (a["id"], a["art"], a["name"], a["kategorie"]))


def beziehung_neu(args):
    fall = _oeffne(args)
    art = pflicht(args.art, "--art")
    von_datum = pruefe_datum(args.von_datum, "--von-datum") if args.von_datum else ""
    bis_datum = pruefe_datum(args.bis_datum, "--bis-datum") if args.bis_datum else ""
    laenge = min(len(von_datum), len(bis_datum))
    if laenge and von_datum[:laenge] > bis_datum[:laenge]:
        raise Fehler("--von-datum liegt nach --bis-datum")
    with fall.schreiben():
        von = fall.hole(args.von, "PO")["id"]
        zu = fall.hole(args.zu, "PO")["id"]
        belege = fall.hole_liste(args.beleg, "B")
        if not belege:
            raise Fehler("--beleg: mindestens ein Beleg nötig")
        rid = fall.erzeuge("R", "beziehung neu", "%s -%s-> %s" % (von, art, zu), von=von, zu=zu,
                           art=art, von_datum=von_datum, bis_datum=bis_datum)
        fall.verknuepfe("beziehung_beleg", rid, belege)
    _zeigen("angelegt: " + rid)


def ereignis_neu(args):
    fall = _oeffne(args)
    datum = pruefe_datum(args.datum, "--datum")
    text = pflicht(args.text, "--text")
    with fall.schreiben():
        belege = fall.hole_liste(args.beleg, "B")
        if not belege:
            raise Fehler("--beleg: mindestens ein Beleg nötig")
        akteure = fall.hole_liste(args.akteur, "PO")
        eid = fall.erzeuge("E", "ereignis neu", "%s %s" % (datum, _kurz(text, 60)), datum=datum, text=text)
        fall.verknuepfe("ereignis_beleg", eid, belege)
        fall.verknuepfe("ereignis_akteur", eid, akteure)
    _zeigen("angelegt: " + eid)


def konfrontation_neu(args):
    fall = _oeffne(args)
    frage = pflicht(args.frage, "--frage")
    with fall.schreiben():
        akteur = fall.hole(args.akteur, "PO")["id"]
        zu = fall.hole_liste(args.zu, "A")
        kid = fall.erzeuge("K", "konfrontation neu", "%s: %s" % (akteur, _kurz(frage, 60)),
                           akteur=akteur, frage=frage, status="entwurf")
        fall.verknuepfe("konfrontation_zu", kid, zu)
    _zeigen("angelegt: %s | status entwurf" % kid)


def _konfrontation_wechseln(fall, kennung, erlaubt_von, neu, **werte):
    k = fall.hole(kennung, "K")
    if k["status"] not in erlaubt_von:
        raise Fehler("Konfrontation %s hat Status %s; erlaubt für diese Aktion: %s"
                     % (k["id"], k["status"], ", ".join(erlaubt_von)))
    fall.aendern("konfrontation", k["id"], status=neu, **werte)
    fall.log("konfrontation " + neu, k["id"], _json(werte))
    return k["id"]


def konfrontation_status(args):
    fall = _oeffne(args)
    am = pruefe_datum(args.am, "--am")
    frist = pruefe_datum(args.frist, "--frist") if args.frist else ""
    with fall.schreiben():
        kid = _konfrontation_wechseln(fall, args.id, ("entwurf", "gesendet"), "gesendet",
                                      gesendet_am=am, frist=frist)
    _zeigen("%s: status gesendet" % kid)


def konfrontation_antwort(args):
    fall = _oeffne(args)
    text = pflicht(args.text, "--text")
    with fall.schreiben():
        quelle = fall.hole(args.quelle, "Q")["id"] if args.quelle else None
        kid = _konfrontation_wechseln(fall, args.id, ("gesendet",), "beantwortet",
                                      antwort=text, antwort_quelle=quelle)
    _zeigen("%s: status beantwortet" % kid)


def konfrontation_keine_antwort(args):
    fall = _oeffne(args)
    vermerk = pflicht(args.vermerk, "--vermerk")
    with fall.schreiben():
        kid = _konfrontation_wechseln(fall, args.id, ("gesendet",), "keine_antwort", vermerk=vermerk)
    _zeigen("%s: status keine_antwort" % kid)


# ===========================================================================
# pruefe, export, dossier
# ===========================================================================

def pruefe(args):
    probleme = bewertung.pruefe(_oeffne(args))
    sperren = [p for p in probleme if p["stufe"] == "sperre"]
    for problem in probleme:
        _zeigen(bewertung.formatiere_problem(problem))
    if not sperren:
        _zeigen("Keine Sperren.")
    return 1 if sperren else 0


def export(args):
    daten = bewertung.export_daten(_oeffne(args))
    text = json.dumps(daten, ensure_ascii=False, indent=2)
    if args.datei:
        Path(args.datei).write_text(text + "\n", encoding="utf-8")
        _zeigen("geschrieben: " + args.datei)
    else:
        _zeigen(text)


def dossier(args):
    fall = _oeffne(args)
    modul = _dossier_modul()
    daten = bewertung.export_daten(fall)
    ziel = Path(args.ziel) if args.ziel else fall.verzeichnis
    ziel.mkdir(parents=True, exist_ok=True)
    ausgaben = {"md": ("dossier.md", modul.render_markdown), "html": ("dossier.html", modul.render_html)}
    formate = ("md", "html") if args.format == "beide" else (args.format,)
    for kuerzel in formate:
        dateiname, render = ausgaben[kuerzel]
        pfad = ziel / dateiname
        pfad.write_text(render(daten), encoding="utf-8")
        _zeigen("geschrieben: %s" % pfad)


def web(args):
    from . import web as oberflaeche  # erst hier: web importiert seinerseits cli
    try:
        server = oberflaeche.Server(args.port)
    except OSError as fehler:
        raise Fehler("Server nicht startbar (Port %d): %s" % (args.port, fehler))
    print("oberfläche: " + server.url, flush=True)
    print("Fälle: %s | beenden mit Strg+C" % faelle_wurzel(), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stoppe()
    return 0


def _dossier_modul():
    name = (__package__ or "recherche") + ".dossier"
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as fehler:
        if fehler.name == name:
            raise Fehler("recherche/dossier.py fehlt")
        raise


# ===========================================================================
# Parser
# ===========================================================================

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        print("fehler: %s" % message, file=sys.stderr)
        self.print_usage(sys.stderr)
        raise SystemExit(2)


def _aktion(bereich, name, funktion, hilfe):
    parser = bereich.add_parser(name, help=hilfe, description=hilfe)
    parser.set_defaults(funktion=funktion)
    return parser


def _liste(parser, *namen, **angaben):
    parser.add_argument(*namen, action="append", **angaben)


def _bereich_fall(parser):
    bereich = parser.add_subparsers(dest="aktion", required=True, metavar="AKTION")
    p = _aktion(bereich, "neu", fall_neu, "Fall anlegen")
    p.add_argument("slug")
    p.add_argument("--titel", required=True)
    p.add_argument("--auftrag", required=True)
    p.add_argument("--interesse")
    p = _aktion(bereich, "setzen", fall_setzen, "Fallangaben ändern")
    for name in ("titel", "auftrag", "interesse", "zusammenfassung"):
        p.add_argument("--" + name)
    _aktion(bereich, "zeigen", fall_zeigen, "Überblick über den Fall")
    _aktion(bereich, "liste", fall_liste, "Vorhandene Fälle")
    p = _aktion(bereich, "sichern", fall_sichern, "Fall als Zip-Archiv sichern (zum Mitnehmen)")
    p.add_argument("--ziel", help="Verzeichnis für das Archiv; sonst das Fallverzeichnis-Wurzel")
    p = _aktion(bereich, "laden", fall_laden, "Fall aus einem Zip-Archiv wiederherstellen")
    p.add_argument("pfad")


def _bereich_hypothese(parser):
    bereich = parser.add_subparsers(dest="aktion", required=True, metavar="AKTION")
    p = _aktion(bereich, "neu", hypothese_neu, "Hypothese anlegen")
    p.add_argument("--text", required=True)
    _liste(p, "--prueft", help="Aussage, die stimmen muss")
    _liste(p, "--widerlegt", help="was die Hypothese widerlegen würde")
    p = _aktion(bereich, "status", hypothese_status, "Status einer Hypothese setzen")
    p.add_argument("id")
    p.add_argument("status", choices=HYPOTHESEN_STATUS)
    p.add_argument("--vermerk", required=True)
    _aktion(bereich, "liste", hypothese_liste, "Hypothesen auflisten")


def _bereich_frage(parser):
    bereich = parser.add_subparsers(dest="aktion", required=True, metavar="AKTION")
    p = _aktion(bereich, "neu", frage_neu, "Frage anlegen")
    p.add_argument("--text", required=True)
    p.add_argument("--hypothese")
    p.add_argument("--plan")
    p.add_argument("--mensch", action="store_true", help="Aufgabe nur für Menschen")
    p = _aktion(bereich, "status", frage_status, "Status einer Frage setzen")
    p.add_argument("id")
    p.add_argument("status", choices=FRAGEN_STATUS)
    p.add_argument("--ergebnis")
    p = _aktion(bereich, "liste", frage_liste, "Fragen auflisten")
    p.add_argument("--status", choices=FRAGEN_STATUS)
    p.add_argument("--hypothese")


def _bereich_suche(parser):
    bereich = parser.add_subparsers(dest="aktion", required=True, metavar="AKTION")
    p = _aktion(bereich, "notieren", suche_notieren, "Durchgeführte Suche festhalten")
    p.add_argument("--anfrage", required=True)
    p.add_argument("--frage")
    p.add_argument("--hypothese")
    p.add_argument("--richtung", choices=RICHTUNGEN, default="neutral")
    p.add_argument("--treffer", type=int)
    p.add_argument("--notiz")


def _bereich_quelle(parser):
    bereich = parser.add_subparsers(dest="aktion", required=True, metavar="AKTION")
    p = _aktion(bereich, "holen", quelle_holen, "URL abrufen und Snapshot speichern")
    p.add_argument("url")
    p.add_argument("--typ", choices=QUELLEN_TYPEN, default="unbekannt")
    p.add_argument("--frage")
    p.add_argument("--archiv", action="store_true", help="Wayback-Snapshot nachschlagen")
    p.add_argument("--sichern", action="store_true", help="zusätzlich Snapshot im Archiv anstoßen")
    p = _aktion(bereich, "datei", quelle_datei, "Lokale Datei als Quelle erfassen")
    p.add_argument("pfad")
    p.add_argument("--titel", required=True)
    p.add_argument("--url")
    p.add_argument("--typ", choices=QUELLEN_TYPEN, default="unbekannt")
    p = _aktion(bereich, "text", quelle_text, "Text von der Standardeingabe als Quelle erfassen")
    p.add_argument("--titel", required=True)
    p.add_argument("--url")
    p.add_argument("--typ", choices=QUELLEN_TYPEN, default="unbekannt")
    p = _aktion(bereich, "lesen", quelle_lesen, "Gespeicherten Text lesen oder durchsuchen")
    p.add_argument("id")
    p.add_argument("--suche")
    p.add_argument("--ab", type=int)
    p.add_argument("--laenge", type=int)
    p = _aktion(bereich, "setzen", quelle_setzen, "Quellenangaben ändern")
    p.add_argument("id")
    p.add_argument("--typ", choices=QUELLEN_TYPEN)
    p.add_argument("--zuverlaessigkeit", choices=ZUVERLAESSIGKEIT)
    for name in ("titel", "herausgeber", "autor", "datum", "ursprung", "interesse"):
        p.add_argument("--" + name)
    p = _aktion(bereich, "zeigen", quelle_zeigen, "Alle Angaben zu einer Quelle")
    p.add_argument("id")
    _aktion(bereich, "liste", quelle_liste, "Quellen auflisten")


def _bereich_beleg(parser):
    bereich = parser.add_subparsers(dest="aktion", required=True, metavar="AKTION")
    p = _aktion(bereich, "neu", beleg_neu, "Wörtliches Zitat als Beleg speichern (wird geprüft)")
    p.add_argument("--quelle", required=True)
    p.add_argument("--zitat", required=True,
                   help="wörtliches Zitat; `-` liest es von der Standardeingabe (UTF-8), "
                        "nützlich bei Anführungszeichen, $ oder Backticks")
    p.add_argument("--aussage", required=True)
    p.add_argument("--direkt", action="store_true", help="die Quelle dokumentiert die Tatsache selbst")
    p.add_argument("--frage")
    p = _aktion(bereich, "setzen", beleg_setzen, "direkt-Markierung oder Aussage eines Belegs ändern")
    p.add_argument("id")
    p.add_argument("--aussage")
    _schalter(p, "direkt", "--direkt", "--nicht-direkt")
    p = _aktion(bereich, "zeigen", beleg_zeigen, "Beleg anzeigen")
    p.add_argument("id")


def _bereich_behauptung(parser):
    bereich = parser.add_subparsers(dest="aktion", required=True, metavar="AKTION")
    p = _aktion(bereich, "neu", behauptung_neu, "Behauptung anlegen")
    p.add_argument("--text", required=True)
    p.add_argument("--art", required=True, choices=BEHAUPTUNGS_ARTEN)
    p.add_argument("--hypothese")
    for name in ("pro", "contra", "aus", "betrifft"):
        p.add_argument("--" + name, help="IDs, kommagetrennt")
    p.add_argument("--belastend", action="store_true")
    p.add_argument("--zuschreibung", action="store_true",
                   help="berichtet nur, was der Autor der Quelle selbst erklärt")
    p = _aktion(bereich, "beleg", behauptung_beleg, "Belege ergänzen oder lösen")
    p.add_argument("id")
    p.add_argument("--pro")
    p.add_argument("--contra")
    p.add_argument("--ohne", help="Belege (pro oder contra) von der Behauptung lösen; der Beleg bleibt erhalten")
    p = _aktion(bereich, "setzen", behauptung_setzen, "Behauptung ändern")
    p.add_argument("id")
    p.add_argument("--text")
    p.add_argument("--art", choices=BEHAUPTUNGS_ARTEN)
    p.add_argument("--aus", help="IDs, kommagetrennt; ersetzt die bisherigen")
    p.add_argument("--betrifft", help="IDs, kommagetrennt; ersetzt die bisherigen")
    p.add_argument("--klaerung")
    _schalter(p, "belastend", "--belastend", "--nicht-belastend")
    _schalter(p, "zuschreibung", "--zuschreibung", "--keine-zuschreibung")
    p = _aktion(bereich, "pruefen", behauptung_pruefen, "Status setzen (innerhalb der Obergrenze)")
    p.add_argument("id")
    p.add_argument("--status", required=True, choices=("belegt", "gestuetzt", "unbestaetigt", "strittig", "widerlegt"))
    p.add_argument("--vermerk", required=True)
    p.add_argument("--pruefer", required=True)
    p = _aktion(bereich, "zeigen", behauptung_zeigen, "Behauptung mit Belegen anzeigen")
    p.add_argument("id")
    p = _aktion(bereich, "liste", behauptung_liste, "Behauptungen auflisten")
    p.add_argument("--status")
    p.add_argument("--hypothese")


def _schalter(parser, dest, an, aus):
    gruppe = parser.add_mutually_exclusive_group()
    gruppe.add_argument(an, dest=dest, action="store_true", default=None)
    gruppe.add_argument(aus, dest=dest, action="store_false", default=None)


def _bereich_akteur(parser):
    bereich = parser.add_subparsers(dest="aktion", required=True, metavar="AKTION")
    p = _aktion(bereich, "neu", akteur_neu, "Person oder Organisation anlegen")
    p.add_argument("--art", required=True, choices=("person", "organisation"))
    p.add_argument("--name", required=True)
    p.add_argument("--kategorie", choices=KATEGORIEN)
    _liste(p, "--kennung", help="k=v")
    p.add_argument("--notiz")
    _liste(p, "--beleg")
    p.add_argument("--trotzdem", action="store_true", help="auch bei gleichem Namen anlegen")
    p = _aktion(bereich, "setzen", akteur_setzen, "Akteur ändern")
    p.add_argument("id")
    p.add_argument("--kategorie", choices=KATEGORIEN)
    _liste(p, "--kennung", help="k=v")
    p.add_argument("--notiz")
    _liste(p, "--beleg")
    _aktion(bereich, "liste", akteur_liste, "Akteure auflisten")


def _bereich_beziehung(parser):
    bereich = parser.add_subparsers(dest="aktion", required=True, metavar="AKTION")
    p = _aktion(bereich, "neu", beziehung_neu, "Beziehung zwischen Akteuren anlegen")
    p.add_argument("--von", required=True)
    p.add_argument("--zu", required=True)
    p.add_argument("--art", required=True)
    p.add_argument("--von-datum")
    p.add_argument("--bis-datum")
    p.add_argument("--beleg", required=True, help="IDs, kommagetrennt")


def _bereich_ereignis(parser):
    bereich = parser.add_subparsers(dest="aktion", required=True, metavar="AKTION")
    p = _aktion(bereich, "neu", ereignis_neu, "Ereignis anlegen")
    p.add_argument("--datum", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--beleg", required=True, help="IDs, kommagetrennt")
    p.add_argument("--akteur", help="IDs, kommagetrennt")


def _bereich_konfrontation(parser):
    bereich = parser.add_subparsers(dest="aktion", required=True, metavar="AKTION")
    p = _aktion(bereich, "neu", konfrontation_neu, "Konfrontation (Stellungnahme) vorbereiten")
    p.add_argument("--akteur", required=True)
    p.add_argument("--frage", required=True)
    p.add_argument("--zu", help="Behauptungs-IDs, kommagetrennt")
    p = _aktion(bereich, "status", konfrontation_status, "Als gesendet markieren")
    p.add_argument("id")
    p.add_argument("status", choices=("gesendet",))
    p.add_argument("--am", required=True)
    p.add_argument("--frist")
    p = _aktion(bereich, "antwort", konfrontation_antwort, "Antwort festhalten")
    p.add_argument("id")
    p.add_argument("--text", required=True)
    p.add_argument("--quelle")
    p = _aktion(bereich, "keine-antwort", konfrontation_keine_antwort, "Ausbleibende Antwort festhalten")
    p.add_argument("id")
    p.add_argument("--vermerk", required=True)


def baue_parser():
    parser = _Parser(prog="python3 -m recherche",
                     description="Fallakte für Recherchen: Quellen, Belege, Behauptungen, Prüfung.")
    parser.add_argument("--fall", help="Fall (Slug); sonst RECHERCHE_FALL oder der einzige Fall")
    parser.add_argument("--wer", help="Name für das Protokoll; sonst RECHERCHE_WER")
    bereiche = parser.add_subparsers(dest="bereich", required=True, metavar="BEREICH")
    for name, aufbau, hilfe in (
            ("fall", _bereich_fall, "Fälle anlegen und anzeigen"),
            ("hypothese", _bereich_hypothese, "Hypothesen"),
            ("frage", _bereich_frage, "Fragen"),
            ("suche", _bereich_suche, "Suchprotokoll"),
            ("quelle", _bereich_quelle, "Quellen"),
            ("beleg", _bereich_beleg, "Belege (verifizierte Zitate)"),
            ("behauptung", _bereich_behauptung, "Behauptungen und ihr Status"),
            ("akteur", _bereich_akteur, "Personen und Organisationen"),
            ("beziehung", _bereich_beziehung, "Beziehungen"),
            ("ereignis", _bereich_ereignis, "Ereignisse"),
            ("konfrontation", _bereich_konfrontation, "Konfrontation mit Betroffenen")):
        aufbau(bereiche.add_parser(name, help=hilfe, description=hilfe))
    _aktion(bereiche, "pruefe", pruefe, "Integritätsprüfung")
    p = _aktion(bereiche, "export", export, "Fall als JSON ausgeben")
    p.add_argument("--datei")
    p = _aktion(bereiche, "dossier", dossier, "Dossier als Markdown/HTML erzeugen")
    p.add_argument("--format", choices=("md", "html", "beide"), default="beide")
    p.add_argument("--ziel")
    p = _aktion(bereiche, "web", web, "Weboberfläche für die Fallakte starten (nur 127.0.0.1)")
    p.add_argument("--port", type=int, default=0, help="Port; 0 wählt einen freien")
    return parser


def main(argv=None):
    for strom in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(strom, "reconfigure"):
            strom.reconfigure(encoding="utf-8")
    return fuehre_aus(baue_parser().parse_args(argv))


def fuehre_aus(args):
    """Führt den geparsten Befehl aus. Getrennt von `main`, damit die Weboberfläche genau
    die Namespace ausführt, die sie vorher geprüft hat."""
    try:
        return args.funktion(args) or 0
    except Fehler as fehler:
        print("fehler: %s" % fehler, file=sys.stderr)
        return fehler.code
    except BrokenPipeError:
        return 0
