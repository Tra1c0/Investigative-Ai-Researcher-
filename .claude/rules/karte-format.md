---
paths:
  - "docs/karte/**"
---

# Projektkarte bearbeiten

Eine Modulnotiz hält fest, was man dem Code nicht in einer Minute ansieht. Sie wird bei jeder Arbeit am Modul mitgeladen, jede Zeile kostet also in jeder künftigen Sitzung. Schreib nur hinein, was dort jemandem einen Umweg oder einen Fehler erspart.

## Aufbau einer Notiz (`docs/karte/module/<modul>.md`)

Frontmatter:

- `paths`: Globs der Dateien, die zum Modul gehören, Code und zugehörige Tests. Verzeichnisse als `pfad/**`.
- `zweck`: eine Zeile, wozu das Modul da ist.
- `tests`: Shell-Befehl ab Repo-Wurzel, der die Tests des Moduls ausführt. Weglassen, wenn es keine gibt.
- `stand` und `testlauf` setzt nur das Werkzeug. Nicht von Hand ändern.

Abschnitte:

- **Einstieg**: wo man zu lesen anfängt, drei bis sieben Verweise mit je einem Halbsatz.
- **Verträge und Fallstricke**: Invarianten, Reihenfolgen, Annahmen über Daten, Dinge, die harmlos aussehen und es nicht sind, jeweils mit dem Grund.
- **Tests**: was abgedeckt ist und welche Lücken bekannt sind.
- **Sackgassen**: Ansätze, die versucht wurden und nicht funktionieren.

## Was hineingehört und was nicht

- Tatsachen mit Verweis, keine Anweisungen. „`src/x.py:laden` cached pro Prozess, deshalb sehen Tests alte Werte“ statt „Cache immer leeren“.
- Verweise in Backticks als `pfad` oder `pfad:Symbol`. Das Werkzeug prüft, ob Pfad und Symbol existieren. Keine Zeilennummern, sie veralten beim nächsten Edit.
- Nicht hinein: Verzeichnislisten, Signaturen, Abhängigkeitslisten, alles, was eine Suche in Sekunden liefert. Auch kein Arbeitsverlauf, der steht in den Commits.
- Richtwert sind höchstens 60 Zeilen. Wird eine Notiz länger, ist das Modul meist zwei Module.

## Sackgassen

Eine Zeile pro Eintrag:

`- JJJJ-MM-TT · <Ansatz> · gescheitert an <Grund> · Beleg: <Commit, Test oder Datei> · erneut prüfen, wenn <Bedingung>`

Sackgassen werden nicht gelöscht. Ist eine überholt, häng `(überholt JJJJ-MM-TT: <Grund>)` an. Eine Sackgasse ohne Grund und Beleg ist nur eine Meinung und hält den Nächsten zu Unrecht ab.

## Stempeln

`python3 tools/karte.py stempel <modul>` heißt: Ich habe diese Notiz gegen den aktuellen Code gehalten, und sie stimmt. Stempeln, ohne das getan zu haben, macht die Karte wertlos, weil ihr danach niemand mehr trauen kann. Vorher `python3 tools/karte.py pruefe`; mit toten Verweisen oder offenen Platzhaltern lässt sich nicht stempeln.

Ein neues Modul legst du mit `python3 tools/karte.py neu <modul> <glob>... --zweck "..." --tests "..."` an und füllst das Gerüst.

## Entscheidungen (`docs/karte/ENTSCHEIDUNGEN.md`)

Nur für das, was mehrere Module betrifft. Neue Einträge oben, fortlaufend nummeriert:

```
## E-NNN · JJJJ-MM-TT · Titel

Kontext: woraus sich die Frage ergab, mit Belegen.
Entscheidung: was gilt.
Verworfen: Alternativen, jeweils mit Grund.
Erneut prüfen, wenn: Bedingung.
```

Der Titel erscheint im Index jeder Sitzung. Er soll für sich allein sagen, was gilt.
