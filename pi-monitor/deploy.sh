#!/bin/bash
# Deploys pi-monitor to the Pi over SSH, writing directly through
# /media/root-ro so changes persist across reboots — no SD card pull
# needed. Root fs is overlayroot (read-only ext4 + tmpfs overlay), so
# ordinary writes over SSH would vanish on next boot; this script
# remounts the real ext4 partition rw first.
#
# Usage: ./deploy.sh [user@host]

set -euo pipefail

HOST="${1:-ajxd2@raspi.local}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_ROOT=/media/root-ro   # real ext4 mount, bypasses the tmpfs overlay
REMOTE_HOME="$REMOTE_ROOT/home/ajxd2"

echo "==> Ensuring root-ro is writable on $HOST"
ssh "$HOST" 'sudo mount -o remount,rw /media/root-ro 2>/dev/null; true'

echo "==> Copying pi-monitor.sh"
ssh "$HOST" "sudo mkdir -p $REMOTE_HOME/pi-monitor && sudo tee $REMOTE_HOME/pi-monitor/pi-monitor.sh >/dev/null" < "$SCRIPT_DIR/pi-monitor.sh"
ssh "$HOST" "sudo chmod +x $REMOTE_HOME/pi-monitor/pi-monitor.sh && sudo chown ajxd2:ajxd2 $REMOTE_HOME/pi-monitor/pi-monitor.sh"

echo "==> Ensuring openbox autostart launches dunst + pi-monitor"
ssh "$HOST" bash -s <<REMOTE_EOF
set -e
AUTOSTART="$REMOTE_HOME/.config/openbox/autostart"
MARK="# pi-monitor autostart (managed by deploy.sh)"
if ! sudo grep -qF "\$MARK" "\$AUTOSTART" 2>/dev/null; then
  sudo tee -a "\$AUTOSTART" >/dev/null <<'BLOCK'

# pi-monitor autostart (managed by deploy.sh)
dunst &
/home/ajxd2/pi-monitor/pi-monitor.sh &
BLOCK
  echo "  added autostart entries"
else
  echo "  autostart already present, skipping"
fi
REMOTE_EOF

echo "==> Attempting to remount root-ro back to read-only (best effort)"
ssh "$HOST" 'sudo mount -o remount,ro /media/root-ro 2>&1 || echo "  (kernel wont allow remount while overlay active this boot -- fine, resets clean on next reboot)"'

echo "==> Restarting live pi-monitor/dunst on the running session for immediate effect"
ssh "$HOST" '
  pkill -f "pi-monitor/pi-monitor.sh" 2>/dev/null || true
  pkill -x dunst 2>/dev/null || true
  sleep 1
  export DISPLAY=:0
  export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
  setsid nohup dunst >/tmp/dunst.log 2>&1 < /dev/null &
  setsid nohup /home/ajxd2/pi-monitor/pi-monitor.sh >/tmp/pi-monitor.log 2>&1 < /dev/null &
'

echo "==> Done. Deployed persistently and running live."
