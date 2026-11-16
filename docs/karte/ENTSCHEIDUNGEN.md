# Entscheidungen

Modulübergreifende Entscheidungen und Sackgassen, neueste oben. Format siehe `.claude/rules/karte-format.md`.

## E-008 · 2026-11-16 · Recherchiert werden öffentliche Rollen; Privatpersonen sind geschützt

Kontext: Der Pressekodex verlangt die Abwägung zwischen Informationsinteresse und Persönlichkeitsschutz (Ziffer 8) und die Unschuldsvermutung (Ziffer 13). Bellingcat hält in seinen Standards fest, dass Recherchierende nicht über das Nötige hinausgehen und Privates nur bei gerechtfertigtem öffentlichem Interesse veröffentlichen; ein Fall, in dem ein Unbeteiligter nach Fehlern von Online-Rechercheuren öffentlich bloßgestellt wurde, ist dokumentiert. Das Handelsregister hat keine Schnittstelle und beschränkt den automatisierten Abruf (§ 52 HRV), archive.today lässt keine Automatisierung zu. Alles nur über Suchtreffer geprüft, die Primärquellen waren aus der Sitzung nicht erreichbar.
Entscheidung: Skill und Rollen grenzen die Recherche auf öffentliche Rollen und offen zugängliche Quellen ein. `pruefe` meldet Behauptungen über Privatpersonen, Personen ohne eindeutiges Merkmal und fehlende Stellungnahmen als offen vor einer Veröffentlichung. Webarchive werden nur auf ausdrücklichen Wunsch angefragt, weil die Anfrage verrät, wozu recherchiert wird. Angebunden werden nur Quellen, die maschinellen Zugriff erlauben.
Verworfen: Automatischer Abruf von Handelsregister, Bundesanzeiger und Insolvenzbekanntmachungen. Dafür legt die Recherche Aufgaben für Menschen an.
Erneut prüfen, wenn: eine dieser Quellen eine offizielle Schnittstelle bekommt.

## E-007 · 2026-11-16 · Ein Beleg ist ein wörtliches Zitat aus dem gespeicherten Schnappschuss

Kontext: Untersuchungen zu KI-Recherchewerkzeugen berichten hohe Fehlerquoten bei Quellenangaben: über 60 % falsche Zuordnungen bei KI-Suchmaschinen (Tow Center, 2025), 45 % der Antworten mit erheblichem Mangel und 31 % mit Quellenproblemen (EBU und BBC, 2025), 40 bis 80 % Zitiergenauigkeit bei Deep-Research-Systemen (DeepTRACE). Alle Zahlen stammen aus Suchtreffern, nicht aus den Studien selbst.
Entscheidung: `recherche` nimmt einen Beleg nur an, wenn das Zitat im lokal gespeicherten Text der Quelle steht. Der Status einer Behauptung hat eine Obergrenze, die sich aus Zahl, Unabhängigkeit und Art der Quellen ergibt; Quellen mit gemeinsamem Ursprung zählen als eine. Den Status setzt eine Rolle, die die Überlegungen der Sammlung nicht kennt, und jede spätere Änderung an Behauptung oder Belegen setzt ihn zurück. Das Dossier entsteht aus der Akte, nicht aus freiem Text.
Verworfen: Ein frei geschriebener Bericht mit nachträglichen Quellenangaben. Zusammenfassungen anderer Werkzeuge als Quelle, weil sie den Wortlaut nicht garantieren.
Erneut prüfen, wenn: die Zitatprüfung echte Zitate häufig ablehnt, etwa wegen Zeilenumbrüchen in PDFs. Dann die Normalisierung erweitern, nicht die Prüfung lockern.

## E-006 · 2026-11-16 · Die App ist eine Fallakte mit Prüfregeln plus Rollen in Claude Code

Kontext: Ein Max-Abo deckt Claude Code ab, auch im nichtinteraktiven Betrieb, aber keine API-Nutzung. Auf Anthropics Recherche-Benchmark kostete Fable 5.2 das 4,3-Fache von Sonnet 5.5 ohne messbaren Gewinn; Opus 5.5 lag 2,4 Punkte über Sonnet 5.5 bei 1,5-fachen Kosten ([Doku](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence), abgerufen 2026-11-16). Die Sammlung ist Masse im Sinn von E-005: viele unabhängige Fragen und mehr Lesestoff, als in einen Kontext passt.
Entscheidung: Laufzeit ist Claude Code mit dem Abo. Der Zustand liegt in `faelle/<fall>/fall.db` und wird nur über `python3 -m recherche` verändert. Die Methode steht im Skill `/recherche`, die Rollen sind Subagenten: `rechercheur` auf Sonnet, `dokumentar`, `advocatus` und `justiziar` auf Opus. Die Leitung liegt beim Modell der Sitzung; Fable bringt für die Sammlung keinen gemessenen Vorteil.
Verworfen: Eine eigenständige Web-App mit API-Schlüssel, solange die Methode nicht an echten Fällen geprüft ist; sie würde jede Recherche zusätzlich kosten.
Erneut prüfen, wenn: die App ohne Claude Code oder für andere laufen soll. Die Fallakte bleibt dann dieselbe, nur der Antrieb wechselt.

