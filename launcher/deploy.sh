#!/bin/bash
# Deploys the launcher (CarPlay + Flappy Bird + Info, with the
# always-on-top overlay tab) to the Pi over SSH, writing directly
# through /media/root-ro so it persists across reboots, same approach
# as pi-monitor/deploy.sh. See the repo README for how/why this works
# on an overlayroot read-only root.
#
# Also removes the original autostart line that launched CarPlay
# directly in a crash-restart loop -- that loop fights with the
# launcher's own process management (it will respawn CarPlay the
# moment the launcher hides/kills it), which caused a whole session's
# worth of "duplicate CarPlay" confusion before the conflict was found.
#
# Usage: ./deploy.sh [user@host]

set -euo pipefail

HOST="${1:-ajxd2@raspi.local}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_ROOT=/media/root-ro
REMOTE_HOME="$REMOTE_ROOT/home/ajxd2"
REMOTE_LAUNCHER_DIR="$REMOTE_HOME/launcher"

echo "==> Ensuring root-ro is writable on $HOST"
ssh "$HOST" 'sudo mount -o remount,rw /media/root-ro 2>/dev/null; true'

echo "==> Copying launcher files"
ssh "$HOST" "sudo mkdir -p $REMOTE_LAUNCHER_DIR"
for f in wm_helper.py launcher.py flappy.py info.py overlay_tab.py; do
  ssh "$HOST" "sudo tee $REMOTE_LAUNCHER_DIR/$f >/dev/null" < "$SCRIPT_DIR/$f"
done
ssh "$HOST" "sudo chown -R ajxd2:ajxd2 $REMOTE_LAUNCHER_DIR"

echo "==> Rewriting openbox autostart: launcher instead of direct CarPlay loop"
ssh "$HOST" bash -s <<REMOTE_EOF
set -e
AUTOSTART="$REMOTE_HOME/.config/openbox/autostart"
OLD_LOOP='(while true; do XCURSOR_THEME=Blank /home/ajxd2/react-carplay.AppImage --no-sandbox; sleep 2; done) &'
MARK="# launcher autostart (managed by launcher/deploy.sh)"

if sudo grep -qF "\$OLD_LOOP" "\$AUTOSTART" 2>/dev/null; then
  sudo grep -vF "\$OLD_LOOP" "\$AUTOSTART" | sudo tee "\$AUTOSTART.new" >/dev/null
  sudo mv "\$AUTOSTART.new" "\$AUTOSTART"
  echo "  removed the old direct-CarPlay autostart loop"
fi

if ! sudo grep -qF "\$MARK" "\$AUTOSTART" 2>/dev/null; then
  sudo tee -a "\$AUTOSTART" >/dev/null <<'BLOCK'

# launcher autostart (managed by launcher/deploy.sh)
python3 /home/ajxd2/launcher/launcher.py &
python3 /home/ajxd2/launcher/overlay_tab.py &
BLOCK
  echo "  added launcher autostart entries"
else
  echo "  launcher autostart already present, skipping"
fi
REMOTE_EOF

echo "==> Attempting to remount root-ro back to read-only (best effort)"
ssh "$HOST" 'sudo mount -o remount,ro /media/root-ro 2>&1 || echo "  (kernel wont allow remount while overlay active this boot -- fine, resets clean on next reboot)"'

echo "==> Restarting live launcher stack for immediate effect"
ssh "$HOST" '
  pkill -9 -x python3 2>/dev/null || true
  pkill -9 -x react-carplay 2>/dev/null || true
  pkill -9 -x react-carplay.AppImage 2>/dev/null || true
  sleep 1
  rm -f /tmp/carplay_pi_launcher_winid
  export DISPLAY=:0
  export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
  setsid nohup python3 /home/ajxd2/launcher/launcher.py >/tmp/launcher.log 2>&1 < /dev/null &
  sleep 2
  setsid nohup python3 /home/ajxd2/launcher/overlay_tab.py >/tmp/overlay_tab.log 2>&1 < /dev/null &
'

echo "==> Done. Deployed persistently and running live."
