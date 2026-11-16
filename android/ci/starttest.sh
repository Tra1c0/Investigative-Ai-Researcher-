#!/usr/bin/env bash
# Startprobe auf dem Emulator: installiert die APK, startet die Activity und entscheidet aus
# logcat. Aufruf: starttest.sh <apk> <ausgabeordner>. Umgebung: UI_PFLICHT=0|1.
# Exit 0 nur, wenn alle geforderten Zeichen erscheinen; jeder andere Ausgang ist ein Fehler.
set -u

APK="${1:?APK fehlt}"
OUT="${2:?Ausgabeordner fehlt}"
UI_PFLICHT="${UI_PFLICHT:-0}"
FRIST=90
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
ui_ok=0
absturz=0
start=$(date +%s)

while :; do
  adb logcat -d > "$OUT/logcat.txt" 2>&1
  grep -q 'recherche: python ok' "$OUT/logcat.txt" && python_ok=1
  grep -q 'recherche: server ok' "$OUT/logcat.txt" && server_ok=1
  if grep -q 'FATAL EXCEPTION' "$OUT/logcat.txt"; then
    absturz=1
    break
  fi
  if [ "$UI_PFLICHT" = "1" ] && [ "$server_ok" = "1" ] && [ "$ui_ok" = "0" ]; then
    adb shell uiautomator dump /sdcard/ui.xml > /dev/null 2>&1
    adb pull /sdcard/ui.xml "$OUT/ui.xml" > /dev/null 2>&1
    grep -qF 'Fälle' "$OUT/ui.xml" 2> /dev/null && ui_ok=1
  fi
  fertig=$python_ok
  if [ "$UI_PFLICHT" = "1" ]; then
    fertig=$(( python_ok && server_ok && ui_ok ))
  fi
  [ "$fertig" = "1" ] && break
  [ $(( $(date +%s) - start )) -ge "$FRIST" ] && break
  sleep 3
done

adb exec-out screencap -p > "$OUT/screenshot.png" 2> /dev/null
adb logcat -d > "$OUT/logcat.txt" 2>&1

echo "---- relevante logcat-Zeilen ----"
grep -E 'recherche|python\.std|AndroidRuntime|FATAL|chaquopy' "$OUT/logcat.txt" | head -60
echo "---------------------------------"
echo "python_ok=$python_ok server_ok=$server_ok ui_ok=$ui_ok absturz=$absturz UI_PFLICHT=$UI_PFLICHT"

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
  [ "$ui_ok" = "1" ] || { echo "FEHLER: Text 'Fälle' nicht im uiautomator-Dump"; exit 1; }
fi
echo "Starttest bestanden"
