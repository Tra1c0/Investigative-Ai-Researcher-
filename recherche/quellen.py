"""Quellen: Abruf, Textgewinnung, Normalisierung und Zitatprüfung."""

import codecs
import hashlib
import http.client
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from .store import Fehler, jetzt

MAX_BYTES = 25 * 1024 * 1024
MAX_UMLEITUNGEN = 5
ABRUF_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (compatible; recherche-werkzeug/0.1)"

MIN_ZITAT = 15
MAX_ZITAT = 700
MIN_ZITATTEIL = 8
MAX_ZITATSPANNE = 2000


# ===========================================================================
# Normalisierung und Zitatprüfung
# ===========================================================================

_UNSICHTBAR = "­​‌‍‎‏⁠᠎﻿"
_ERSATZ = {ord(c): None for c in _UNSICHTBAR}
_ERSATZ.update({ord(c): '"' for c in "„“”«»"})
_ERSATZ.update({ord(c): "'" for c in "‚‘’"})
_ERSATZ.update({ord(c): "-" for c in "–—"})
_AUSLASSUNG = re.compile(r"\[(?:…|\.\.\.)\]")


def entferne_unsichtbares(text):
    """Entfernt weiche Trennstriche und Zeichen ohne Breite; Ergebnis in NFC."""
    return unicodedata.normalize("NFC", text.translate({ord(c): None for c in _UNSICHTBAR}))


def normalisiere_mit_karte(text):
    """Vergleichsform samt Positionskarte: (Text, karte), karte[i] ist der Index
    des Zeichens i der Vergleichsform im Ausgangstext.

    Vergleichsform: NFC, ohne Unsichtbares, typografische Anführungszeichen und
    Striche vereinheitlicht, jeder Leerraum ein Leerzeichen, getrimmt. Groß-/
    Kleinschreibung bleibt."""
    zeichen, karte = [], []
    for index, original in enumerate(text):
        zeichen_neu = _ERSATZ.get(ord(original), original)
        if zeichen_neu is None:
            continue
        if zeichen_neu.isspace():
            if zeichen and zeichen[-1] != " ":
                zeichen.append(" ")
                karte.append(index)
            continue
        zeichen.append(zeichen_neu)
        karte.append(index)
    if zeichen and zeichen[-1] == " ":
        zeichen.pop()
        karte.pop()
    return _nfc_mit_karte("".join(zeichen), karte)


def _nfc_mit_karte(text, karte):
    """NFC je Zeichen samt folgenden kombinierenden Zeichen; Karte bleibt gültig."""
    if unicodedata.is_normalized("NFC", text):
        return text, karte
    ergebnis, neue_karte, start = [], [], 0
    for ende in range(1, len(text) + 1):
        if ende == len(text) or unicodedata.combining(text[ende]) == 0:
            teil = unicodedata.normalize("NFC", text[start:ende])
            ergebnis.append(teil)
            neue_karte.extend([karte[start]] * len(teil))
            start = ende
    return "".join(ergebnis), neue_karte


def normalisiere(text):
    """Vergleichsform ohne Karte, siehe normalisiere_mit_karte."""
    return normalisiere_mit_karte(text)[0]


def zitat_teile(zitat):
    """Zerlegt ein Zitat an `[…]` oder `[...]` in normalisierte, nichtleere Teile."""
    teile = (normalisiere(stueck) for stueck in _AUSLASSUNG.split(zitat))
    return [teil for teil in teile if teil]


def pruefe_zitatform(zitat):
    """Prüft Länge und Teillängen; gibt die normalisierten Teile zurück."""
    laenge = len(normalisiere(zitat))
    if not MIN_ZITAT <= laenge <= MAX_ZITAT:
        raise Fehler("Zitat muss %d bis %d Zeichen lang sein" % (MIN_ZITAT, MAX_ZITAT))
    teile = zitat_teile(zitat)
    for teil in teile:
        if len(teil) < MIN_ZITATTEIL:
            raise Fehler('Zitatteil zu kurz (mindestens %d Zeichen): "%s"' % (MIN_ZITATTEIL, teil))
    return teile


