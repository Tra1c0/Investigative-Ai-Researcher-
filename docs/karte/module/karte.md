---
paths:
  - "tools/karte.py"
  - "tests/test_karte.py"
zweck: "Prüft und pflegt die Projektkarte: Abgleich, Stempel, Testlauf, Hooks"
tests: "python3 -m unittest discover -s tests -p 'test_karte*.py'"
stand: "c40b4ff13a38"
testlauf: "gruen c40b4ff13a38 2026-11-16"
---
# karte

## Einstieg
- `tools/karte.py:main` verteilt auf die Befehle. `hook` wird vor der Git-Prüfung abgezweigt, weil der Hook außerhalb eines Repos still enden muss.
- `tools/karte.py:Analyse` ist der Kern: Dateiinventar, Prüfung jeder Notiz, unkartierte Dateien, Problemliste. Alle Befehle und der Hook bauen darauf auf.
- `tools/karte.py:check_note` erzeugt die FEHLER einer Notiz und entscheidet über VERALTET und UNGESTEMPELT.
- `tools/karte.py:hook_output` enthält die gesamte Hook-Logik: Index einspeisen, Ausgangszustand merken, beim Beenden anhalten.
- `tests/test_karte.py` baut für jeden Test ein eigenes Git-Repo im Temp-Verzeichnis und ruft das Werkzeug als Prozess auf.

## Verträge und Fallstricke
- Der Hook darf eine Sitzung nie stören: `tools/karte.py:cmd_hook` fängt jede Ausnahme und endet mit 0. Fehler im Hook bleiben deshalb unsichtbar. Zum Debuggen die Eingabe als JSON per Pipe an `python3 tools/karte.py hook` geben und `hook_output` direkt aufrufen.
- Der Fingerabdruck (`tools/karte.py:Projekt`) hasht den Inhalt im Arbeitsverzeichnis, nicht den Commit. Stempeln geht deshalb vor dem Commit, und ein Stempel übersteht Squash und Rebase. Zeilenenden werden auf LF normalisiert, damit ein CRLF-Checkout nicht als Änderung zählt.
- `tools/karte.py:set_frontmatter_value` ändert genau eine Zeile. Claude Code liest die Notizen als echtes YAML (Feld `paths`); alles, was das Werkzeug schreibt, muss gültiges YAML bleiben, sonst lädt die Notiz als Regel ohne Pfadbindung in jeder Sitzung.
- `tools/karte.py:compile_glob` versteht nur eine Teilmenge der Muster, die Claude Code für `paths` kennt. Die Karte nutzt bewusst nur diese Teilmenge, damit Werkzeug und Claude Code dieselben Dateien meinen.
- Gemeldet wird je Agent und Problem einmal pro Sitzung; der Zustand liegt als Datei im Temp-Verzeichnis, benannt nach der `session_id`. Der Schlüssel für VERALTET enthält den Fingerabdruck: Ändert sich das Modul nach einer Meldung weiter, wird erneut gemeldet.
- `tools/karte.py:check_pointer` rät, ob ein Ausdruck in Backticks ein Pfad ist: erstes Segment existiert in der Repo-Wurzel, oder der Ausdruck hat einen Schrägstrich und eine Dateiendung. Brüche mit Dezimalpunkt in Backticks werden dadurch fälschlich als tote Verweise gemeldet.
- `test` führt den Befehl aus dem Feld `tests` über die Shell aus. Deshalb fehlt `test` in den Allow-Regeln von `.claude/settings.json`: Sonst könnte ein Agent über dieses Feld beliebige Befehle ohne Rückfrage starten.

## Tests
- Abgedeckt: Glob-Tabelle, die Schreibweisen des Frontmatters, Stempel ändert nur eine Zeile, Veralten und CRLF, unkartierte und ignorierte Dateien, Verweisprüfung, Testlauf grün und rot, alle vier Hook-Ereignisse.
- Lücken: nur mit Python 3.13 gelaufen, nicht mit 3.9. Kein Test mit sehr großen Repos. Dass Claude Code die Hooks und die verknüpften Regeln lädt, prüft kein automatischer Test.

## Sackgassen
- (keine)
