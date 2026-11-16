---
paths:
  - "android/**"
  - ".github/workflows/apk.yml"
zweck: "Android-Hülle: eingebettetes Python (Chaquopy) plus WebView um die lokale Oberfläche von recherche; Bau und Starttest in GitHub Actions"
stand: "1dff8894c1f9"
---
# android-huelle

## Einstieg
- `android/app/src/main/java/app/recherche/fallakte/MainActivity.java`: die einzige Activity. Startet Python in einem Hintergrundthread, ruft `recherche.web.starte_im_hintergrund`, lädt die URL in die WebView. `Bruecke` ist das JavaScript-Interface `Android` (importieren, exportieren, dossierTeilen, speichern, dossierSpeichern, oeffneExtern).
- `android/app/src/main/java/app/recherche/fallakte/UrlRegeln.java`: die Regeln, welche Adresse in die WebView darf und welche in den Browser.
- `android/app/build.gradle`: Chaquopy-Konfiguration und der Task `syncPython`, der `recherche/` aus dem Repository ins Build-Verzeichnis spiegelt (Unterordner python-src, nie im Git).
- `.github/workflows/apk.yml`: Jobs `tests`, `apk`, `starttest`, `veroeffentlichen`. `android/ci/starttest.sh` entscheidet den Starttest aus logcat und uiautomator-Dump.
- `android/build.gradle`: hier stehen die Versionen von Android-Gradle-Plugin und Chaquopy.

## Verträge und Fallstricke
- Die Python-Quellen gibt es nur in `recherche/`. Unter `android/` darf keine Kopie liegen; der Workflow bricht ab, wenn dort eine `__init__.py` auftaucht. Die Chaquopy-Tasks hängen per Namensmuster (`python`) an `syncPython`, ohne das kämen Gradle-8-Fehler über fehlende Task-Abhängigkeiten.
- Die Seite ruft nur `window.Android.*` auf, und das ist nur sicher, weil in der WebView ausschließlich der Ursprung `http://127.0.0.1:<port>` des Servers lädt, auch für Unteranfragen (`UrlRegeln.istEigeneSeite`). Der Vergleich ist ein Präfixvergleich der Zeichenkette, nicht der Host aus `android.net.Uri`: Bei `http://fremd.example\@127.0.0.1:<port>/` liest Uri den lokalen Host, Chromium lädt aber fremd.example. `localhost` ist bewusst nicht erlaubt (könnte auf ::1 laufen). Wer eine Fremdseite in die WebView lässt, gibt ihr Import, Export und Dateizugriff.
- Der Token steckt in der URL (`?t=`). Er darf nicht ins Log (auch nicht über die Konsole der Seite: `onConsoleMessage` loggt ohne Quelladresse) und nicht in den Browser; `UrlRegeln.externeAdresse` lässt nur Hostnamen mit Punkt zu, keine IP-Adresse in irgendeiner Schreibweise, kein localhost, keine Benutzerangabe, keinen Rückwärtsstrich, und verlangt denselben Host von `java.net.URI` und `android.net.Uri`.
- Speichern: `speichern` und `dossierSpeichern` erzeugen die Datei im Cache, öffnen `ACTION_CREATE_DOCUMENT` und kopieren erst im Ergebnis; die Cache-Kopie wird danach gelöscht. Es gibt nur eine ausstehende Datei, `MainActivity.zuSpeichern`. Der Import bricht bei `recherche.web.MAX_LADEN` ab (gelesen aus Python) und löscht die Teilkopie.
- Der Server lebt pro Prozess; `MainActivity` merkt URL und Port statisch, damit eine neu erzeugte Activity keinen zweiten Server startet.
- Log-Schlüsselwörter `python ok` und `server ok` (Tag `recherche`) liest `android/ci/starttest.sh`; ändert man sie, ändert man den Test.
- Gebaut wird `assembleRelease`, nicht debuggable: Mit `android:debuggable` käme jeder mit adb-Zugriff per `run-as` an die Fallakten. Der Workflow-Schritt „APK prüfen“ bricht ab, wenn `aapt2 dump badging` `application-debuggable` meldet. Die Datei heißt `recherche.apk` (Artefakt `recherche-apk`, Release-Anhang).
- Signiert wird mit dem Debug-Schlüssel des Build-Rechners (`signingConfigs.debug`, kein Geheimnis nötig). Er entsteht bei jedem CI-Lauf neu: Eine installierte App lässt sich nicht aktualisieren, eine neuere Version erfordert Deinstallieren, und das löscht die Fälle, wenn sie nicht vorher exportiert wurden. Ein fester Schlüssel braucht ein Repository-Secret, das nur der Eigentümer anlegen kann.
- `pypdf` ist in `android/app/build.gradle` auf eine Version festgenagelt: Die App verarbeitet sensible Daten, da soll nicht der Stand des Bautags einfließen.
- Manifest: nur INTERNET, `allowBackup=false`, leere Datenextraktion, Klartext nur für 127.0.0.1. FileProvider gibt nur `cache/export/` frei. `targetSdk` bleibt 34, ab 35 erzwingt Android Edge-to-Edge.
- Versionen: AGP 8.13.0 (Chaquopy 17.2 unterstützt 7.3 bis 9.5), Gradle 8.13 über den Wrapper, JDK 17, compileSdk 35, Python 3.13 (muss auf dem Build-Rechner dieselbe Minor-Version haben).
- Zwei Schalter oben im Workflow: `UI_PFLICHT` bestimmt nur die Strenge des Starttests, `VEROEFFENTLICHEN` allein, ob der Job `veroeffentlichen` die Vorabversion (Tag `apk-vorab`) anlegt; vorher enthielte sie eine App ohne Oberfläche. Sie löscht das alte Release samt Tag und legt es neu an. Ein Release aus dem allerersten Lauf (Commit 0a3b61e, noch ohne diese Bedingung, Anhang noch recherche-debug.apk) bleibt bis zum nächsten Veröffentlichungslauf stehen.
- `android/gradle/wrapper/gradle-wrapper.properties` hat keine Prüfsumme der Distribution, weil downloads.gradle.org im Entwicklungscontainer gesperrt ist; die Wrapper-JAR prüft der Workflow mit der Gradle-Wrapper-Validierung.

## Tests
- Es gibt keinen lokalen Test: Der Android-SDK ist im Entwicklungscontainer gesperrt, gebaut wird nur in GitHub Actions.
- Der Job `starttest` startet die APK auf einem x86_64-Emulator (API 34). Gemessen werden immer `python_ok`, `server_ok`, `ui_dump` (Überschrift „Fälle“ im uiautomator-Dump, auch als Entität `F&#228;lle`) und `ui_js` (die Seite loggt `oberflaeche bereit`, die Hülle schreibt es als `recherche: js: …`). `UI_PFLICHT=0` entscheidet nur `python_ok`; mit `1` zählt zusätzlich `server_ok` und einer der beiden UI-Werte. Das Skript gibt die Bildschirmtexte und die `js:`-Zeilen aus, weil Artefakte nicht immer abrufbar sind.
- Lokal geprüft wurde nur, was ohne Android läuft: die Regeln in `UrlRegeln` gegen einen Nachbau von `android.net.Uri` (nicht in CI, der Nachbau ist eine Annahme über Uri) und `starttest.sh` gegen ein vorgetäuschtes adb.
- Nicht geprüft: Import, Export, Speichern, Dateiauswahl und Teilen auf einem Gerät, arm64.

## Sackgassen
- (keine)
