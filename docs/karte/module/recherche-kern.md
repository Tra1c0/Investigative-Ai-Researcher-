---
paths:
  - "recherche/__init__.py"
  - "recherche/__main__.py"
  - "recherche/cli.py"
  - "recherche/store.py"
  - "recherche/quellen.py"
  - "recherche/bewertung.py"
  - "tests/test_recherche_*.py"
zweck: "Fallakte der Recherche: Speicher, Befehle, Quellenabruf mit Zitatprüfung, Statusregeln, Integritätsprüfung"
tests: "python3 -m unittest discover -s tests -p 'test_recherche*.py'"
stand: "ea748d035e6c"
testlauf: "gruen ea748d035e6c 2026-11-16"
---
# recherche-kern

## Einstieg
- `recherche/cli.py:baue_parser` enthält alle Befehle mit ihren Optionen an einer Stelle; `recherche/cli.py:main` fängt `Fehler` ab und macht daraus Meldung und Exit-Code.
- `recherche/store.py:Fall` ist der Zugriff auf `fall.db`. Geschrieben wird nur innerhalb von `schreiben`, IDs kommen aus `neue_id` in derselben Transaktion.
- `recherche/quellen.py:hole_url` und `recherche/quellen.py:lege_quelle_an` sind Abruf und Schnappschuss, `recherche/quellen.py:finde_teile` die Zitatprüfung.
- `recherche/bewertung.py:obergrenze` ist die Statusregel als reine Funktion, `recherche/bewertung.py:pruefe` die Integritätsprüfung in Ausgabereihenfolge, `recherche/bewertung.py:export_daten` das Exportformat.