## E-005 · 2026-11-16 · Delegiert wird Masse, Zusammenhängendes bleibt in einer Hand

Kontext: Anthropics Messungen zu Kosten und Qualität ([Doku](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence), abgerufen 2026-11-16, erste Hälfte der Seite gelesen). Delegation an günstigere Modelle lag nur in zwei Fällen vorn: bei Arbeit, die größer ist als ein Kontextfenster, und bei Routinearbeit mit teuren Ausreißern. Bei einer zusammenhängenden Kette, die in einen Kontext passt, war das Modell des Orchestrators allein mit niedrigerem Effort in jedem gemessenen Fall besser; diese Fälle wurden an Vorgängermodellen gemessen. Auf dem Defektsuche-Benchmark kostete Fable 5.2 als Orchestrator anstelle von Opus 5.5 19 % mehr bei etwa gleichem Ergebnis; allein arbeitend lag Fable 5.2 dort 3,2 bis 7,5 Punkte über dem Gespann mit Sonnet-Subagenten, bei 2,2- bis 3,4-fachen Kosten. Haiku-Subagenten senkten bei Coding die Kosten pro Versuch um 32 % und die Erfolgsquote um etwa 4 Punkte. Mit niedrigem Effort beginnen und nur Fehlschläge höher wiederholen kostete rund 40 % weniger als alles auf `high`, bei gleicher Erfolgsquote, sofern Tests die Fehlschläge sichtbar machen.
Entscheidung: Der Lead zerlegt nicht, was zusammenhängt. Eine zusammenhängende Aufgabe geht als Ganzes an einen Agenten oder bleibt beim Lead; delegiert wird Masse (Suche, Lesen, viele unabhängige Teile, mechanisches Volumen, Review). Günstig beginnen und nach gescheiterter Prüfung eskalieren. Die Qualität delegierter Arbeit ist die des Workers, nicht die des Leads.
Verworfen: Jede Ausführung grundsätzlich abgeben (für zusammenhängende Aufgaben gemessen schlechter). Der Advisor als Standard (im gemessenen Coding-Fall 1,7 Punkte Gewinn am Rand des Rauschens für etwa 2,1-fache Kosten; jeder Aufruf liest den ganzen Verlauf ungecacht).
Erneut prüfen, wenn: ein neues Modell erscheint oder sich die Preisverhältnisse ändern; die Messungen gelten je Modellgeneration.

## E-004 · 2026-11-16 · Lead-Modus startet pro Sitzung, nicht per Voreinstellung

