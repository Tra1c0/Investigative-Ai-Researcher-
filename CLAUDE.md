# Investigative-Ai-Researcher

Stand 2026-11-16: Das Repository enthält bisher nur die Arbeitsumgebung für Claude (Agenten, Projektkarte, Prüfwerkzeug). Sobald das eigentliche Projekt Build- und Testbefehle hat, gehören sie hierher.

## Projektkarte

`docs/karte/` ist das Gedächtnis des Projekts über Sitzungen hinweg: pro Modul eine Notiz mit Einstiegspunkten, Verträgen, Testabdeckung und bekannten Sackgassen, dazu `docs/karte/ENTSCHEIDUNGEN.md` für alles Modulübergreifende.

- Der Index steht zu Sitzungsbeginn im Kontext. Fehlt er: `python3 tools/karte.py status`.
- Die Notiz eines Moduls (`docs/karte/module/<modul>.md`) lädt von selbst, wenn du eine seiner Dateien liest oder änderst.
- Der Code gilt. Widerspricht ihm eine Notiz, ist die Notiz falsch und wird korrigiert.
- Nach Codeänderungen: Notiz gegen den neuen Stand halten, anpassen, `python3 tools/karte.py stempel <modul>`. Neue Dateien einem Modul zuordnen. Verworfene Ansätze als Sackgasse eintragen.
- Tests eines Moduls: `python3 tools/karte.py test <modul>`. Bei Erfolg kommt eine Zeile, und der Lauf wird vermerkt.
- Prüfen, ob alles stimmt: `python3 tools/karte.py pruefe`.

Das Format der Notizen steht in `.claude/rules/karte-format.md` und lädt beim Öffnen einer Datei unter `docs/karte/`.

## Arbeitsteilung

Der Lead-Modus (`/lead <Aufgabe>` in einer Sitzung oder `claude --agent lead` im Terminal) lohnt sich für Aufgaben mit Masse: breite Suche, viele unabhängige Teile, mehr Arbeit, als in einen Kontext passt. Der Lead plant, stuft ein, delegiert und prüft; die Regeln stehen in `.claude/agents/lead.md`. Eine zusammenhängende Aufgabe, die in einen Kontext passt, erledigt ein Modell allein günstiger und besser (E-005).

| Agent | Modell | Aufgabe |
|---|---|---|
| `scout` | Haiku | nachsehen, suchen, zusammenfassen; ändert nichts |
| `worker` | Sonnet, bei Bedarf Opus | implementieren, testen, Karte pflegen |
| `reviewer` | Opus | unabhängiges Review riskanter Änderungen |
| `thinker` | Fable | offene Entscheidungen, keine Umsetzung |
