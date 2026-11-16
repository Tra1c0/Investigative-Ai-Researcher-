# Projektkarte

Die Karte ist das Gedächtnis des Projekts für Claude-Sitzungen. Sie hält fest, was sich aus dem Code nicht schnell ablesen lässt: wo man in ein Modul einsteigt, welche Verträge gelten, was getestet ist und welche Ansätze schon gescheitert sind. Die Begründung für den Zuschnitt steht in `ENTSCHEIDUNGEN.md` (E-001 bis E-003).

## Was wann geladen wird

| Ebene | Inhalt | Wann im Kontext |
|---|---|---|
| Index | eine Zeile pro Modul (Pfade, Zweck, Zustand, Teststand), Titel der Entscheidungen | zu Beginn jeder Sitzung und jedes Subagenten, per Hook |
| Modulnotiz `module/<modul>.md` | Einstieg, Verträge und Fallstricke, Tests, Sackgassen | sobald eine Datei des Moduls gelesen oder geändert wird |
| `ENTSCHEIDUNGEN.md` | modulübergreifende Entscheidungen mit Begründung | nur wenn jemand sie öffnet |

Das automatische Laden der Notizen läuft über `.claude/rules/karte`, einen Symlink auf `module/`. Jede Notiz ist damit eine Regel, die an die `paths` ihres Moduls gebunden ist.

## Wie die Karte aktuell bleibt

Jede Notiz trägt in `stand` einen Fingerabdruck der Dateien ihres Moduls. `tools/karte.py` vergleicht ihn mit dem aktuellen Inhalt und meldet:

- **VERALTET**: Der Code des Moduls hat sich seit dem letzten Stempel geändert.
- **UNGESTEMPELT**: Die Notiz wurde angelegt, aber noch nicht bestätigt.
- **UNKARTIERT**: Eine Datei gehört zu keinem Modul und steht nicht in `ignoriert.txt`.
- **FEHLER**: Die Notiz verweist auf Pfade oder Symbole, die es nicht gibt, oder ist unvollständig.

Wer Code ändert, hält die Notiz gegen den neuen Stand und stempelt. Vergisst ein Agent das, hält ihn ein Hook beim Beenden an, einmal pro Problem und Sitzung. Abweichungen, die schon vor der Sitzung bestanden, erscheinen nur als Hinweis im Index.

## Befehle

```
python3 tools/karte.py status                 Index und Zustand
python3 tools/karte.py pruefe                 alle Probleme, Exit 1 wenn welche offen sind
python3 tools/karte.py stempel <modul>        Notiz als geprüft bestätigen (--alle für alle)
python3 tools/karte.py test <modul>           Tests des Moduls ausführen und den Lauf vermerken
python3 tools/karte.py neu <modul> <glob>...  Notiz mit Gerüst anlegen
```

`Tests grün` im Index heißt: Die Tests sind auf genau dem aktuellen Stand des Moduls durchgelaufen. Nach jeder weiteren Änderung steht dort `grün@alt`.

## Grenzen

- Ein Stempel belegt, dass jemand bestätigt hat, nicht dass er geprüft hat. Das Werkzeug erkennt geänderten Code und tote Verweise, aber keine inhaltlich falsche Notiz.
- In Cloud-Threads eines Claude-Projekts laufen weder die Hooks noch die pfadgebundenen Regeln. Dort hilft `python3 tools/karte.py status` von Hand.
- Ohne Symlink-Unterstützung im Checkout lädt die Notiz nicht von selbst. Der Index zeigt weiterhin, wo sie liegt.
- Ob der Index Suchschritte spart, ist nicht gemessen. Wer es prüfen will, vergleicht in `/usage` ähnliche Aufgaben mit und ohne den `SessionStart`-Hook.
