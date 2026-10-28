#!/bin/bash
# Installs the carrier board software on the Pi, writing through
# /media/root-ro so it persists (see INFO.md), with a progress card on the
# Pi's screen (../splash/progress.sh) so nobody cuts the power mid-write.
#
# What it does:
#   - i2c-tools and util-linux-extra (hwclock) in overlayroot-chroot (dtc
#     ships with the OS); i2c-dev loaded at boot for /dev/i2c-*
#   - board/ to ~/launcher/board, carrierd.service to /etc/systemd/system
#     (enabled only with --enable)
#   - compiles system/carrier-audio-overlay.dts into overlays/carrier-audio.dtbo
#     on the boot partition (staged; only loaded with --audio)
#   - writes the lines from system/config.txt into the boot partition's
#     config.txt as one managed block, replacing any earlier block
#
# Stages (BRINGUP.md): the default block has I2C, the GPIO26 power hold, the
# RTC and fan PWM. --audio adds dtparam=audio=off and the carrier-audio
# overlay, and makes the board PulseAudio's default speaker and mic at
# 48 kHz (system/carrier.pa, 89-carrier-pulse.rules); leave it out while
# CarPlay still plays through the USB adapter.
# enable_uart is left out: the UART header J3 is not fitted.
#
# The FAT boot partition is not mounted under overlayroot, so it is mounted
# on /mnt only while it is written. config.txt is backed up once as
# config.txt.carrier-bak; delete the block (or restore the backup) to undo.
#
# --board-only: just copy board/ and restart carrierd (code changes to the
# board software); no tools, audio or boot settings are touched.
#
# Usage: ./install.sh [--audio] [--enable] [--reboot] [user@host]
#        ./install.sh --board-only [user@host]

set -euo pipefail

AUDIO=false ENABLE=false REBOOT=false BOARD_ONLY=false
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --board-only) BOARD_ONLY=true ;;
    --audio) AUDIO=true ;;
    --enable) ENABLE=true ;;
    --reboot) REBOOT=true ;;
    *) echo "unknown option $1" >&2; exit 1 ;;
  esac
  shift
done
HOST="${1:-ajxd2@raspi.local}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RO=/media/root-ro
RO_HOME=$RO/home/ajxd2

if $BOARD_ONLY; then
  source "$SCRIPT_DIR/../splash/progress.sh"
  onscreen_start "$HOST" "Updating board software" "Board software updated"
  onscreen 5 40 3 "Copying the board software."
  trap 'onscreen -1 0 1 "Stopped. The board software was not changed."' ERR
  ssh "$HOST" "sudo mount -o remount,rw $RO 2>/dev/null; true"
  echo "==> Copying board/"
  tar -C "$SCRIPT_DIR/.." --exclude=__pycache__ -cf - board \
    | ssh "$HOST" "sudo tar -C $RO_HOME/launcher --no-same-owner --overwrite -xf - && sudo chown -R ajxd2:ajxd2 $RO_HOME/launcher/board"
  echo "==> Restarting carrierd"
  onscreen 50 95 3 "Restarting the board service. Audio pauses for a second."
  ssh "$HOST" "sudo systemctl restart carrierd && sleep 2 && systemctl is-active carrierd"
  ssh "$HOST" "sudo mount -o remount,ro $RO 2>/dev/null || true"
  trap - ERR
  onscreen 100 100 1 "Running the new version."
  echo "==> Done."
  exit 0
fi

# The managed block: system/config.txt minus comments, the UART line and,
# without --audio, the audio lines.
BLOCK="$(grep -v -e '^#' -e '^$' -e '^enable_uart' "$SCRIPT_DIR/system/config.txt")"
if ! $AUDIO; then
  BLOCK="$(grep -v -e '^dtparam=audio=' -e '^dtoverlay=carrier-audio' <<<"$BLOCK")"
fi
echo "==> config.txt block:"
sed 's/^/    /' <<<"$BLOCK"

source "$SCRIPT_DIR/../splash/progress.sh"
onscreen_start "$HOST" "Installing the carrier board" "Carrier board installed"
onscreen 2 10 3 "Getting ready. Keep the power on."
trap 'onscreen -1 0 1 "Stopped. Boot settings were not changed if this came before that step."' ERR

echo "==> Ensuring root-ro is writable on $HOST"
ssh "$HOST" "sudo mount -o remount,rw $RO 2>/dev/null; true"

echo "==> Installing i2c-tools and hwclock (persistent, idempotent)"
onscreen 10 40 20 "Installing tools. Keep the power on."
# the image's package lists go stale (old versions 404), so refresh first;
# IPv4 only: a LAN with a broken IPv6 route stalls apt for good
ssh "$HOST" "test -x $RO/usr/sbin/i2cdetect -a -x $RO/usr/sbin/hwclock || { sudo overlayroot-chroot apt-get -o Acquire::ForceIPv4=true update && sudo overlayroot-chroot apt-get -o Acquire::ForceIPv4=true install -y i2c-tools util-linux-extra; }"
# overlayroot-chroot exits 0 even when apt fails
ssh "$HOST" "test -x $RO/usr/sbin/i2cdetect -a -x $RO/usr/sbin/hwclock" || { echo "i2c-tools/hwclock did not install" >&2; false; }
echo i2c-dev | ssh "$HOST" "sudo tee $RO/etc/modules-load.d/carrier-i2c.conf >/dev/null"

