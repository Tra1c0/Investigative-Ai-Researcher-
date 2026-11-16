---
paths:
  - "recherche/web.py"
  - "recherche/web_ui.html"
  - "tests/test_recherche_web.py"
zweck: "Lokale Weboberfläche der Fallakte: Python-Server, eine HTML-Seite, Schnittstelle für die Android-Hülle"
tests: "python3 -m unittest discover -s tests -p 'test_recherche_web.py'"
testlauf: "gruen f5a7bf1fa981 2026-11-16"
stand: "f5a7bf1fa981"
---
# recherche-web

## Einstieg
- `recherche/web.py:Server` ist der HTTP-Server (nur 127.0.0.1, Token je Start); `recherche/web.py:_Handler._verteile` legt die Reihenfolge der Prüfungen fest: Host, Ursprung bei POST, Token, Route.
- `recherche/web.py:fuehre_befehl_aus` führt die Kommandozeile im Prozess aus: `recherche/web.py:_lauf` parst mit `recherche/cli.py:baue_parser`, `recherche/web.py:_pruefer` prüft die Namespace gegen `recherche/web.py:ERLAUBT`, dann läuft genau sie über `recherche/cli.py:fuehre_aus`.
- `recherche/web.py:starte_im_hintergrund`, `recherche/web.py:exportiere`, `recherche/web.py:importiere` und `recherche/web.py:dossier_datei` ruft die Android-Hülle beim Namen auf (siehe android-huelle); umbenennen bricht die App.
- `recherche/web_ui.html` ist die ganze Oberfläche (CSS und JS inline, Nonce-Platzhalter `__NONCE__`, den der Server je Antwort ersetzt).

## Verträge und Fallstricke
- Der Client wählt nie einen Pfad, und das lässt sich nur an der geparsten Namespace sichern, nicht an der Rohliste: argparse nimmt ab Python 3.13, dem Python der App, `--` zwischen Bereich und Aktion (`["fall","--","laden",x]` war ein Weg an jeder Prüfung von `argv[:2]` vorbei; bis 3.12 lehnt der Parser das selbst ab) und Abkürzungen (`--dat`). Darum gilt: Erlaubt sind nur die Paare in `ERLAUBT` (Standard ist Ablehnen), `pfad`, `datei` und `ziel` müssen leer sein, `fall` und `wer` müssen die des Servers sein, und ohne Fall läuft nur `fall neu` und `fall liste` (sonst nähme die Kommandozeile den einzigen Fall von selbst). `pruefe_argv` ist nur die billige erste Stufe. Ein neuer Befehl der Seite gehört in `ERLAUBT`; ein Test liest die Paare aus `recherche/web_ui.html` und bricht bei Abweichung.
- Fall, Name und Titel stehen als `--fall=`, `--wer=`, `--titel=` im Aufruf; ein Wert mit führendem `-` wäre sonst eine Option und ließe jeden Befehl scheitern. Uploads gehen als Temp-Datei mit vom Server gebildetem Namen durch `quelle datei` (eigene Prüfung der Namespace in `lade_quelle_datei`).
- Löschen gibt es nur als `POST /api/loeschen` (`recherche/web.py:loesche_fall`: Fall und Bestätigung sind derselbe vorhandene Slug, Umbenennen im Fallverzeichnis, dann Entfernen). Es ist weder Befehl der Kommandozeile noch über `befehl` erreichbar; Agenten sollen Fallakten nicht löschen können.
- `recherche/web.py:importiere` gibt den Text für den Nutzer zurück („Akte geladen: <slug>“, bei Rücksetzungen mit Zahl und IDs), nicht den Slug; die Android-Hülle zeigt ihn unverändert. `/api/laden` liefert `slug` und `zurueckgesetzt`.
- Beim Start entfernt der Server Arbeitsverzeichnisse, die seit gestern liegen (`recherche/store.py:raeume_arbeitsverzeichnisse`), und `loesche_fall` meldet 500, wenn sich nicht alles entfernen ließ: Solche Reste enthalten eine ganze Akte und stehen in keiner Liste.
- Jede Verbindung hat ein Lesetimeout (`LESE_TIMEOUT`). Es gilt je Lesevorgang: Ein lokaler Client, der alle paar Sekunden ein Byte schickt, hält seinen Thread weiter, und die Zahl der Threads ist nicht begrenzt. Erreichbar ist das nur für Programme auf demselben Gerät. Antwortet der Server vor dem Lesen eines Körpers, schließt `_lingern` erst die Senderichtung; ein Schließen mit ungelesenen Daten löst RST aus, das die Antwort beim Client vernichten kann. Tests zu großen Körpern erklären darum nur die Länge und senden keinen Körper.
- IDs aus der Akte werden nur zu DOM-IDs, wenn sie die Form `^[A-Z]\d+$` haben, und `window.Android` gilt nur mit Funktion `oeffneExtern`; eine importierte Akte mit ID wie `fuss` oder `Android` überdeckt sonst Seitenelemente und die Brücke.
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
- Abgedeckt: zwei Stufen der Befehlsprüfung samt `--`, Abkürzungen, Namen und Titeln mit `-` am Anfang, Laden mit zurückgesetztem Status, Löschen mit falscher und richtiger Bestätigung, Lesetimeout, Token und Cookie, Host- und Ursprungsprüfung, Köpfe auf jeder Antwort, CSP samt Nonce, Größengrenzen, Befehl mit Code, Ausgabe und deutschem Fehler, jede verbotene Option und jeder verbotene Befehl ohne Wirkung, Zitat von stdin mit Sonderzeichen, Upload, Sichern und Laden über HTTP und über die Python-Funktionen, ungültige Slugs, eingebettetes Dossier, Textprüfung der Seite (keine fremden Ressourcen, kein innerHTML).
- Von Hand geprüft am 2026-11-16 mit Chromium (auch Löschen, Statuswarnung, beide Android-Knopfvarianten, Ladehinweis) (Playwright) bei 390 und 1280 px an einer Kopie von `faelle/selbsttest-fable`: kein waagerechtes Scrollen, Quelle per Text, Beleg aus Auswahl, Behauptung, Prüfung, Suche, Textseiten, Dossier im Rahmen, Klick auf Quellenlink im Dossier öffnet neuen Tab, `window.Android` als Attrappe.
- Lücken: in der Android-WebView ist nur der Start geprüft (im Emulator erscheint die Fallliste, siehe android-huelle), keine Bedienung; Markierung per Langdruck mit dem Finger nur über die Selection-API nachgestellt; kein Test des JavaScripts selbst (nur Textprüfung und Browserlauf von Hand).

## Sackgassen
- 2026-11-16 · Befehle der Seite an der Rohliste prüfen (`argv[:2]` gegen eine Verbotsliste, Optionen am Präfix) · gescheitert an argparse ab Python 3.13: `["quelle","--","datei","/etc/passwd"]` legte eine beliebige lesbare Datei als Quelle an, `["fall","--","laden",x]` lud ein Zip von jedem Pfad · Beleg: Sicherheitsreview in der Sitzung, `tests/test_recherche_web.py:Befehlspruefung` · erneut prüfen, wenn nie: geprüft wird die geparste Namespace gegen eine Erlaubtliste
