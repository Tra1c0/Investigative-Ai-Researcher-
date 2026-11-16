"""Lokale Weboberfläche für die Fallakte (nur Standardbibliothek).

Der Server treibt die vorhandene Kommandozeile (`recherche.cli.main`) im selben Prozess und
zeigt ihre Antworten; keine Regel der Fallakte ist hier nachgebaut. Er lauscht nur auf
127.0.0.1, verlangt ein Token je Serverstart und liest oder schreibt nie einen vom Client
gewählten Pfad.

Aufruf von Hand: `python3 -m recherche web [--port N]`. Die Android-Hülle ruft
`starte_im_hintergrund`, `exportiere`, `importiere` und `dossier_datei` beim Namen.
"""

import contextlib
import hmac
import http.cookies
import io
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import bewertung, cli
from . import quellen as q
from . import store
from .store import SLUG, Fall, Fehler, faelle_liste, faelle_wurzel, sichere_fall

SEITE = Path(__file__).resolve().parent / "web_ui.html"

MAX_JSON = 1024 * 1024
MAX_UPLOAD = q.MAX_BYTES
MAX_LADEN = 512 * 1024 * 1024
MAX_SLUG = 80
WER_STANDARD = "nutzer"

# Ein Befehl nach dem anderen: die Kommandozeile tauscht Standardströme des Prozesses aus.
_SPERRE = threading.Lock()

LESE_TIMEOUT = 30  # Sekunden je Lese- oder Schreibvorgang einer Verbindung

_VERBOTENE_BEFEHLE = (("quelle", "datei"), ("fall", "sichern"), ("fall", "laden"))
_VERBOTENE_OPTIONEN = ("--datei", "--ziel")
_OHNE_FALL = (("fall", "neu"), ("fall", "liste"))
# Erlaubt ist, was die Seite schickt (der Test liest die Paare aus web_ui.html); alles andere 403.
ERLAUBT = frozenset([
    ("fall", "neu"), ("fall", "setzen"), ("fall", "liste"),
    ("hypothese", "neu"), ("hypothese", "status"),
    ("frage", "neu"), ("frage", "status"),
    ("suche", "notieren"),
    ("quelle", "holen"), ("quelle", "text"), ("quelle", "lesen"), ("quelle", "setzen"),
    ("beleg", "neu"),
    ("behauptung", "neu"), ("behauptung", "setzen"), ("behauptung", "beleg"), ("behauptung", "pruefen"),
    ("akteur", "neu"), ("akteur", "setzen"),
    ("beziehung", "neu"), ("ereignis", "neu"),
    ("konfrontation", "neu"), ("konfrontation", "status"), ("konfrontation", "antwort"),
    ("konfrontation", "keine-antwort"),
])


class Anfragefehler(Exception):
    """Fehler, der als HTTP-Status mit kurzem deutschem Text beantwortet wird."""

    def __init__(self, status, text):
        super().__init__(text)
        self.status = status
        self.text = text


# ===========================================================================
# Prüfungen der Eingaben
# ===========================================================================

def pruefe_slug(wert):
    """Gibt den Slug aus der Liste der vorhandenen Fälle zurück (nie die Eingabe selbst).

    Erst die Form, dann der Abgleich mit den Fällen: Ein Slug, der nicht passt,
    erreicht das Dateisystem nicht."""
    if not isinstance(wert, str) or len(wert) > MAX_SLUG or not SLUG.fullmatch(wert):
        raise Anfragefehler(400, "Ungültiger Fallname (erlaubt: a-z, 0-9 und Bindestrich).")
    for vorhanden in faelle_liste(faelle_wurzel()):
        if vorhanden == wert:
            return vorhanden
    raise Anfragefehler(404, "unbekannt: Fall %s" % wert)


def pruefe_wer(wert):
    if wert is None:
        return WER_STANDARD
    if not isinstance(wert, str):
        raise Anfragefehler(400, "wer muss ein Text sein.")
    wert = "".join(z for z in wert if z.isprintable()).strip()
    if len(wert) > 80:
        raise Anfragefehler(400, "wer ist zu lang (höchstens 80 Zeichen).")
    return wert or WER_STANDARD


