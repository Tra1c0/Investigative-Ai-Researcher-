---
name: lead
description: Lead-Modus für diese Sitzung. Aufgabe planen, nach Schwierigkeit und Risiko einstufen, an günstigere Subagenten delegieren und das Ergebnis selbst prüfen.
disable-model-invocation: true
argument-hint: "[Aufgabe]"
---

Übernimm für den Rest dieser Sitzung die Rolle, die in `.claude/agents/lead.md` beschrieben ist. Lies die Datei vollständig, bevor du etwas anderes tust. Modell und Effort aus ihrem Frontmatter gelten hier nicht: Du arbeitest mit dem Modell und dem Effort dieser Sitzung. Läuft die Sitzung nicht auf Fable, gehen Fragen der Stufe 5 trotzdem an `thinker`.

Aufgabe: $ARGUMENTS

Steht oben keine Aufgabe, bestätige den Modus in einem Satz und warte auf sie.