Kontext: Fable-Nutzung wird je nach Tarif unterschiedlich abgerechnet. Auf Pro und Standard-Sitzen ist sie nicht im Kontingent enthalten und läuft über Usage Credits; auf Max, Ultra und Premium-Sitzen sind bis zu 50 % des Wochenlimits für Fable nutzbar, und Fable verbraucht das Limit schneller als andere Modelle, ohne veröffentlichten Faktor ([Support-Artikel](https://support.claude.com/en/articles/15424964-claude-fable-models-on-your-plan), abgerufen 2026-11-16). Im nichtinteraktiven Betrieb rechnet Claude Code Fable ohne Rückfrage über Credits ab ([Doku](https://code.claude.com/docs/en/model-config#fable-and-usage-credits)).
Entscheidung: `.claude/settings.json` setzt kein `"agent": "lead"`. Der Lead startet mit `/lead <Aufgabe>` oder `claude --agent lead`.
Verworfen: Lead als Projektstandard, weil dann jede Sitzung, auch eine triviale oder automatisierte, auf Fable liefe.
Erneut prüfen, wenn: der Tarif Fable ohne Zusatzkosten abdeckt und jede Sitzung im Repo als Lead laufen soll. Dann `"agent": "lead"` in `.claude/settings.json` eintragen.

## E-003 · 2026-11-16 · Modulnotizen liegen unter docs/karte, geladen per Symlink als Regeln

Kontext: `.claude/` ist ein geschützter Pfad. Schreibzugriffe fragen in den Modi `default` und `acceptEdits` nach, werden in `dontAsk` abgelehnt, und Allow-Regeln heben das nicht auf ([Doku](https://code.claude.com/docs/en/permission-modes#protected-paths)). Notizen, die Agenten laufend pflegen sollen, dürfen dort nicht liegen. `.claude/rules/` folgt Symlinks, deren Ziel im Arbeitsverzeichnis liegt ([Doku](https://code.claude.com/docs/en/memory#share-rules-across-projects-with-symlinks)), und lädt Regeln mit `paths` erst, wenn eine passende Datei gelesen oder geändert wird ([Doku](https://code.claude.com/docs/en/memory#path-specific-rules)), auch in Subagenten ([Doku](https://code.claude.com/docs/en/sub-agents#what-loads-at-startup)).
Entscheidung: Notizen unter `docs/karte/module/`, `.claude/rules/karte` ist ein Symlink dorthin.
Verworfen: Notizen direkt unter `.claude/rules/` (Rückfrage bei jeder Aktualisierung). `CLAUDE.md` in jedem Modulverzeichnis (ein Modul müsste genau ein Verzeichnis sein, Tests in einem anderen Baum blieben außen vor, und die Dokumentation läge verstreut).
Erneut prüfen, wenn: das Repo auf einem System ohne Symlinks ausgecheckt wird. Dann lädt die Notiz nicht mehr von selbst; Index und Verweise bleiben.

## E-002 · 2026-11-16 · Veraltete Notizen werden mechanisch erkannt

Kontext: Agenten folgen Kontextdateien auch dann, wenn sie dem Code widersprechen; veraltete Verweise sind in öffentlichen Repos verbreitet. Belege dafür liegen nur aus zweiter Hand vor (Xu und Wu 2026; Treude und Baltes, arXiv 2606.09090), die Primärquellen waren aus der Sitzung nicht erreichbar.
Entscheidung: Jede Notiz trägt einen Inhalts-Fingerabdruck der Dateien ihres Moduls. `tools/karte.py` meldet Module, deren Code sich seit dem Stempel geändert hat, Dateien ohne Notiz und tote Verweise. Ein Hook hält den Agenten, der die Abweichung verursacht hat, einmal pro Problem an. Im Zweifel gilt der Code.
Verworfen: Verankerung an Commit-Hashes (der Hash steht erst nach dem Commit fest und geht bei Squash und Rebase verloren). Ein eigener Kartografen-Agent nach jeder Aufgabe (er müsste neu lesen, was der ausführende Agent schon im Kontext hat).
Erneut prüfen, wenn: der Hook häufig für Änderungen anhält, die keine Notiz berühren. Dann die Module feiner schneiden oder Pfade in `docs/karte/ignoriert.txt` aufnehmen.

## E-001 · 2026-11-16 · Die Karte hält nur fest, was der Code nicht zeigt

Kontext: Eine Studie der ETH Zürich (Gloaguen u. a., arXiv 2602.11988, ICLR 2026) findet laut Abstract, dass Kontextdateien die Erfolgsquote von Coding-Agenten nicht verbessern, die Kosten um über 20 % erhöhen und dass Repository-Überblicke nicht helfen; sie empfiehlt, nur minimale Anforderungen festzuhalten. Geprüft über das ICLR-Verzeichnis und Zusammenfassungen, nicht am Volltext. Eine zweite Studie (Lulla u. a., arXiv 2601.20404) misst mit AGENTS.md kürzere Laufzeit und weniger Tokens, aber keine Korrektheit; ebenfalls nur aus zweiter Hand. Aus erster Hand: Claudes eigene Prüfung `/doctor` streicht aus einer CLAUDE.md, was sich aus dem Code ableiten lässt (Verzeichnislayouts, Architekturüberblicke), und behält Fallstricke, Begründungen und abweichende Konventionen ([Doku](https://code.claude.com/docs/en/memory#my-claude-md-is-too-large)).
Entscheidung: Notizen enthalten Einstiegspunkte, Verträge, Testabdeckung und Sackgassen, als Tatsachen mit Verweis. Der Index pro Sitzung ist eine Zeile pro Modul.
Verworfen: Ein automatisch erzeugter Architekturüberblick in `CLAUDE.md`.
Erneut prüfen, wenn: Sitzungen trotz Karte viele Suchschritte brauchen, um die richtige Stelle zu finden, oder Notizen regelmäßig über 60 Zeilen wachsen.