def finde_teile(teile, text_norm, max_spanne=MAX_ZITATSPANNE):
    """Offset des ersten Teils im normalisierten Text, wenn alle Teile in dieser
    Reihenfolge und ohne Überlappung vorkommen und vom Anfang des ersten bis zum
    Ende des letzten höchstens `max_spanne` Zeichen liegen (None: unbegrenzt).

    Die Grenze verhindert, dass aus weit entfernten Stellen ein Zitat montiert wird."""
    if not teile:
        return None
    start = text_norm.find(teile[0])
    while start >= 0:
        position = start + len(teile[0])
        for teil in teile[1:]:
            gefunden = text_norm.find(teil, position)
            if gefunden < 0:
                return None  # weiter rechts kann es erst recht nicht mehr passen
            position = gefunden + len(teil)
        if max_spanne is None or position - start <= max_spanne:
            return start
        start = text_norm.find(teile[0], start + 1)
    return None


_WORT = re.compile(r"\w+")


def aehnlichste_stelle(zitat_norm, text_norm, laenge=300):
    """Passage mit der größten Wortüberlappung: (Offset, Ausschnitt).

    Gleitendes Fenster über die Wörter des Textes; jedes gesuchte Wort zählt
    einmal pro Fenster, gewichtet mit seiner Länge. Linear in der Textlänge."""
    quellwoerter = [w.lower() for w in _WORT.findall(zitat_norm)]
    gesucht = {w for w in quellwoerter if len(w) >= 4} or set(quellwoerter)
    woerter = [(m.start(), m.group().lower()) for m in _WORT.finditer(text_norm)]
    fenster = max(5, len(quellwoerter))
    zaehler = {}
    punkte = beste_punkte = 0
    bester_rechts = 0
    for rechts, (_, wort) in enumerate(woerter):
        if wort in gesucht:
            zaehler[wort] = zaehler.get(wort, 0) + 1
            if zaehler[wort] == 1:
                punkte += len(wort)
        links = rechts - fenster
        if links >= 0 and woerter[links][1] in gesucht:
            altes = woerter[links][1]
            zaehler[altes] -= 1
            if zaehler[altes] == 0:
                punkte -= len(altes)
        if punkte > beste_punkte:
            beste_punkte, bester_rechts = punkte, rechts
    if beste_punkte == 0:
        return 0, text_norm[:laenge]
    erstes = max(0, bester_rechts - fenster + 1)
    while woerter[erstes][1] not in gesucht:
        erstes += 1
    start = woerter[erstes][0]
    return start, text_norm[start:start + laenge]


# ===========================================================================
# Abruf
# ===========================================================================

def _intern(adresse):
    if getattr(adresse, "ipv4_mapped", None):
        adresse = adresse.ipv4_mapped
    return (adresse.is_loopback or adresse.is_private or adresse.is_link_local
            or adresse.is_unspecified)


def _adressen(host, port):
    try:
        infos = socket.getaddrinfo(host, port)
    except (socket.gaierror, UnicodeError):
        return []  # nicht auflösbar: der Abruf selbst scheitert dann mit eigenem Grund
    return [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]


def pruefe_ziel(url):
    """Nur http/https; interne Adressen nur mit RECHERCHE_LOKAL_ERLAUBT=1."""
    teile = urllib.parse.urlsplit(url)
    if teile.scheme not in ("http", "https"):
        raise Fehler("nur http und https sind erlaubt")
    try:
        host, port = teile.hostname, teile.port
    except ValueError:
        raise Fehler("ungültige URL")
    if not host:
        raise Fehler("ungültige URL")
    if os.environ.get("RECHERCHE_LOKAL_ERLAUBT") == "1":
        return
    if any(_intern(adresse) for adresse in _adressen(host, port)):
        raise Fehler("interne Adresse nicht erlaubt")