def pruefe_argv(argv):
    """Erste Stufe, auf der Rohliste: Form und offensichtliche Pfadwünsche. Maßgeblich ist die
    zweite Stufe (`_pruefer`), die prüft, was der Parser verstanden hat; argparse kennt Wege,
    die sich auf der Liste nicht sicher erkennen lassen (`--`, Abkürzungen)."""
    if (not isinstance(argv, list) or not argv or len(argv) > 200
            or not all(isinstance(a, str) for a in argv)):
        raise Anfragefehler(400, "argv muss eine nichtleere Liste von Texten sein.")
    if argv[0].startswith("-"):
        raise Anfragefehler(403, "Globale Optionen setzt die Oberfläche selbst.")
    if "--" in argv:
        raise Anfragefehler(403, "Das Trennzeichen -- ist über die Weboberfläche nicht erlaubt.")
    if argv[0] == "web" or tuple(argv[:2]) in _VERBOTENE_BEFEHLE:
        raise Anfragefehler(403, "Dieser Befehl ist über die Weboberfläche nicht erlaubt: %s."
                            % " ".join(argv[:2]))
    for arg in argv:
        if arg.startswith("--"):
            name = arg.split("=", 1)[0]
            # argparse nimmt auch Abkürzungen wie --dat; darum gilt jedes Präfix
            if len(name) >= 3 and any(o.startswith(name) for o in _VERBOTENE_OPTIONEN):
                raise Anfragefehler(403, "Die Option %s ist über die Weboberfläche nicht "
                                    "erlaubt." % name)


def _pruefer(slug, wer):
    """Zweite Stufe: prüft die geparste Namespace, genau die, die danach läuft."""
    def pruefe(args):
        paar = (getattr(args, "bereich", None), getattr(args, "aktion", None))
        if paar not in ERLAUBT:
            raise Anfragefehler(403, "Dieser Befehl ist über die Weboberfläche nicht erlaubt: %s."
                                % (" ".join(t for t in paar if t) or "?"))
        for name in ("pfad", "datei", "ziel"):
            if getattr(args, name, None) is not None:
                raise Anfragefehler(403, "Die Weboberfläche liest oder schreibt keine vom Client "
                                    "gewählten Pfade (%s)." % name)
        if getattr(args, "fall", None) != slug or getattr(args, "wer", None) != wer:
            raise Anfragefehler(403, "Fall und Name setzt die Oberfläche selbst.")
    return pruefe


# ===========================================================================
# Befehle ausführen
# ===========================================================================

def _lauf(argv, eingabe, pruefung):
    """Parst `argv`, prüft die Namespace mit `pruefung` und führt genau diese aus
    (`cli.fuehre_aus`); Standardströme ersetzt, SystemExit abgefangen."""
    aus, fehler = io.StringIO(), io.StringIO()
    stdin_alt = sys.stdin
    sys.stdin = io.TextIOWrapper(io.BytesIO((eingabe or "").encode("utf-8")), encoding="utf-8")
    try:
        # Die Kommandozeile schließt ihre Datenbankverbindungen erst beim Aufräumen; die
        # ResourceWarning dazu gehört nicht in die Antwort an den Nutzer.
        with contextlib.redirect_stdout(aus), contextlib.redirect_stderr(fehler), \
                warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            try:
                args = cli.baue_parser().parse_args(argv)
                pruefung(args)
                code = cli.fuehre_aus(args)
            except SystemExit as ende:
                code = ende.code
                if code is None:
                    code = 0
                elif not isinstance(code, int):
                    fehler.write("fehler: %s\n" % code)
                    code = 1
            except Anfragefehler:
                raise
            except Exception as unerwartet:  # nie den Server mitreißen
                fehler.write("fehler: unerwarteter Fehler: %s: %s\n"
                             % (type(unerwartet).__name__, unerwartet))
                code = 1
    finally:
        sys.stdin = stdin_alt
    return {"code": int(code or 0), "aus": aus.getvalue(), "fehler": fehler.getvalue()}


