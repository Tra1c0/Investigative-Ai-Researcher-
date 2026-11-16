#!/usr/bin/env bash
# Startprobe auf dem Emulator: installiert die APK, startet die Activity und entscheidet aus
# logcat und dem uiautomator-Dump. Aufruf: starttest.sh <apk> <ausgabeordner>.
# Umgebung: UI_PFLICHT=0|1.
#
# Gemessen wird immer dasselbe:
#   python_ok  logcat: 'recherche: python ok'
#   server_ok  logcat: 'recherche: server ok'
#   ui_dump    die Ueberschrift der Seite (Faelle) steht im uiautomator-Dump
#   ui_js      logcat: 'recherche: js: recherche: oberflaeche bereit' (die Seite meldet sich selbst)
# UI_PFLICHT=0: entscheidet nur python_ok; die UI-Werte werden gemessen und ausgegeben.
# UI_PFLICHT=1: zusaetzlich server_ok und mindestens einer der beiden UI-Werte.
# Exit 0 nur bei Erfolg; jeder andere Ausgang ist ein Fehler.
set -u

APK="${1:?APK fehlt}"
OUT="${2:?Ausgabeordner fehlt}"
UI_PFLICHT="${UI_PFLICHT:-0}"
FRIST="${STARTTEST_FRIST:-90}"          # hoechstens so lange wird gewartet
SETTLE_0="${STARTTEST_SETTLE:-45}"       # Modus 0: so lange wird nach den UI-Werten gesucht, wenn python_ok schon da ist
PAKET=app.recherche.fallakte

mkdir -p "$OUT"
adb wait-for-device

if ! adb install -r "$APK"; then
  echo "FEHLER: Installation fehlgeschlagen"
  exit 1
fi

adb logcat -c
adb shell am start -W -n "$PAKET/.MainActivity"

python_ok=0
server_ok=0
ui_dump=0
ui_js=0
absturz=0
dump_versuche=0
start=$(date +%s)

dump_pruefen() {
  dump_versuche=$((dump_versuche + 1))
  adb shell uiautomator dump /sdcard/ui.xml > "$OUT/dump-meldung.txt" 2>&1
  adb pull /sdcard/ui.xml "$OUT/ui.xml" > /dev/null 2>&1
  if grep -qE 'Fälle|F&#228;lle|F&#xe4;lle|F&#xE4;lle' "$OUT/ui.xml" 2> /dev/null; then
    ui_dump=1
  fi
}

while :; do
  adb logcat -d > "$OUT/logcat.txt" 2>&1
  grep -q 'recherche: python ok' "$OUT/logcat.txt" && python_ok=1
  grep -q 'recherche: server ok' "$OUT/logcat.txt" && server_ok=1
  grep -qF 'recherche: js: recherche: oberflaeche bereit' "$OUT/logcat.txt" && ui_js=1
  if grep -q 'FATAL EXCEPTION' "$OUT/logcat.txt"; then
    absturz=1
    break
  fi
  if [ "$server_ok" = "1" ] && [ "$ui_dump" = "0" ]; then
    dump_pruefen
  fi

  vergangen=$(( $(date +%s) - start ))
  if [ "$UI_PFLICHT" = "1" ]; then
    # Erfolg sobald einer der beiden UI-Werte da ist.
    [ "$python_ok" = "1" ] && [ "$server_ok" = "1" ] && { [ "$ui_dump" = "1" ] || [ "$ui_js" = "1" ]; } && break
  else
    # Messen, solange es etwas zu messen gibt: beide UI-Werte da oder Wartezeit um.
    [ "$python_ok" = "1" ] && [ "$ui_dump" = "1" ] && [ "$ui_js" = "1" ] && break
    [ "$python_ok" = "1" ] && [ "$vergangen" -ge "$SETTLE_0" ] && break
  fi
  [ "$vergangen" -ge "$FRIST" ] && break
  sleep 3
done

# Letzter Blick, damit Werte, die kurz vor Schluss kamen, nicht verloren gehen.
adb logcat -d > "$OUT/logcat.txt" 2>&1
grep -qF 'recherche: js: recherche: oberflaeche bereit' "$OUT/logcat.txt" && ui_js=1
if [ "$server_ok" = "1" ] && [ "$ui_dump" = "0" ]; then
  dump_pruefen
fi
adb exec-out screencap -p > "$OUT/screenshot.png" 2> /dev/null

echo "---- logcat, Tag recherche ----"
grep -E ' recherche: ' "$OUT/logcat.txt" | grep -v ' recherche: js: ' | head -20
echo "---- logcat, Konsole der Seite (recherche: js:), bis 20 ----"
grep -E ' recherche: js: ' "$OUT/logcat.txt" | head -20
echo "---- logcat, Python-Ausgabe und Abstürze ----"
grep -E 'python\.std(out|err)|AndroidRuntime|FATAL' "$OUT/logcat.txt" | head -40
echo "---- Bildschirm laut uiautomator-Dump (Versuche: $dump_versuche) ----"
if [ -s "$OUT/ui.xml" ] && grep -q '<node' "$OUT/ui.xml"; then
  echo "text-Werte (bis 40, verschieden):"
  grep -o ' text="[^"]*"' "$OUT/ui.xml" | sed 's/^ text=//' | grep -v '^""$' | awk '!seen[$0]++' | head -40
  echo "content-desc-Werte (bis 20, verschieden):"
  grep -o ' content-desc="[^"]*"' "$OUT/ui.xml" | sed 's/^ content-desc=//' | grep -v '^""$' | awk '!seen[$0]++' | head -20
else
  echo "kein brauchbarer Dump; Meldung von uiautomator:"
  head -5 "$OUT/dump-meldung.txt" 2> /dev/null
fi
echo "---------------------------------"
echo "python_ok=$python_ok server_ok=$server_ok ui_dump=$ui_dump ui_js=$ui_js absturz=$absturz UI_PFLICHT=$UI_PFLICHT"

if [ "$absturz" = "1" ]; then
  echo "FEHLER: Absturz der App"
  exit 1
fi
if [ "$python_ok" != "1" ]; then
  echo "FEHLER: 'recherche: python ok' erschien nicht innerhalb von ${FRIST}s"
  exit 1
fi
if [ "$UI_PFLICHT" = "1" ]; then
  [ "$server_ok" = "1" ] || { echo "FEHLER: 'recherche: server ok' fehlt"; exit 1; }
  if [ "$ui_dump" = "1" ] && [ "$ui_js" = "1" ]; then
    echo "UI bestanden: ui_dump und ui_js"
  elif [ "$ui_dump" = "1" ]; then
    echo "UI bestanden: nur ui_dump (ui_js fehlt)"
  elif [ "$ui_js" = "1" ]; then
    echo "UI bestanden: nur ui_js (ui_dump fehlt)"
  else
    echo "FEHLER: weder ui_dump noch ui_js"
    exit 1
  fi
fi
echo "Starttest bestanden"