class _Umleitung(urllib.request.HTTPRedirectHandler):
    """Prüft jedes Umleitungsziel wie die Ausgangs-URL und begrenzt die Zahl."""

    max_redirections = MAX_UMLEITUNGEN

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        pruefe_ziel(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _grund(fehler):
    if isinstance(fehler, urllib.error.HTTPError):
        return "HTTP %d" % fehler.code if fehler.code >= 400 else str(fehler.msg)
    if isinstance(fehler, urllib.error.URLError):
        fehler = fehler.reason
    if isinstance(fehler, (TimeoutError, socket.timeout)):
        return "Zeitüberschreitung"
    return str(fehler) or fehler.__class__.__name__


def hole_url(url):
    """Lädt die URL; gibt (endgültige URL, Content-Type, Header-Charset, Rohbytes) zurück."""
    pruefe_ziel(url)
    anfrage = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_Umleitung())
    try:
        with opener.open(anfrage, timeout=ABRUF_TIMEOUT) as antwort:
            angekuendigt = antwort.headers.get("Content-Length", "")
            if angekuendigt.isdigit() and int(angekuendigt) > MAX_BYTES:
                raise Fehler("Antwort größer als 25 MB")
            roh = antwort.read(MAX_BYTES + 1)
            if len(roh) > MAX_BYTES:
                raise Fehler("Antwort größer als 25 MB")
            return (antwort.geturl(), antwort.headers.get("Content-Type", ""),
                    antwort.headers.get_content_charset(), roh)
    except Fehler:
        raise
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as fehler:
        raise Fehler("Abruf fehlgeschlagen (%s)" % _grund(fehler))


# ===========================================================================
# Archiv (nur auf ausdrücklichen Wunsch)
# ===========================================================================

def _lade(url, timeout):
    anfrage = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(anfrage, timeout=timeout)


def archiv_suchen(url):
    """Nächster Wayback-Snapshot oder None."""
    abfrage = "https://archive.org/wayback/available?url=" + urllib.parse.quote(url, safe="")
    with _lade(abfrage, 8) as antwort:
        daten = json.loads(antwort.read(1000000).decode("utf-8", "replace"))
    nahester = (daten.get("archived_snapshots") or {}).get("closest") or {}
    return nahester.get("url") if nahester.get("available") else None


def archiv_sichern(url):
    """Beauftragt einen neuen Snapshot; gibt dessen URL zurück, wenn bekannt."""
    with _lade("https://web.archive.org/save/" + url, 20) as antwort:
        endgueltig = antwort.geturl()
        if re.search(r"/web/\d+", endgueltig):
            return endgueltig
        ort = antwort.headers.get("Content-Location", "")
        if re.match(r"/web/\d+", ort):
            return "https://web.archive.org" + ort
    return None


def archiviere(url, sichern):
    """Best effort: (archiv_url oder "", Hinweiszeilen)."""
    hinweise = []
    archiv_url = ""
    try:
        archiv_url = archiv_suchen(url) or ""
        if sichern:
            archiv_url = archiv_sichern(url) or archiv_url
        if not archiv_url:
            hinweise.append("hinweis: kein Archivstand gefunden")
    except Exception:  # bewusst breit: der Archivdienst darf den Abruf nie scheitern lassen
        hinweise.append("hinweis: Archiv nicht erreichbar")
    return archiv_url, hinweise


# ===========================================================================
# Textgewinnung
# ===========================================================================

_BLOCK = {"p", "div", "section", "article", "header", "footer", "nav", "aside", "main",
          "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table", "tr", "blockquote",
          "pre", "br", "hr", "form", "figure", "figcaption", "dl", "dt", "dd", "address",
          "fieldset", "details", "summary", "body"}
_UEBERSPRINGEN = {"script", "style", "noscript", "template", "svg"}
_DATUM_ANFANG = re.compile(r"\s*(\d{4}(?:-\d{2}(?:-\d{2})?)?)")