def fuehre_befehl_aus(fall, wer, argv, eingabe):
    """Eine Kommandozeile des Clients, geprüft und unter der Sperre ausgeführt."""
    pruefe_argv(argv)
    if eingabe is not None and not isinstance(eingabe, str):
        raise Anfragefehler(400, "eingabe muss ein Text oder null sein.")
    wer = pruefe_wer(wer)
    # Mit = angehängt, damit ein Name oder Fall, der mit - beginnt, keine Option wird.
    vorspann = ["--wer=" + wer]
    slug = None
    if fall is None:
        if tuple(argv[:2]) not in _OHNE_FALL:
            raise Anfragefehler(400, "Für diesen Befehl muss ein Fall angegeben werden.")
    else:
        slug = pruefe_slug(fall)
        vorspann.append("--fall=" + slug)
    with _SPERRE:
        return _lauf(vorspann + argv, eingabe, _pruefer(slug, wer))


def _dateiname(name):
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(z for z in name if z.isprintable() and z not in '<>:"|?*').strip(" .")
    return name[:150] or "upload"


def lade_quelle_datei(slug, titel, name, roh, wer, typ):
    """Hochgeladene Bytes als Quelle der Art `datei`; über `quelle datei` mit einer Datei
    in einem eigenen Temp-Verzeichnis, deren Namen der Server bestimmt."""
    slug = pruefe_slug(slug)
    wer = pruefe_wer(wer)
    with tempfile.TemporaryDirectory(prefix="recherche-upload-") as temp:
        pfad = Path(temp) / _dateiname(name)
        pfad.write_bytes(roh)
        argv = ["--wer=" + wer, "--fall=" + slug, "quelle", "datei", str(pfad), "--titel=" + (titel or "")]
        if typ:
            argv.append("--typ=" + typ)

        def pruefe(args):
            if (args.bereich, args.aktion, args.pfad, args.fall, args.wer) != ("quelle", "datei", str(pfad), slug, wer):
                raise Anfragefehler(403, "Interner Fehler beim Hochladen.")
        with _SPERRE:
            return _lauf(argv, None, pruefe)


# ===========================================================================
# Lesen und Datenaustausch
# ===========================================================================

@contextlib.contextmanager
def _fall_lesen(slug):
    fall = Fall.oeffnen(faelle_wurzel(), slug, "web")
    try:
        yield fall
    finally:
        fall.conn.close()


def faelle():
    wurzel = faelle_wurzel()
    ergebnis = []
    for slug in faelle_liste(wurzel):
        try:
            with _fall_lesen(slug) as fall:
                titel = fall.meta().get("titel", "")
        except (sqlite3.Error, Fehler):
            titel = ""
        ergebnis.append({"slug": slug, "titel": titel})
    return ergebnis


def export_von(slug):
    """Export eines Falls aus einem einzigen Lese-Schnappschuss."""
    with _fall_lesen(pruefe_slug(slug)) as fall:
        fall.conn.execute("BEGIN")
        try:
            return bewertung.export_daten(fall)
        finally:
            fall.conn.execute("ROLLBACK")


def dossier_html(slug):
    return cli._dossier_modul().render_html(export_von(slug))


def fuer_einbettung(html):
    """Dossier für den Rahmen der Seite: Links gehen in ein neues Fenster (in der Android-
    Hülle landet das im Browser), Sprünge innerhalb des Dossiers bleiben im Rahmen."""
    html = html.replace('<a href="#', '<a target="_self" href="#')
    return html.replace("<head>", '<head><base target="_blank">', 1)


def optionen():
    """Die Aufzählungen der Fallakte, damit die Seite keine eigene Kopie führt."""
    return {"quellen_typen": store.QUELLEN_TYPEN, "kategorien": store.KATEGORIEN,
            "zuverlaessigkeit": store.ZUVERLAESSIGKEIT, "behauptungs_arten": store.BEHAUPTUNGS_ARTEN,
            "pruefbare_status": store.PRUEFBARE_STATUS, "hypothesen_status": store.HYPOTHESEN_STATUS,
            "fragen_status": store.FRAGEN_STATUS, "richtungen": store.RICHTUNGEN}