## Verträge und Fallstricke
- Die Regeln zu Zitatprüfung und Obergrenze sind der Zweck des Werkzeugs (E-007), keine Bequemlichkeitsgrenzen. Wird eine gelockert, steht im Dossier „belegt“, wo es die Belege nicht tragen.
- Verglichen wird ein Zitat in normalisierter Form (`recherche/quellen.py:normalisiere_mit_karte`), gespeichert wird seine Position aber im gespeicherten Text, wie `quelle lesen` ihn zählt. Beides zu mischen war ein Fehler der ersten Fassung, siehe Sackgassen.
- Jede Änderung an Text, Art, Belegen, Prämissen, Zuschreibung oder Klärung einer Behauptung setzt ihre Prüfung zurück, ebenso eine Änderung an Quelle oder Beleg, durch die die Obergrenze unter den Status sinkt (`recherche/bewertung.py:nach_aenderung`). Ein neuer Änderungsweg, der das nicht aufruft, lässt einen geprüften Status stehen, den die Belege nicht mehr tragen.
- Das Exportformat ist der Vertrag mit `recherche/dossier.py`. Ein neues Feld muss dort als fehlend verkraftet werden, sonst bricht das Dossier bei alten Akten.
- `recherche/quellen.py:pruefe_ziel` lehnt interne Adressen ab, auch als Ziel einer Umleitung. Scheitert die Namensauflösung, lässt es den Abruf zu, weil hinter einem Proxy nur dieser auflösen kann.
- Webarchive werden nur mit `--archiv` oder `--sichern` angefragt, weil die Anfrage verrät, wozu recherchiert wird (E-008).
- Aus HTML wird der gesamte sichtbare Text übernommen, samt Navigation; eine Erkennung des Hauptinhalts gibt es nicht. Seiten, die ihren Inhalt per JavaScript laden, liefern fast nichts und lösen die Warnung unter 200 Zeichen aus.
- `recherche/cli.py:web` startet die Weboberfläche (siehe recherche-web), die `recherche/cli.py:main` im selben Prozess aufruft. Befehle dürfen darum nur über `sys.stdin` lesen und nur argparse darf beenden. Die Seite erlaubt nur Paare aus `recherche/web.py:ERLAUBT`; ein neuer Befehl ist dort ohne Eintrag gesperrt, ein neuer Pfadparameter muss `pfad`, `datei` oder `ziel` heißen, sonst prüft `recherche/web.py:_pruefer` ihn nicht.
- Eine geladene Akte kann Status tragen, die ihre Belege nicht tragen (das Archiv ist nur eine SQLite-Datei). `recherche/bewertung.py:lade_akte` ist darum der einzige Weg, eine Akte zu laden (CLI und Weboberfläche). Die Datenbank aus dem Archiv wird gelesen, nie benutzt: `recherche/store.py:_uebernimm` schreibt ihre Zeilen in eine frische mit dem eigenen `SCHEMA`. Geprüft wird, solange die Akte noch im Arbeitsverzeichnis liegt: Aufbau der Datenbank, Daten (`recherche/store.py:pruefe_inhalt`: Typen, IDs, Verweise nur auf vorhandene Objekte der richtigen Art, bekannte Werte, Zähler), dann werden unzulässige Status zurückgesetzt (`recherche/bewertung.py:status_unzulaessig`, hier auch bei ungeklärtem Gegenbeleg) und einmal alles ausgegeben. Erst danach wird sie ins Fallverzeichnis verschoben; jeder Fehler heißt Ablehnen. Die erste Fassung verschob zuerst und räumte bei bestimmten Fehlern auf, siehe Sackgassen. `recherche/bewertung.py:pruefe` meldet unzulässige Status als Sperre `STATUS`, falls sie anders entstehen. Wer `recherche/store.py:lade_fall` direkt aufruft, umgeht das.
- `recherche/store.py:lade_fall` lehnt ab: mehr als 16 MiB entpackt bei mehr als dem 100-fachen der gepackten Größe, zu wenig freien Speicher (Größe plus 100 MiB Reserve) und beschädigte Archive; danach bleibt nichts im Fallverzeichnis zurück.
- Die Datenbank einer geladenen Akte darf nur die Tabellen aus `SCHEMA` enthalten, im Wortlaut (`recherche/store.py:pruefe_schema`). Ein Auslöser oder eine Ansicht könnte Werte ändern, nachdem sie geprüft wurden, etwa einen zurückgesetzten Status wiederherstellen. Folge: Wer `SCHEMA` ändert, sperrt alle älteren Sicherungen aus, bis die Prüfung auch die alte Fassung kennt.
- Ein Beleg zählt für die Obergrenze nur, wenn sein Zitat im gespeicherten Text steht (`recherche/bewertung.py:Kontext`, Schalter `zitate`). Nur die Nachführung nach gewöhnlichen Änderungen schaltet das ab: Sie liefe sonst bei jedem Befehl über die Texte aller Quellen, und kein Befehl kann ein Zitat ungültig machen.
- Schlussfolgerungen, deren Prämissen im Kreis auf sie zurückführen, haben die Obergrenze unbestätigt (`recherche/bewertung.py:_knoten_im_kreis`, einmal je Kontext). Sonst stützen sich zwei Behauptungen ohne jeden Beleg gegenseitig.
- `recherche/bewertung.py:_nachziehen` arbeitet auf einem Kontext mit einer Arbeitsliste: Nach einem Zurücksetzen kommen nur die Schlussfolgerungen noch einmal dran, die darauf beruhen. Es setzt jede Behauptung höchstens einmal zurück und bricht mit einem Fehler ab, wenn sie danach noch unzulässig ist. Zwei IDs, die sich nur in der Schreibung unterschieden (`A1`, `a1`), ließen die frühere Schleife nie enden, weil `Fall.hole` IDs großschreibt.
- `recherche/store.py:faelle_liste` zählt nur Verzeichnisse in Slug-Form als Fälle. Die Arbeitsverzeichnisse von Laden und Löschen beginnen mit einem Punkt und enthalten zeitweise eine `fall.db`.
- Mehrere Prozesse schreiben gleichzeitig in dieselbe Akte (SQLite im WAL-Modus). Eine ID außerhalb der Schreibtransaktion zu vergeben führt zu doppelten IDs.
- Kein Test greift auf das Internet zu: Die Abruftests laufen gegen einen lokalen Server und setzen `RECHERCHE_LOKAL_ERLAUBT=1`.