ssh "$HOST" "sudo mount -o remount,rw $RO 2>/dev/null; true"   # after the chroot above
echo "==> Copying board/ and the carrierd unit"
onscreen 40 55 3 "Copying the board software. Keep the power on."
tar -C "$SCRIPT_DIR/.." --exclude=__pycache__ -cf - board \
  | ssh "$HOST" "sudo mkdir -p $RO_HOME/launcher && sudo tar -C $RO_HOME/launcher --no-same-owner --overwrite -xf - && sudo chown -R ajxd2:ajxd2 $RO_HOME/launcher/board"
ssh "$HOST" "sudo tee $RO/etc/systemd/system/carrierd.service >/dev/null" < "$SCRIPT_DIR/system/carrierd.service"
if $ENABLE; then
  ssh "$HOST" "sudo overlayroot-chroot systemctl enable carrierd"
  ssh "$HOST" "test -L $RO/etc/systemd/system/multi-user.target.wants/carrierd.service" \
    || { echo "carrierd was not enabled" >&2; false; }
fi

# overlayroot-chroot remounts root-ro read-only when it exits
rw() { ssh "$HOST" "sudo mount -o remount,rw $RO 2>/dev/null; true"; }

if $AUDIO; then
  rw
  echo "==> PulseAudio: the board as default speaker and mic, 48 kHz"
  onscreen 50 55 2 "Setting up the board audio."
  ssh "$HOST" "sudo mkdir -p $RO/etc/pulse/default.pa.d && sudo tee $RO/etc/pulse/default.pa.d/carrier.pa >/dev/null" \
    < "$SCRIPT_DIR/system/carrier.pa"
  ssh "$HOST" "sudo tee $RO/etc/udev/rules.d/89-carrier-pulse.rules >/dev/null" < "$SCRIPT_DIR/system/89-carrier-pulse.rules"
  ssh "$HOST" bash -s <<REMOTE_EOF
set -e
PA=$RO/etc/pulse
# default.pa must pull in the drop-in directory
sudo grep -q '^\.include /etc/pulse/default.pa.d' \$PA/default.pa || echo '.include /etc/pulse/default.pa.d' | sudo tee -a \$PA/default.pa >/dev/null
# the board runs at 48 kHz only: no resampling to 44.1 kHz streams' rate
for k in default-sample-rate alternate-sample-rate; do
  if sudo grep -q "^[;#]* *\$k *=" \$PA/daemon.conf; then
    sudo sed -i "s/^[;#]* *\$k *=.*/\$k = 48000/" \$PA/daemon.conf
  else
    echo "\$k = 48000" | sudo tee -a \$PA/daemon.conf >/dev/null
  fi
done
grep -E '^(default|alternate)-sample-rate' \$PA/daemon.conf
# ~/.config/pulse/default.pa (hand-made, not in the repo) pinned the default
# sink to the USB adapter and runs after the drop-in: drop that line, once
# backed up.
U=$RO_HOME/.config/pulse/default.pa
if sudo grep -q '^set-default-sink' \$U 2>/dev/null; then
  sudo test -f \$U.usb-adapter || sudo cp -p \$U \$U.usb-adapter
  sudo sed -i '/^set-default-sink/d' \$U
fi
REMOTE_EOF
fi

echo "==> Compiling the audio overlay"
onscreen 55 65 3 "Building the audio overlay."
ssh "$HOST" "cat > /tmp/carrier-audio.dts && dtc -q -@ -I dts -O dtb -o /tmp/carrier-audio.dtbo /tmp/carrier-audio.dts" \
  < "$SCRIPT_DIR/system/carrier-audio-overlay.dts"

echo "==> Writing the boot partition"
onscreen 65 95 4 "Writing boot settings. Keep the power on."
ssh "$HOST" "BLOCK_B64=$(base64 -w0 <<<"$BLOCK") bash -s" <<'REMOTE_EOF'
set -e
BLOCK="$(base64 -d <<<"$BLOCK_B64")"
FW=/mnt
sudo mount /dev/mmcblk0p1 "$FW"
trap 'sudo umount "$FW"' EXIT
CFG="$FW/config.txt"
sudo test -f "$CFG.carrier-bak" || sudo cp "$CFG" "$CFG.carrier-bak"
sudo cp /tmp/carrier-audio.dtbo "$FW/overlays/carrier-audio.dtbo"
BEGIN='# >>> carrier board (managed by launcher/board/install.sh)'
END='# <<< carrier board'
# drop any earlier block, then append the new one under [all]
sudo awk -v b="$BEGIN" -v e="$END" '$0==b{skip=1} !skip{print} $0==e{skip=0}' "$CFG" \
  | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}' > /tmp/config.txt.new
printf '\n%s\n[all]\n%s\n%s\n' "$BEGIN" "$BLOCK" "$END" >> /tmp/config.txt.new
sudo cp /tmp/config.txt.new "$CFG.new"
sudo sync
sudo mv "$CFG.new" "$CFG"
sudo sync
echo "--- $CFG (end)"
tail -n 12 "$CFG"
REMOTE_EOF

ssh "$HOST" "sudo mount -o remount,ro $RO 2>/dev/null || true"
trap - ERR
if $REBOOT; then
  onscreen 100 100 1 "Restarting now."
  echo "==> Rebooting"
  sleep 3  # long enough to read the card
  ssh "$HOST" "sudo systemctl reboot" || true
else
  onscreen 100 100 1 "It takes effect at the next start."
  echo "==> Done. Reboot the Pi to load the new boot settings."
fi
