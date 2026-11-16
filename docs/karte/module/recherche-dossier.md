---
paths:
  - "recherche/dossier.py"
  - "tests/test_dossier.py"
  - "tests/daten/**"
zweck: "Erzeugt aus dem Export einer Fallakte das Dossier als Markdown und HTML"
tests: "python3 -m unittest discover -s tests -p 'test_dossier*.py'"
testlauf: "gruen 131d30094b48 2026-11-16"
stand: "131d30094b48"
---
# recherche-dossier

## Einstieg
- `recherche/dossier.py:render_markdown` und `recherche/dossier.py:render_html` sind die ganze Schnittstelle: reine Funktionen des Export-Dicts.
- `recherche/dossier.py:_Ansicht` bereitet die Daten einmal für beide Formate auf: IDs auflösen, Behauptungen gruppieren und sortieren, Bereitschaftszeile, Zählungen. Reihenfolgen und Zählregeln werden nur hier geändert.
- `recherche/dossier.py:_Html` baut das HTML, die Funktionen mit dem Präfix `_md_` das Markdown.
- `tests/daten/dossier_beispiel.json` ist ein vollständiger erfundener Fall, an dem alle Tests hängen.

## Verträge und Fallstricke
- Die Eingabe ist das Exportformat von `python3 -m recherche export`. Das Modul importiert nichts aus dem Paket, damit es ohne Fallakte testbar bleibt; die Tests laden es deshalb über den Dateipfad.
- Quelleninhalte kommen aus dem Web und gelten als nicht vertrauenswürdig. Im HTML geht jeder Wert durch `recherche/dossier.py:e`, Links entstehen nur über `recherche/dossier.py:h_url`, das ausschließlich Adressen mit http oder https verlinkt. Wer einen Wert direkt in einen f-String setzt, öffnet eine Lücke: `tests/test_dossier.py:HtmlSicherheit` prüft nur die Felder, die die Fixture mit Schadcode füllt.
- Das HTML enthält kein Skript und lädt nichts nach. Es muss als Datei ohne Netz und als Artifact funktionieren.
- `prueft` und `widerlegt` einer Hypothese sind frei formulierte Sätze, keine IDs. Sie wurden einmal als Verweise dargestellt und erschienen dann als „unbekannt“.
- Jede ID bekommt genau einen Anker (`recherche/dossier.py:_Html`, Methode `anker`). Ein Beleg, den mehrere Behauptungen nutzen, wird jedes Mal ausgeschrieben, verlinkt aber ab dem zweiten Mal auf das erste Vorkommen.
- Die Obergrenze einer Behauptung erscheint nur, wenn ihr Status darunter liegt oder sie ungeprüft ist (`recherche/dossier.py:zeige_obergrenze`).
- Belege, die keine Behauptung nutzt, stehen unter „Belege ohne Behauptung“, damit Verweise aus Chronologie und Beziehungen ein Ziel haben.
- Der Seitentext darf überall umbrechen (`overflow-wrap:anywhere` am `body`). Eine Tabelle scrollt deshalb nie seitlich, sie schrumpft: Jede weitere Spalte macht alle Zellen schmaler. Das Quellenverzeichnis ist darum eine Liste von Karten, und `recherche/dossier.py:_Html` schreibt in `tabelle` den Spaltennamen an jede Zelle, damit Zeilen unter 40rem Breite zu Blöcken werden.

## Tests
- Abgedeckt: beide Formate auf der Fixture, auf leeren Listen und auf fehlenden Werten; Bereitschaftszeile; Verweise in der Kurzfassung; Reihenfolgen; Schadcode in Werten und Adressen; genau ein Anker je ID und keine toten internen Links; Quellen als Karten mit Anker und Link, Spaltennamen an den Tabellenzellen; Markdown-Sonderzeichen in Tabellen; Zuschreibungen; die Zahlen im Abschnitt Methode.
- Von Hand geprüft am 2026-11-16: Die Fixture wurde in Chromium bei 390 und 1280 Pixeln Breite, hell und dunkel, gerendert; kein seitliches Scrollen, Status-Marken und Zitate lesbar. Übersehen wurde dabei das Quellenverzeichnis, siehe Sackgassen. Nach dessen Umbau erneut bei 390 Pixeln am Selbsttest-Fall angesehen: Quellenkarten und die gestapelte Akteurstabelle sind lesbar, die Adressen stehen in ganzen Zeilen. Das ist kein automatischer Test.
- Lücken: Die Markdown-Ausgabe wurde nie auf GitHub angesehen. Nicht unter Python 3.9 gelaufen.

## Sackgassen
- 2026-11-16 · Quellenverzeichnis als Tabelle mit fünfzehn Spalten · gescheitert an der Breite: bei 390 Pixeln war die Spalte mit der Adresse etwa 13 Pixel breit und über 1400 Pixel hoch, die Links kaum zu treffen; bei voller Breite bleiben rechnerisch rund 50 Pixel je Spalte (46rem durch fünfzehn) · Beleg: Browser-Prüfung der Oberfläche in der Sitzung, `tests/test_dossier.py:HtmlAufSchmalemBildschirm` · erneut prüfen, wenn nie für das Quellenverzeichnis; bei anderen Tabellen ab etwa sieben Spalten gleich Karten nehmen