def exportiere(slug, zielverzeichnis):
    """Schreibt die Akte als Zip (`store.sichere_fall`) und gibt den Pfad zurück."""
    slug = pruefe_slug(slug)
    with _fall_lesen(slug) as fall:
        pfad, _anzahl, _groesse = sichere_fall(fall, zielverzeichnis)
    return str(pfad)


def lade_akte(pfad, herkunft):
    """Lädt und prüft eine gesicherte Akte; gibt (Slug, [(ID, Grund)]) zurück."""
    with _SPERRE:
        return bewertung.lade_akte(faelle_wurzel(), pfad, "web", herkunft)


def importiere(pfad):
    """Stellt eine gesicherte Akte wieder her und gibt den Text zurück, den die Hülle dem
    Nutzer zeigt: „Akte geladen: <slug>“, bei zurückgesetzten Prüfungen mit deren Zahl."""
    slug, zurueck = lade_akte(pfad, "Weboberfläche")
    text = "Akte geladen: %s" % slug
    if zurueck:
        text += " (%d Prüfung%s zurückgesetzt: %s)" % (
            len(zurueck), "" if len(zurueck) == 1 else "en", ", ".join(aid for aid, _ in zurueck))
    return text


def loesche_fall(slug, bestaetigung):
    """Entfernt einen Fall endgültig. Nur über die Weboberfläche, nie über `befehl`: Der Fall
    und die Bestätigung müssen derselbe vorhandene Slug sein."""
    slug = pruefe_slug(slug)
    if bestaetigung != slug:
        raise Anfragefehler(400, "Die Bestätigung stimmt nicht mit dem Kurznamen des Falls "
                            "überein; nichts wurde gelöscht.")
    wurzel = faelle_wurzel()
    with _SPERRE:
        ziel = wurzel / slug
        temp = wurzel / (".loeschen-" + secrets.token_hex(8))
        try:
            os.rename(str(ziel), str(temp))
        except OSError as fehler:
            raise Anfragefehler(500, "Der Fall ließ sich nicht entfernen: %s" % fehler)
        if temp.is_symlink():
            temp.unlink()
        else:
            shutil.rmtree(str(temp), ignore_errors=True)
    return slug


def dossier_datei(slug, zielverzeichnis):
    """Schreibt das Dossier als eine HTML-Datei und gibt ihren Pfad zurück."""
    slug = pruefe_slug(slug)
    html = dossier_html(slug)
    ziel = Path(zielverzeichnis)
    ziel.mkdir(parents=True, exist_ok=True)
    pfad = ziel / ("dossier-%s.html" % slug)
    pfad.write_text(html, encoding="utf-8")
    return str(pfad)


# ===========================================================================
# HTTP
# ===========================================================================

_NICHT_ZEICHEN = re.compile(r"[^A-Za-z0-9._-]")