class _HtmlSammler(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.teile = []
        self.titel = []
        self.meta = {}
        self.zeit = ""
        self._ueberspringen = 0
        self._im_kopf = False
        self._im_titel = False
        self._titel_fertig = False

    def handle_starttag(self, tag, attrs):
        attribute = dict(attrs)
        if tag == "head":
            self._im_kopf = True
        elif tag == "body":
            self._im_kopf = False
        elif tag == "meta":
            self._merke_meta(attribute)
        elif tag == "title" and not self._ueberspringen and not self._titel_fertig:
            self._im_titel = True
        elif tag == "time" and not self.zeit:
            self.zeit = attribute.get("datetime") or ""
        elif tag in _UEBERSPRINGEN:
            self._ueberspringen += 1
        if tag in _BLOCK:
            self.teile.append("\n")
        elif tag in ("td", "th"):
            self.teile.append(" ")

    def handle_endtag(self, tag):
        if tag == "head":
            self._im_kopf = False
        elif tag == "title" and self._im_titel:
            self._im_titel = False
            self._titel_fertig = True
        elif tag in _UEBERSPRINGEN and self._ueberspringen:
            self._ueberspringen -= 1
        if tag in _BLOCK:
            self.teile.append("\n")

    def handle_data(self, daten):
        if self._im_titel:
            self.titel.append(daten)
        elif not self._ueberspringen and not self._im_kopf:
            self.teile.append(re.sub(r"\s+", " ", daten))

    def _merke_meta(self, attribute):
        name = (attribute.get("property") or attribute.get("name") or "").lower()
        inhalt = (attribute.get("content") or "").strip()
        if name and inhalt and name not in self.meta:
            self.meta[name] = inhalt


def raeume_auf(text):
    """Zeilen trimmen, Leerzeichen zusammenziehen, höchstens eine Leerzeile am Stück."""
    ergebnis = []
    for zeile in text.split("\n"):
        zeile = re.sub(r"[ \t]+", " ", zeile).strip()
        if zeile or (ergebnis and ergebnis[-1]):
            ergebnis.append(zeile)
    return "\n".join(ergebnis).strip()


def _datumsteil(wert):
    treffer = _DATUM_ANFANG.match(wert or "")
    return treffer.group(1) if treffer else ""


def _meta_charset(roh):
    treffer = re.search(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([-\w.:]+)", roh[:20000], re.I)
    return treffer.group(1).decode("ascii", "ignore") if treffer else None


def dekodiere(roh, kopf_charset=None, html=False):
    """Header-Charset, dann <meta charset>, sonst UTF-8; Fehler werden ersetzt."""
    name = kopf_charset or (_meta_charset(roh) if html else None) or "utf-8"
    try:
        codecs.lookup(name)
    except LookupError:
        name = "utf-8"
    return roh.decode(name, errors="replace")


def extrahiere_html(roh, kopf_charset=None):
    sammler = _HtmlSammler()
    sammler.feed(dekodiere(roh, kopf_charset, html=True))
    sammler.close()
    titel = sammler.meta.get("og:title") or " ".join("".join(sammler.titel).split())
    return {
        "text": raeume_auf(entferne_unsichtbares("".join(sammler.teile))),
        "titel": " ".join(titel.split()),
        "herausgeber": " ".join(sammler.meta.get("og:site_name", "").split()),
        "datum": _datumsteil(sammler.meta.get("article:published_time") or sammler.zeit),
        "autor": " ".join(sammler.meta.get("author", "").split()),
    }


def extrahiere_pdf(roh):
    """Text per pdftotext, sonst pypdf, sonst leer."""
    with tempfile.TemporaryDirectory() as ordner:
        pfad = os.path.join(ordner, "quelle.pdf")
        with open(pfad, "wb") as datei:
            datei.write(roh)
        text = _pdftotext(pfad)
        if text is None:
            text = _pypdf(pfad)
    return raeume_auf(entferne_unsichtbares(text.replace("\f", "\n\n")))


def _pdftotext(pfad):
    if not shutil.which("pdftotext"):
        return None
    try:
        ergebnis = subprocess.run(["pdftotext", "-enc", "UTF-8", pfad, "-"],
                                  capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return ergebnis.stdout.decode("utf-8", "replace") if ergebnis.returncode == 0 else None


def _pypdf(pfad):
    try:
        import pypdf
        leser = pypdf.PdfReader(pfad)
        return "\n\n".join(seite.extract_text() or "" for seite in leser.pages)
    except Exception:  # bewusst breit: optionale Bibliothek, kaputte PDFs liefern leeren Text
        return ""


_HTML_TYPEN = ("text/html", "application/xhtml+xml")


def inhaltsart(mime, roh, name=""):
    """html, pdf, text oder andere; aus Content-Type, Dateiname und Inhalt."""
    mime = (mime or "").split(";")[0].strip().lower()
    if not mime or mime == "application/octet-stream":
        mime = mimetypes.guess_type(name)[0] or mime
    kopf = roh[:2000].lower()
    if mime in _HTML_TYPEN or (not mime and (b"<html" in kopf or b"<!doctype html" in kopf)):
        return "html"
    if mime == "application/pdf" or roh.startswith(b"%PDF"):
        return "pdf"
    if mime.startswith("text/") or mime.endswith(("json", "xml")):
        return "text"
    if b"\0" not in roh[:4096]:
        return "text"
    return "andere"


def extrahiere(roh, mime, kopf_charset=None, name=""):
    """Text und Metadaten (titel, herausgeber, datum, autor) aus Rohbytes."""
    art = inhaltsart(mime, roh, name)
    leer = {"titel": "", "herausgeber": "", "datum": "", "autor": ""}
    if art == "html":
        return extrahiere_html(roh, kopf_charset)
    if art == "pdf":
        return dict(leer, text=extrahiere_pdf(roh))
    if art == "text":
        return dict(leer, text=dekodiere(roh, kopf_charset))
    return dict(leer, text="")


# ===========================================================================
# Quelle anlegen
# ===========================================================================

def sha256_von(roh):
    return hashlib.sha256(roh).hexdigest()


def finde_duplikat(fall, sha):
    zeilen = fall.alle("quelle", "WHERE sha256 = ?", (sha,))
    return zeilen[0]["id"] if zeilen else None


def lege_quelle_an(fall, roh, art, mime, kopf_charset="", url="", angefragt_url="",
                   typ="unbekannt", titel="", name="", archiv_url="", frage=None):
    """Speichert Snapshot und Text. Gibt (ID, neu, Zeile) zurück; bei gleichem
    Inhalt (sha256) wird nichts gespeichert und die vorhandene ID geliefert."""
    sha = sha256_von(roh)
    vorhanden = finde_duplikat(fall, sha)
    if vorhanden:
        return vorhanden, False, None
    info = extrahiere(roh, mime, kopf_charset, name)
    with fall.schreiben():
        vorhanden = finde_duplikat(fall, sha)
        if vorhanden:
            return vorhanden, False, None
        quelle_id = fall.neue_id("Q")
        _schreibe_snapshot(fall, quelle_id, roh, info["text"])
        fall.einfuegen(
            "quelle", id=quelle_id, url=url, angefragt_url=angefragt_url,
            titel=titel or info["titel"] or url or name, herausgeber=info["herausgeber"],
            autor=info["autor"], datum=info["datum"], abgerufen=jetzt(), sha256=sha, typ=typ,
            archiv_url=archiv_url, zeichen=len(info["text"]), art=art, inhaltstyp=mime or "",
            frage=frage)
        fall.log("quelle " + art, quelle_id, url or name or titel)
    return quelle_id, True, fall.hole(quelle_id, "Q")


def _schreibe_snapshot(fall, quelle_id, roh, text):
    ordner = fall.quellen_verzeichnis(quelle_id)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "roh").write_bytes(roh)
    (ordner / "text.txt").write_text(text, encoding="utf-8")
