#!/usr/bin/env bash
# Installiert den Küchen-Lastmonitor auf einem Raspberry Pi (Raspberry Pi OS).
# - Python-Abhängigkeiten in venv
# - systemd-Dienst (Webserver, Autostart, Neustart bei Absturz)
# - Chromium-Kiosk-Autostart auf dem angeschlossenen Monitor
#
# Aufruf auf dem Pi:   bash deploy/install.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
RUN_HOME="$(eval echo "~$RUN_USER")"

echo "==> Installation in: $APP_DIR  (Benutzer: $RUN_USER)"

echo "==> Systempakete installieren …"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip curl unclutter || true
# Chromium heißt je nach OS-Version unterschiedlich
sudo apt-get install -y chromium-browser || sudo apt-get install -y chromium || true

echo "==> Python-venv + Abhängigkeiten …"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> GPIO-Zugriff (Sirene bei Überlast) …"
sudo usermod -aG gpio "$RUN_USER" || true

echo "==> Konfiguration …"
if [ ! -f "$APP_DIR/config.json" ]; then
  cp "$APP_DIR/config.example.json" "$APP_DIR/config.json"
  echo "    config.json aus Vorlage erstellt – IP-Adresse später unter /settings eintragen."
fi

echo "==> systemd-Dienst einrichten …"
sudo tee /etc/systemd/system/lastmonitor.service >/dev/null <<EOF
[Unit]
Description=Kuechen-Lastmonitor (PLEXLOG)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
SupplementaryGroups=gpio
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now lastmonitor.service

echo "==> Kiosk-Autostart einrichten …"
chmod +x "$APP_DIR/deploy/kiosk.sh"
mkdir -p "$RUN_HOME/.config/autostart"
cat > "$RUN_HOME/.config/autostart/lastmonitor-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Lastmonitor Kiosk
Exec=$APP_DIR/deploy/kiosk.sh
X-GNOME-Autostart-enabled=true
EOF
chown -R "$RUN_USER":"$RUN_USER" "$RUN_HOME/.config/autostart" 2>/dev/null || true

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "============================================================"
echo " Fertig."
echo " Anzeige (lokal am Pi):     http://localhost:8000/"
echo " Einstellungen (im Netz):   http://${IP:-<pi-ip>}:8000/settings"
echo ""
echo " Dienst-Status:  sudo systemctl status lastmonitor"
echo " Logs:           journalctl -u lastmonitor -f"
echo " Für den Kiosk-Vollbildmodus den Pi neu starten:  sudo reboot"
echo "============================================================"
