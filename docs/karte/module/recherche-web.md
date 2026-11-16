---
paths:
  - "recherche/web.py"
  - "recherche/web_ui.html"
  - "tests/test_recherche_web.py"
zweck: "Lokale Weboberfläche der Fallakte: Python-Server, eine HTML-Seite, Schnittstelle für die Android-Hülle"
tests: "python3 -m unittest discover -s tests -p 'test_recherche_web.py'"
testlauf: "gruen fcdd441283f6 2026-11-16"
stand: "fcdd441283f6"
---
# recherche-web

## Einstieg
- `recherche/web.py:Server` ist der HTTP-Server (nur 127.0.0.1, Token je Start); `recherche/web.py:_Handler._verteile` legt die Reihenfolge der Prüfungen fest: Host, Ursprung bei POST, Token, Route.
- `recherche/web.py:fuehre_befehl_aus` führt die Kommandozeile im Prozess aus (`recherche/web.py:_lauf` über `recherche/cli.py:main`); `recherche/web.py:pruefe_argv` weist ab, womit der Client einen Pfad wählen könnte.
- `recherche/web.py:starte_im_hintergrund`, `recherche/web.py:exportiere`, `recherche/web.py:importiere` und `recherche/web.py:dossier_datei` ruft die Android-Hülle beim Namen auf (siehe android-huelle); umbenennen bricht die App.
- `recherche/web_ui.html` ist die ganze Oberfläche (CSS und JS inline, Nonce-Platzhalter `__NONCE__`, den der Server je Antwort ersetzt).

## Verträge und Fallstricke
- Der Client wählt nie einen Pfad: `pruefe_argv` lehnt `quelle datei`, `fall sichern`, `fall laden`, `web`, `--datei` und `--ziel` samt Abkürzungen ab (argparse nimmt `--dat`), Uploads gehen als Temp-Datei mit vom Server gebildetem Namen durch `quelle datei`, Slugs kommen nur aus `faelle_liste`. Ein neuer Befehl mit Pfadoption muss in `pruefe_argv` aufgenommen werden.
- Die Seite rechnet keine Regel nach; Status, Obergrenze und Probleme kommen aus `/api/export`. Nur Bereitschaftszeile, Gruppierung und Reihenfolge der Behauptungen spiegeln `recherche/dossier.py` (zwei Stellen, bei Änderung dort anpassen).
- Der Textleser parst die Ausgabe von `quelle lesen` (Fußzeile `-- Zeichen a bis b von n`, Trefferköpfe `[Zeichen a-b]`); ändert sich das Format in `recherche/cli.py:quelle_lesen`, bricht die Seite. Positionen zählen Unicode-Zeichen wie Python, nicht UTF-16 (`nimmZeichen`).
- Werte gehen immer als `--name=wert` an die Kommandozeile, sonst liest argparse ein Wort mit führendem `-` als Option.
- Befehle laufen nacheinander unter `_SPERRE`, weil `_lauf` `sys.stdin`, `sys.stdout` und `sys.stderr` des Prozesses austauscht. Befehle müssen darum über `sys.stdin` lesen und dürfen nur argparse beenden.
- Der Cookie-Name trägt den Port, weil Cookies Ports nicht trennen und zwei Server auf 127.0.0.1 sich sonst das Token überschreiben.
- Die Dossier-Antwort hat eine eigene CSP (kein Skript). Nur `?eingebettet=1` bekommt `recherche/web.py:fuer_einbettung` (`<base target="_blank">`, interne Sprünge `target="_self"`) und `allow-popups` in der CSP-Sandbox; die Datei aus `dossier_datei` bleibt das unveränderte Dossier.
- `behauptung setzen` hat kein `--hypothese`: Die Hypothese einer Behauptung lässt sich nur beim Anlegen setzen, das Bearbeiten-Formular zeigt sie nicht.
- Die Markierung im Quelltext wird bei `selectionchange` gemerkt, weil ein Tipp auf „Als Beleg übernehmen“ sie auflösen kann, bevor der Klick ankommt.
- Die CLI schließt ihre Datenbankverbindungen erst beim Aufräumen; `_lauf` unterdrückt die dabei entstehende ResourceWarning, sonst stünde sie im Fehlertext.

## Tests
- Abgedeckt: Token und Cookie, Host- und Ursprungsprüfung, Köpfe auf jeder Antwort, CSP samt Nonce, Größengrenzen, Befehl mit Code, Ausgabe und deutschem Fehler, jede verbotene Option und jeder verbotene Befehl ohne Wirkung, Zitat von stdin mit Sonderzeichen, Upload, Sichern und Laden über HTTP und über die Python-Funktionen, ungültige Slugs, eingebettetes Dossier, Textprüfung der Seite (keine fremden Ressourcen, kein innerHTML).
- Von Hand geprüft am 2026-11-16 mit Chromium (Playwright) bei 390 und 1280 px an einer Kopie von `faelle/selbsttest-fable`: kein waagerechtes Scrollen, Quelle per Text, Beleg aus Auswahl, Behauptung, Prüfung, Suche, Textseiten, Dossier im Rahmen, Klick auf Quellenlink im Dossier öffnet neuen Tab, `window.Android` als Attrappe.
- Lücken: keine Prüfung in der echten Android-WebView; Markierung per Langdruck mit dem Finger nur über die Selection-API nachgestellt; kein Test des JavaScripts selbst (nur Textprüfung und Browserlauf von Hand); nicht unter Python 3.9 gelaufen.

## Sackgassen
- (keine)
