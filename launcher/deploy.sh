#!/bin/bash
# Deploys the launcher (Chromium-kiosk frontend + Python backend, CarPlay +
# Flappy Bird + Info + Trip Calc + Logs as the apps it launches, with the
# always-on-top overlay tab) to the Pi over SSH, writing directly through
# /media/root-ro so it persists across reboots, same approach as
# pi-monitor/deploy.sh. See the repo README for how/why this works on an
# overlayroot read-only root.
#
# By default this only copies files and live-restarts the running stack --
# it does NOT touch the openbox autostart file, so a bad deploy doesn't risk
# the next boot. Pass --autostart once you've verified the live-restarted
# stack works on the real touchscreen, to make it the boot-time default.
#
# The old pygame launcher.py/flappy.py/info.py are still copied and left in
# place, undeployed from autostart, as a manual fallback: SSH in, `pkill -9
# -f chromium` and `pkill -9 -f server.py`, then `python3
# /home/ajxd2/launcher/launcher.py` by hand.
#
# Usage: ./deploy.sh [--autostart] [user@host]

set -euo pipefail

AUTOSTART_FLAG=false
if [[ "${1:-}" == "--autostart" ]]; then
  AUTOSTART_FLAG=true
  shift
fi

HOST="${1:-ajxd2@raspi.local}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_ROOT=/media/root-ro
REMOTE_HOME="$REMOTE_ROOT/home/ajxd2"
REMOTE_LAUNCHER_DIR="$REMOTE_HOME/launcher"

echo "==> Ensuring root-ro is writable on $HOST"
ssh "$HOST" 'sudo mount -o remount,rw /media/root-ro 2>/dev/null; true'

echo "==> Ensuring chromium is installed (persistent, idempotent)"
ssh "$HOST" 'command -v chromium >/dev/null || sudo overlayroot-chroot apt-get install -y chromium'

echo "==> Copying launcher files"
ssh "$HOST" "sudo mkdir -p $REMOTE_LAUNCHER_DIR/assets/icons $REMOTE_LAUNCHER_DIR/web"
for f in wm_helper.py server.py launcher.py flappy.py info.py trip.py logs.py overlay_tab.py; do
  ssh "$HOST" "sudo tee $REMOTE_LAUNCHER_DIR/$f >/dev/null" < "$SCRIPT_DIR/$f"
done
for f in "$SCRIPT_DIR"/web/*; do
  ssh "$HOST" "sudo tee $REMOTE_LAUNCHER_DIR/web/$(basename "$f") >/dev/null" < "$f"
done
for f in "$SCRIPT_DIR"/assets/icons/*.svg "$SCRIPT_DIR"/assets/icons/*.png; do
  ssh "$HOST" "sudo tee $REMOTE_LAUNCHER_DIR/assets/icons/$(basename "$f") >/dev/null" < "$f"
done
ssh "$HOST" "sudo chown -R ajxd2:ajxd2 $REMOTE_LAUNCHER_DIR"

echo "==> Seeding config.json (only if it doesn't already exist -- it's device-owned state, saved live from the settings screen, not repo-managed)"
ssh "$HOST" "sudo test -f $REMOTE_LAUNCHER_DIR/config.json || echo '{\"default_app\": null, \"auto_launch\": false}' | sudo tee $REMOTE_LAUNCHER_DIR/config.json >/dev/null"

if $AUTOSTART_FLAG; then
  echo "==> Rewriting openbox autostart: server.py (Chromium kiosk) instead of the old pygame launcher.py"
  ssh "$HOST" bash -s <<REMOTE_EOF
set -e
AUTOSTART="$REMOTE_HOME/.config/openbox/autostart"
OLD_LOOP='(while true; do XCURSOR_THEME=Blank /home/ajxd2/react-carplay.AppImage --no-sandbox; sleep 2; done) &'
OLD_LAUNCHER_LINE='python3 /home/ajxd2/launcher/launcher.py &'
MARK="# launcher autostart (managed by launcher/deploy.sh)"

if sudo grep -qF "\$OLD_LOOP" "\$AUTOSTART" 2>/dev/null; then
  sudo grep -vF "\$OLD_LOOP" "\$AUTOSTART" | sudo tee "\$AUTOSTART.new" >/dev/null
  sudo mv "\$AUTOSTART.new" "\$AUTOSTART"
  echo "  removed the old direct-CarPlay autostart loop"
fi

if sudo grep -qF "\$OLD_LAUNCHER_LINE" "\$AUTOSTART" 2>/dev/null; then
  sudo grep -vF -e "\$MARK" -e "\$OLD_LAUNCHER_LINE" -e 'python3 /home/ajxd2/launcher/overlay_tab.py &' "\$AUTOSTART" | sudo tee "\$AUTOSTART.new" >/dev/null
  sudo mv "\$AUTOSTART.new" "\$AUTOSTART"
  echo "  removed the old pygame launcher.py autostart block"
fi

if ! sudo grep -qF "\$MARK" "\$AUTOSTART" 2>/dev/null; then
  sudo tee -a "\$AUTOSTART" >/dev/null <<'BLOCK'

# launcher autostart (managed by launcher/deploy.sh)
(while true; do python3 /home/ajxd2/launcher/server.py; sleep 2; done) &
python3 /home/ajxd2/launcher/overlay_tab.py &
BLOCK
  echo "  added server.py (kiosk backend) + overlay_tab.py autostart entries"
else
  echo "  launcher autostart already present, skipping"
fi
REMOTE_EOF
else
  echo "==> Skipping autostart rewrite (pass --autostart once the live-restarted stack is verified on the touchscreen)"
fi

echo "==> Attempting to remount root-ro back to read-only (best effort)"
ssh "$HOST" 'sudo mount -o remount,ro /media/root-ro 2>&1 || echo "  (kernel wont allow remount while overlay active this boot -- fine, resets clean on next reboot)"'

echo "==> Killing old launcher stack"
# The AppImage-mount wrapper process's comm name gets truncated to
# "react-carplay.A" by the kernel's 15-char TASK_COMM_LEN limit, so `pkill
# -x react-carplay.AppImage` (exact comm match) never matches it and it
# survived every previous restart as a stale leftover process -- match its
# full command line with -f instead, which isn't length-limited.
ssh "$HOST" '
  pkill -9 -x python3 2>/dev/null || true
  pkill -9 -x react-carplay 2>/dev/null || true
  pkill -9 -f "/home/ajxd2/react-carplay.AppImage" 2>/dev/null || true
' || true
sleep 1
# Killing chromium's process tree with -9 tends to drop the current SSH
# session for a couple of seconds (looks like a brief system-wide hiccup,
# maybe GPU/DRM cleanup) even though the Pi itself is fine -- so this runs
# as its own, last, ssh call, tolerating a non-zero/dropped-connection exit.
ssh "$HOST" 'pkill -9 -f chromium 2>/dev/null || true' || true
sleep 3

echo "==> Restarting live launcher stack for immediate effect"
ssh "$HOST" '
  rm -f /tmp/carplay_pi_launcher_winid
  export DISPLAY=:0
  export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
  setsid nohup python3 /home/ajxd2/launcher/server.py >/tmp/server.log 2>&1 < /dev/null &
  sleep 2
  setsid nohup python3 /home/ajxd2/launcher/overlay_tab.py >/tmp/overlay_tab.log 2>&1 < /dev/null &
'

echo "==> Done. Deployed and running live. Re-run with --autostart once verified to make it boot-persistent."
