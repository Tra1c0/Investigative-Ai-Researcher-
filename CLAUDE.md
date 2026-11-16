# Investigative-Ai-Researcher

Eine App für investigative Recherche: Sie führt eine Fallakte, in der jede Aussage an ein wörtliches Zitat aus einer gesicherten Quelle gebunden ist, und arbeitet mit Rollen wie ein Rechercheteam.

Stand 2026-11-16: Kern (Fallakte, Belegprüfung, Dossier), Methode, Rollen, Oberfläche und Android-App stehen. Es fehlen Anbindungen an Register und Datenbanken. Die Android-App ist im Emulator gestartet, aber auf keinem Gerät geprüft.

## Die App

- `recherche/` ist ein Python-Paket ohne Abhängigkeiten außer der Standardbibliothek. Alle Befehle: `python3 -m recherche --help`.
- Die Oberfläche (`python3 -m recherche web`) ist eine einzelne Seite, `recherche/web_ui.html`, vor einem lokalen Server, `recherche/web.py`. Sie führt dieselben Befehle aus wie die Kommandozeile; eine Regel, die nur in der Oberfläche gilt oder dort fehlt, darf es nicht geben.
- Die Android-App unter `android/` verpackt dasselbe Paket mit Chaquopy und zeigt die Oberfläche in einer WebView. Sie enthält keine KI (E-009). Gebaut und im Emulator gestartet wird nur in GitHub Actions (`.github/workflows/apk.yml`); hier in der Entwicklungsumgebung fehlt das Android-SDK.
- Die Methode steht im Skill `/recherche <Thema>` (`.claude/skills/recherche/SKILL.md`). Die Rollen sind Subagenten: `rechercheur` (Sonnet) sammelt, `dokumentar` (Opus) prüft unabhängig, `advocatus` (Opus) sucht dagegen, `justiziar` (Opus) macht die rechtliche Vorprüfung.
- Fallakten liegen unter `faelle/` und kommen nicht ins Git. Das Repository ist öffentlich, und eine Akte kann Namen und Vorwürfe enthalten.
- Tests: `python3 -m unittest discover -s tests`. Kein Test greift auf das Internet zu.
- Warum die App so gebaut ist, steht in `docs/karte/ENTSCHEIDUNGEN.md` (E-006 bis E-010). Die Regeln dort zu Belegen und zum Schutz von Privatpersonen sind keine Stilfragen: Wer sie lockert, macht aus dem Werkzeug ein anderes.

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
