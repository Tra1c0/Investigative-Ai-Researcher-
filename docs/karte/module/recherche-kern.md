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
stand: "2ac03df860a4"
testlauf: "gruen 2ac03df860a4 2026-11-16"
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
- Jede Änderung an Text, Art, Belegen, Prämissen oder Zuschreibung einer Behauptung setzt ihre Prüfung zurück, ebenso eine Änderung an Quelle oder Beleg, durch die die Obergrenze unter den Status sinkt (`recherche/bewertung.py:nach_aenderung`). Ein neuer Änderungsweg, der das nicht aufruft, lässt einen geprüften Status stehen, den die Belege nicht mehr tragen.
- Das Exportformat ist der Vertrag mit `recherche/dossier.py`. Ein neues Feld muss dort als fehlend verkraftet werden, sonst bricht das Dossier bei alten Akten.
- `recherche/quellen.py:pruefe_ziel` lehnt interne Adressen ab, auch als Ziel einer Umleitung. Scheitert die Namensauflösung, lässt es den Abruf zu, weil hinter einem Proxy nur dieser auflösen kann.
- Webarchive werden nur mit `--archiv` oder `--sichern` angefragt, weil die Anfrage verrät, wozu recherchiert wird (E-008).
- Aus HTML wird der gesamte sichtbare Text übernommen, samt Navigation; eine Erkennung des Hauptinhalts gibt es nicht. Seiten, die ihren Inhalt per JavaScript laden, liefern fast nichts und lösen die Warnung unter 200 Zeichen aus.
- `recherche/cli.py:web` startet die Weboberfläche (siehe recherche-web), die `recherche/cli.py:main` im selben Prozess aufruft. Befehle dürfen darum nur über `sys.stdin` lesen und nur argparse darf beenden; eine neue Option, die einen Pfad nimmt, muss in `recherche/web.py:pruefe_argv` gesperrt werden.
- Mehrere Prozesse schreiben gleichzeitig in dieselbe Akte (SQLite im WAL-Modus). Eine ID außerhalb der Schreibtransaktion zu vergeben führt zu doppelten IDs.
- Kein Test greift auf das Internet zu: Die Abruftests laufen gegen einen lokalen Server und setzen `RECHERCHE_LOKAL_ERLAUBT=1`.

## Tests
- Abgedeckt: Abruf (Zeichensätze, Umleitung, Fehler, Größengrenze, interne Adressen, Dubletten), Zitatprüfung samt Auslassungen und Positionen, Tabelle der Obergrenzen einschließlich Zuschreibung, Zurücksetzen der Prüfung, jede Problemart von `pruefe`, Export, gleichzeitiges Schreiben, Sichern und Laden einer Akte. Die Tests der Weboberfläche (`tests/test_recherche_web.py`) laufen unter demselben Muster mit, gehören inhaltlich zu recherche-web.
- Von Hand geprüft am 2026-11-16: Abruf, Lesen und Belegen an drei echten Seiten (support.claude.com, platform.claude.com, anthropic.com), dazu je ein Lauf der Rollen `rechercheur` und `dokumentar` gegen die Akte.
- Lücken: kein automatischer Test gegen echte Webseiten. PDF-Text nur über `pdftotext` gelaufen, der Weg über `pypdf` nicht. Nicht unter Python 3.9 gelaufen.

## Sackgassen
- 2026-11-16 · Position eines Belegs als Stelle im normalisierten Text · gescheitert daran, dass `quelle lesen --ab <stelle>` das Zitat nicht traf, weil die Leseausgabe im gespeicherten Text zählt · Beleg: Rollentest des Rechercheurs, Bericht in der Sitzung · erneut prüfen, wenn nie: ein Koordinatensystem genügt
- 2026-11-16 · „gestützt“ schon bei zwei unabhängigen Quellen ohne Bewertung · verworfen, weil zwei unzuverlässige Quellen keinen belastbaren Stand ergeben · Beleg: `recherche/bewertung.py:obergrenze` · erneut prüfen, wenn in echten Fällen zu viel als unbestätigt hängen bleibt
- 2026-11-16 · Primärbeleg nur aus amtlichen Quellen · gescheitert daran, dass die eigene Veröffentlichung eines Urhebers nie belegen konnte, dass er etwas erklärt · Beleg: Selbsttest-Fall, Behauptung über den Hilfeartikel · gelöst durch die Kennzeichnung als Zuschreibung
