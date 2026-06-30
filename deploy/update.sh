#!/usr/bin/env bash
# Update auf die neueste Version aus GitHub und Neustart des Dienstes.
# Aufruf auf dem Pi:   bash deploy/update.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

echo "==> Neuste Version laden …"
git pull --ff-only

echo "==> Abhängigkeiten aktualisieren …"
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Dienst neu starten …"
sudo systemctl restart lastmonitor.service
echo "==> Fertig. Status:"
sudo systemctl --no-pager status lastmonitor.service | head -n 6
