# Investigativ-Rechercheagent

Eine App für investigative Recherche mit Claude Code. Sie arbeitet in Rollen wie ein Rechercheteam und führt eine Fallakte, in der jede Aussage an ein wörtliches Zitat aus einer gesicherten Quelle gebunden ist. Das Ergebnis ist ein Dossier, das zu jeder Aussage zeigt, wie belastbar sie ist und worauf sie beruht.

## Was die App erzwingt

Die bekannten Schwächen von KI-Recherche sind erfundene oder falsch zugeordnete Zitate, eine Meldung, die als mehrere Bestätigungen gezählt wird, und Verdacht, der als Tatsache dasteht. Die Fallakte schließt das technisch aus oder macht es sichtbar:

- **Zitate werden geprüft.** Ein Beleg wird nur angenommen, wenn das Zitat wörtlich im lokal gespeicherten Text der Quelle steht.
- **Der Status hat eine Obergrenze.** „Belegt“ braucht ein amtliches Originaldokument oder zwei voneinander unabhängige, zuverlässige Quellen. Quellen mit gemeinsamem Ursprung zählen als eine.
- **Geprüft wird getrennt.** Den Status setzt eine Rolle, die die Überlegungen der Sammlung nicht kennt. Ändert sich danach etwas an Behauptung oder Belegen, gilt sie wieder als ungeprüft.
- **Gegenrecherche ist Pflicht.** Eine Hypothese lässt sich nicht bewerten, solange keine Suche nach Widerspruch protokolliert ist.
- **Betroffene sind geschützt.** Die Akte meldet Behauptungen über Privatpersonen, Zuordnungen allein über den Namen und belastende Aussagen ohne Stellungnahme als offen vor einer Veröffentlichung.

## Ablauf einer Recherche

`/recherche <Thema oder Auftrag>` in einer Claude-Code-Sitzung in diesem Repository.

1. Auftrag klären, Fall anlegen
2. Vorrecherche, Hypothesen mit Gegenhypothese, Rechercheplan. Hier hält die App an und legt dir den Plan vor.
3. Sammlung: je Frage ein `rechercheur`, parallel
4. Prüfung jeder Behauptung durch den `dokumentar`
5. Auswertung: Chronologie, Beziehungen, Belege gegen alle Hypothesen
6. Gegenprüfung durch den `advocatus`
7. Rechtliche Vorprüfung und Konfrontationsfragen durch den `justiziar`
8. Dossier unter `faelle/<fall>/dossier.html` und `dossier.md`

Die Akte lässt sich auch von Hand führen und einsehen:

```
python3 -m recherche fall zeigen          Überblick über den Fall
python3 -m recherche behauptung liste     alle Behauptungen mit Status
python3 -m recherche pruefe               was offen ist, nach Dringlichkeit
python3 -m recherche dossier              Dossier neu erzeugen
python3 -m recherche --help               alle Befehle
```

## Voraussetzungen

- Claude Code und Python ab 3.9. Für PDFs `pdftotext` oder `pypdf`, sonst nichts.
- **Netzzugriff auf die Seiten, die gelesen werden sollen.** In einer Cloud-Sitzung mit eingeschränktem Netz kann die App keine Quellen sichern und damit nichts belegen. Die Websuche allein reicht nicht, weil Suchtreffer keinen Wortlaut garantieren.
- Fallakten liegen unter `faelle/` und werden nicht ins Git übernommen. Sie können Namen und Vorwürfe enthalten.

## Was die App nicht kann

- Mit Menschen sprechen, Informanten gewinnen, vor Ort recherchieren, Akten einsehen, Auskunftsansprüche durchsetzen. Sie bereitet das vor und legt es als Aufgaben für Menschen an.
- Die Echtheit von Dokumenten, Fotos und Videos prüfen.
- Seiten lesen, die ihren Inhalt erst per JavaScript laden oder hinter einer Bezahlschranke liegen.
- Rechtlich prüfen. Die Vorprüfung macht sichtbar, wo es heikel wird; vor einer Veröffentlichung braucht es einen Anwalt.
- Handelsregister, Bundesanzeiger und ähnliche Quellen automatisch abfragen, wo das nicht erlaubt ist.

Ob die Ergebnisse an die eines Rechercheteams heranreichen, ist bisher nicht an echten Fällen gemessen.

## Entwicklung

Tests: `python3 -m unittest discover -s tests`. Wie das Repository für die Arbeit mit Claude eingerichtet ist, steht in `CLAUDE.md`, die Begründungen für den Aufbau in `docs/karte/ENTSCHEIDUNGEN.md`.
