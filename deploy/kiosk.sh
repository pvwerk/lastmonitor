#!/usr/bin/env bash
# Startet Chromium im Vollbild-Kiosk und zeigt die Lastmonitor-Anzeige.
# Wird beim Login der Desktop-Sitzung automatisch ausgeführt (Autostart).
set -u

URL="http://localhost:8000/"

# Bildschirmschoner aus, DPMS aber aktiv lassen (nur Auto-Timer aus) – der
# Lastmonitor-Dienst schaltet den Monitor sonst per konfigurierbarem
# Standby-Zeitfenster (Einstellungen) selbst per "xset dpms force" ab/an.
xset s off 2>/dev/null || true
xset s noblank 2>/dev/null || true
xset +dpms 2>/dev/null || true
xset dpms 0 0 0 2>/dev/null || true

# Mauszeiger ausblenden
( command -v unclutter >/dev/null && unclutter -idle 0.5 -root & ) 2>/dev/null || true

# Warten bis der Webserver erreichbar ist
for i in $(seq 1 60); do
  if curl -s -o /dev/null "$URL"; then break; fi
  sleep 1
done

CHROME="$(command -v chromium-browser || command -v chromium || true)"
if [ -z "$CHROME" ]; then
  echo "Chromium nicht gefunden" >&2
  exit 1
fi

exec "$CHROME" \
  --kiosk \
  --start-fullscreen \
  --noerrdialogs \
  --disable-infobars \
  --incognito \
  --no-first-run \
  --fast --fast-start \
  --disable-translate \
  --disable-features=Translate,TranslateUI \
  --disable-session-crashed-bubble \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --check-for-update-interval=31536000 \
  "$URL"