class _Handler(BaseHTTPRequestHandler):
    server_version = "recherche"
    sys_version = ""
    timeout = LESE_TIMEOUT  # ein Client, der nichts sendet, hält den Thread nicht ewig
    # HTTP/1.0: jede Antwort schließt die Verbindung, ein ungelesener Rest eines
    # abgelehnten Bodys kann so keine Folgeanfrage verfälschen.

    def log_message(self, *args):
        pass

    @property
    def app(self):
        return self.server.app

    # -- Antworten

    def _kopf(self, status, typ, laenge, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(laenge))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for name, wert in extra:
            self.send_header(name, wert)
        self.end_headers()

    def _senden(self, status, koerper, typ, extra=()):
        self._kopf(status, typ, len(koerper), extra)
        if self.command != "HEAD":
            self.wfile.write(koerper)

    def _text(self, status, text, extra=()):
        self._senden(status, text.encode("utf-8"), "text/plain; charset=utf-8", extra)

    def _json(self, status, wert):
        self._senden(status, json.dumps(wert, ensure_ascii=False).encode("utf-8"),
                     "application/json; charset=utf-8")

    def send_error(self, code, message=None, explain=None):
        """Auch Fehler des Protokolls bekommen die Sicherheitsköpfe und deutschen Text."""
        self.close_connection = True
        try:
            self._text(code, "Anfrage nicht möglich (%s)." % code)
        except OSError:
            pass

    # -- Zugang

    def _hosts(self):
        port = self.app.port
        return ("127.0.0.1:%d" % port, "localhost:%d" % port)

    def _erlaubter_host(self):
        return self.headers.get("Host", "") in self._hosts()

    def _erlaubter_ursprung(self):
        ursprung = self.headers.get("Origin")
        return ursprung is None or ursprung in ["http://" + h for h in self._hosts()]

    def _token_ok(self, wert):
        return bool(wert) and hmac.compare_digest(wert.encode("utf-8"), self.app.token.encode("utf-8"))

    def _angemeldet(self):
        if self._token_ok(self.headers.get("X-Recherche-Token", "")):
            return True
        try:
            cookies = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return False
        morsel = cookies.get(self.app.cookie)
        return bool(morsel) and self._token_ok(morsel.value)

    # -- Verteilung

    def do_GET(self):
        self._bearbeite()

    def do_POST(self):
        self._bearbeite()

    def do_HEAD(self):
        self._bearbeite()

    def do_PUT(self):
        self._text(405, "Methode nicht erlaubt.")

    do_DELETE = do_PATCH = do_OPTIONS = do_PUT

    def _bearbeite(self):
        self._body_gelesen = False
        try:
            self._verteile()
        except Anfragefehler as fehler:
            self.close_connection = True
            if self.path.startswith("/api/"):
                self._json(fehler.status, {"fehler": fehler.text})
            else:
                self._text(fehler.status, fehler.text)
            if self.command == "POST" and not self._body_gelesen:
                self._lingern()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as unerwartet:
            self.close_connection = True
            try:
                self._json(500, {"fehler": "Interner Fehler: %s" % type(unerwartet).__name__})
            except OSError:
                pass

    def _lingern(self):
        """Nach einer Antwort, bevor der Körper gelesen wurde: erst die Senderichtung schließen
        und ein Stück vom Rest lesen. Wer die Verbindung mit ungelesenen Daten schließt, löst ein
        RST aus, das die Antwort beim Client vernichten kann."""
        try:
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_WR)
            self.connection.settimeout(1)
            rest = 64 * 1024
            while rest > 0:
                stueck = self.connection.recv(min(rest, 16 * 1024))
                if not stueck:
                    break
                rest -= len(stueck)
        except OSError:
            pass

    def _verteile(self):
        if not self._erlaubter_host():
            raise Anfragefehler(403, "Ungültiger Host. Die Oberfläche antwortet nur auf 127.0.0.1.")
        teile = urlsplit(self.path)
        abfrage = {k: v[-1] for k, v in parse_qs(teile.query, keep_blank_values=True).items()}
        if self.command == "POST" and not self._erlaubter_ursprung():
            raise Anfragefehler(403, "Ungültiger Ursprung der Anfrage.")
        if teile.path == "/" and "t" in abfrage:
            return self._anmelden(abfrage["t"])
        if not self._angemeldet():
            raise Anfragefehler(403, "Kein Zugriff. Die Oberfläche über die Adresse mit Token "
                                "öffnen (python3 -m recherche web gibt sie aus).")
        if self.command == "POST":
            routen = {"/api/befehl": self._befehl, "/api/quelle-datei": self._quelle_datei,
                      "/api/laden": self._laden, "/api/loeschen": self._loeschen}
        else:
            routen = {"/": self._seite, "/api/faelle": self._faelle, "/api/optionen": self._optionen,
                      "/api/export": self._export, "/api/dossier": self._dossier,
                      "/api/sichern": self._sichern}
        route = routen.get(teile.path)
        if route is None:
            raise Anfragefehler(404 if self.command == "GET" else 405, "Nicht gefunden.")
        route(abfrage)

    def _anmelden(self, token):
        if not self._token_ok(token):
            raise Anfragefehler(403, "Token ungültig.")
        cookie = "%s=%s; HttpOnly; SameSite=Strict; Path=/" % (self.app.cookie, self.app.token)
        self._kopf(302, "text/plain; charset=utf-8", 0,
                   [("Location", "/"), ("Set-Cookie", cookie)])

    # -- Körper lesen

    def _koerper(self, maximal, typ=None):
        if self.headers.get("Transfer-Encoding"):
            raise Anfragefehler(411, "Content-Length ist erforderlich.")
        if typ is not None:
            gesendet = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if gesendet != typ:
                raise Anfragefehler(415, "Content-Type muss %s sein." % typ)
        try:
            laenge = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise Anfragefehler(411, "Content-Length ist erforderlich.")
        if laenge < 0:
            raise Anfragefehler(400, "Ungültige Content-Length.")
        if laenge > maximal:
            raise Anfragefehler(413, "Anfrage zu groß (höchstens %d MB)." % (maximal // (1024 * 1024) or 1))
        return laenge

    def _lies(self, laenge):
        self._body_gelesen = True
        teile, rest = [], laenge
        while rest > 0:
            stueck = self.rfile.read(min(65536, rest))
            if not stueck:
                raise Anfragefehler(400, "Anfrage unvollständig.")
            teile.append(stueck)
            rest -= len(stueck)
        return b"".join(teile)

    # -- Routen

    def _seite(self, abfrage):
        try:
            seite = SEITE.read_text(encoding="utf-8")
        except OSError:
            raise Anfragefehler(500, "web_ui.html fehlt.")
        nonce = secrets.token_urlsafe(16)
        csp = ("default-src 'none'; script-src 'nonce-%(n)s'; style-src 'nonce-%(n)s'; "
               "connect-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'none'; "
               "frame-ancestors 'none'" % {"n": nonce})
        self._senden(200, seite.replace("__NONCE__", nonce).encode("utf-8"),
                     "text/html; charset=utf-8", [("Content-Security-Policy", csp)])

    def _faelle(self, abfrage):
        self._json(200, faelle())

    def _optionen(self, abfrage):
        self._json(200, optionen())

    def _export(self, abfrage):
        self._json(200, export_von(abfrage.get("fall")))

    def _dossier(self, abfrage):
        html = dossier_html(abfrage.get("fall"))
        # Das Dossier ist eigener Inhalt mit eigenem Stil, aber ohne jedes Skript. Nur die
        # eingebettete Fassung darf neue Fenster öffnen (Quellenlinks nach außen); sie erben nichts.
        sandbox = "sandbox"
        if abfrage.get("eingebettet") == "1":
            html = fuer_einbettung(html)
            sandbox += " allow-popups allow-popups-to-escape-sandbox"
        csp = ("default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
               "form-action 'none'; " + sandbox)
        self._senden(200, html.encode("utf-8"), "text/html; charset=utf-8",
                     [("Content-Security-Policy", csp)])

    def _sichern(self, abfrage):
        slug = pruefe_slug(abfrage.get("fall"))
        with tempfile.TemporaryDirectory(prefix="recherche-sichern-") as temp:
            with _fall_lesen(slug) as fall:
                pfad, _anzahl, groesse = sichere_fall(fall, temp)
            name = _NICHT_ZEICHEN.sub("_", pfad.name)
            self._kopf(200, "application/zip", groesse,
                       [("Content-Disposition", 'attachment; filename="%s"' % name)])
            if self.command != "HEAD":
                with open(str(pfad), "rb") as datei:
                    shutil.copyfileobj(datei, self.wfile)

    def _befehl(self, abfrage):
        laenge = self._koerper(MAX_JSON, "application/json")
        try:
            daten = json.loads(self._lies(laenge).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Anfragefehler(400, "Der Körper ist kein gültiges JSON.")
        if not isinstance(daten, dict):
            raise Anfragefehler(400, "Der Körper muss ein JSON-Objekt sein.")
        try:
            ergebnis = fuehre_befehl_aus(daten.get("fall"), daten.get("wer"), daten.get("argv"),
                                         daten.get("eingabe"))
        except Anfragefehler as fehler:
            if fehler.status in (403, 400, 404):
                self._json(fehler.status, {"code": 2, "aus": "", "fehler": "fehler: " + fehler.text})
                return
            raise
        self._json(200, ergebnis)

    def _quelle_datei(self, abfrage):
        laenge = self._koerper(MAX_UPLOAD, "application/octet-stream")
        pruefe_slug(abfrage.get("fall"))  # vor dem Lesen des Bodys
        roh = self._lies(laenge)
        self._json(200, lade_quelle_datei(abfrage.get("fall"), abfrage.get("titel", ""),
                                          abfrage.get("name", ""), roh, abfrage.get("wer"),
                                          abfrage.get("typ")))

    def _laden(self, abfrage):
        laenge = self._koerper(MAX_LADEN, "application/octet-stream")
        wurzel = faelle_wurzel()
        wurzel.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix=".upload-", dir=str(wurzel)))
        self._body_gelesen = True
        try:
            pfad = temp / "akte.zip"
            try:
                with open(str(pfad), "wb") as datei:
                    rest = laenge
                    while rest > 0:
                        stueck = self.rfile.read(min(1024 * 1024, rest))
                        if not stueck:
                            raise Anfragefehler(400, "Anfrage unvollständig.")
                        datei.write(stueck)
                        rest -= len(stueck)
            except OSError as fehler:
                if isinstance(fehler, socket.timeout):
                    raise
                raise Anfragefehler(400, "Das Archiv ließ sich nicht zwischenspeichern: %s" % fehler)
            try:
                slug, zurueck = lade_akte(pfad, "Weboberfläche")
            except Fehler as fehler:
                raise Anfragefehler(400, str(fehler))
        finally:
            shutil.rmtree(str(temp), ignore_errors=True)
        self._json(200, {"slug": slug, "zurueckgesetzt": [aid for aid, _ in zurueck]})

    def _loeschen(self, abfrage):
        laenge = self._koerper(MAX_JSON, "application/json")
        try:
            daten = json.loads(self._lies(laenge).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Anfragefehler(400, "Der Körper ist kein gültiges JSON.")
        if not isinstance(daten, dict):
            raise Anfragefehler(400, "Der Körper muss ein JSON-Objekt sein.")
        self._json(200, {"geloescht": loesche_fall(daten.get("fall"), daten.get("bestaetigung"))})


class Server:
    """Ein laufender Server mit eigenem Token (je Start neu)."""

    def __init__(self, port=0):
        self.token = secrets.token_urlsafe(24)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.app = self
        self.port = self.httpd.server_address[1]
        # Cookies kennen keine Ports; der Name hält Server auf 127.0.0.1 auseinander.
        self.cookie = "recherche_t_%d" % self.port

    @property
    def url(self):
        return "http://127.0.0.1:%d/?t=%s" % (self.port, self.token)

    def serve_forever(self):
        self.httpd.serve_forever()

    def stoppe(self):
        self.httpd.shutdown()
        self.httpd.server_close()


_hintergrund = None
_start_sperre = threading.Lock()


def starte_im_hintergrund(wurzel):
    """Setzt die Fallwurzel dieses Prozesses, startet den Server in einem Daemon-Thread
    auf einem freien Port und gibt Adresse, Port und Token zurück. Ein zweiter Aufruf
    liefert den schon laufenden Server."""
    global _hintergrund
    with _start_sperre:
        os.environ["RECHERCHE_FAELLE"] = str(wurzel)
        Path(str(wurzel)).mkdir(parents=True, exist_ok=True)
        if _hintergrund is None:
            server = Server(0)
            threading.Thread(target=server.serve_forever, name="recherche-web", daemon=True).start()
            _hintergrund = server
        return {"url": _hintergrund.url, "port": _hintergrund.port, "token": _hintergrund.token}