## Tests
- Abgedeckt: Abruf (Zeichensätze, Umleitung, Fehler, Größengrenze, interne Adressen, Dubletten), Zitatprüfung samt Auslassungen und Positionen, Tabelle der Obergrenzen einschließlich Zuschreibung, Zurücksetzen der Prüfung, jede Problemart von `pruefe`, Export, gleichzeitiges Schreiben, Sichern und Laden einer Akte, PDF-Text über `pdftotext` und über `pypdf` (`tests/test_recherche_quellen.py:PdfTest`). Laden, Archivgrenzen und fremder Aufbau der Datenbank: `tests/test_recherche_archiv.py`. Die Tests der Weboberfläche (`tests/test_recherche_web.py`) laufen unter demselben Muster mit, gehören inhaltlich zu recherche-web.
- Von Hand geprüft am 2026-11-16: Abruf, Lesen und Belegen an drei echten Seiten (support.claude.com, platform.claude.com, anthropic.com), dazu je ein Lauf der Rollen `rechercheur` und `dokumentar` gegen die Akte.
- Die CI (`.github/workflows/apk.yml`) lässt die Tests unter Python 3.10, 3.13 und 3.15 laufen. Unter 3.13 ist `pypdf` in der Version der Android-App installiert, sonst werden die Tests dieses Wegs übersprungen; in der App gibt es nur ihn. Von Hand liefen sie am 2026-11-16 auch unter 3.9, 3.11, 3.12 und 3.14; 3.9 bietet der Runner nicht mehr an.
- Lücken: kein automatischer Test gegen echte Webseiten. PDF-Text nur an einem selbst erzeugten Dokument mit eingebettetem Text; gescannte und verschlüsselte PDFs nicht.

## Sackgassen
- 2026-11-16 · Position eines Belegs als Stelle im normalisierten Text · gescheitert daran, dass `quelle lesen --ab <stelle>` das Zitat nicht traf, weil die Leseausgabe im gespeicherten Text zählt · Beleg: Rollentest des Rechercheurs, Bericht in der Sitzung · erneut prüfen, wenn nie: ein Koordinatensystem genügt
- 2026-11-16 · „gestützt“ schon bei zwei unabhängigen Quellen ohne Bewertung · verworfen, weil zwei unzuverlässige Quellen keinen belastbaren Stand ergeben · Beleg: `recherche/bewertung.py:obergrenze` · erneut prüfen, wenn in echten Fällen zu viel als unbestätigt hängen bleibt
- 2026-11-16 · Die Datenbank aus dem Archiv übernehmen, nachdem ihr Schematext und ihre Werte geprüft sind · gescheitert am Dateiformat: Eine Tabelle mit zwei Zeilen derselben ID hinter einem Index, der nur eine kennt, bestand jede Abfrage; die Prüfung sah die eine Zeile, die Liste zeigte die andere mit „belegt“ · Beleg: drittes Review in der Sitzung, `tests/test_recherche_archiv.py:FeindlicheAkte` · erneut prüfen, wenn nie: Zeilen werden in eine frische Datenbank geschrieben
- 2026-11-16 · Kreise je Behauptung über alle Wege suchen und nach jeder Runde des Zurücksetzens alles neu lesen · gescheitert an der Laufzeit: 99 Sekunden für eine Kette von 4000 Schlussfolgerungen, 144 für eine Kaskade von 800, dabei hält die Oberfläche ihre Sperre · Beleg: drittes Review, `tests/test_recherche_archiv.py:Laufzeit` · erneut prüfen, wenn nie
- 2026-11-16 · Geladene Akte erst ins Fallverzeichnis verschieben, dann prüfen und bei einer Liste bekannter Fehlerarten wieder entfernen · gescheitert daran, dass ein Fehler außerhalb der Liste (`Fehler`, AttributeError) eine ungeprüfte Akte mit unzulässigem Status zurückließ · Beleg: Nachreview in der Sitzung, `tests/test_recherche_archiv.py:FeindlicheAkte` · erneut prüfen, wenn nie: geprüft wird vor dem Verschieben
- 2026-11-16 · Primärbeleg nur aus amtlichen Quellen · gescheitert daran, dass die eigene Veröffentlichung eines Urhebers nie belegen konnte, dass er etwas erklärt · Beleg: Selbsttest-Fall, Behauptung über den Hilfeartikel · gelöst durch die Kennzeichnung als Zuschreibung
