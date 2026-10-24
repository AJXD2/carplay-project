#!/bin/bash
# Installs a rendered splash draft (build/<draft>, from render.py) as the
# Pi's boot splash, writing through /media/root-ro so it persists. Also
# installs the boot session pieces the splash depends on: xsplash.py (keeps
# the animation playing in X until the launcher is up), ~/.xinitrc and
# ~/.bash_profile from launcher/system/, a getty@tty1 override so autologin
# can't hang behind Plymouth, and vt.global_cursor_default=0 on the kernel
# command line so the console never shows a text cursor.
#
# While it runs, a progress card is shown on the Pi's screen (progress.sh),
# so whoever is in the car knows not to cut the power.
#
# Plymouth runs from the initramfs, so the theme files alone do nothing: the
# initramfs is rebuilt in overlayroot-chroot and copied to the FAT boot
# partition as initramfs8, which is what the Pi 4 boots. Two settings are
# needed for any initramfs build inside overlayroot-chroot, so they're
# installed as /etc/initramfs-tools/conf.d/overlayroot (also used by kernel
# updates, see INFO.md):
#   MODULES=most  the Pi's MODULES=dep fails in the chroot ("failed to
#                 determine device for /")
#   FSTYPE=ext4   the fsck hook can't detect the root type in the chroot and
#                 would leave fsck out of the image
# overlayroot-chroot exits 0 even when its command fails, so success is
# judged by unpacking the new image and checking it holds this draft.
#
# Rollback: the original theme is kept once as themes/carplay-rings, the
# original image as initramfs8.bak on the boot partition, and the original
# session files as ~/.xinitrc.orig and ~/.bash_profile.orig.
#
# Usage: ./install.sh <draft> [user@host]    e.g. ./install.sh 4-bulb-check

set -euo pipefail

DRAFT="${1:?usage: install.sh <draft> [user@host]}"
HOST="${2:-ajxd2@raspi.local}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEM_DIR="$SCRIPT_DIR/../system"
SRC="$SCRIPT_DIR/build/$DRAFT"
RO=/media/root-ro
THEME=$RO/usr/share/plymouth/themes/carplay
RO_HOME=$RO/home/ajxd2

if [[ ! -f "$SRC/carplay.script" || ! -f "$SRC/frames.json" ]]; then
  echo "no complete build in $SRC; run ./render.py $DRAFT first" >&2
  exit 1
fi

source "$SCRIPT_DIR/progress.sh"
echo "==> Showing progress on the Pi's screen"
onscreen_start "$HOST" "Updating boot splash" "Boot splash updated"
onscreen 2 10 3 "Copying the new animation. Keep the power on."
trap 'onscreen -1 0 1 "The Pi still boots the previous splash."' ERR

echo "==> Ensuring root-ro is writable on $HOST"
ssh "$HOST" "sudo mount -o remount,rw $RO 2>/dev/null; true"

echo "==> Replacing the carplay theme with $DRAFT"
ssh "$HOST" "sudo test -d $THEME-rings || sudo cp -a $THEME $THEME-rings"
ssh "$HOST" "sudo find $THEME -mindepth 1 -delete"
tar -C "$SRC" --exclude=preview.webp -cf - . \
  | ssh "$HOST" "sudo tar -C $THEME --no-same-owner -xf - && sudo chown -R root:root $THEME"

echo "==> Installing the boot session (xsplash.py, .xinitrc, .bash_profile)"
onscreen 10 15 2 "Installing the boot session. Keep the power on."
ssh "$HOST" "sudo mkdir -p $RO_HOME/launcher/splash && sudo tee $RO_HOME/launcher/splash/xsplash.py >/dev/null" < "$SCRIPT_DIR/xsplash.py"
for f in xinitrc bash_profile; do
  ssh "$HOST" "sudo test -f $RO_HOME/.$f.orig || sudo cp -p $RO_HOME/.$f $RO_HOME/.$f.orig"
  ssh "$HOST" "sudo tee $RO_HOME/.$f >/dev/null" < "$SYSTEM_DIR/$f"
done
ssh "$HOST" "sudo chown -R ajxd2:ajxd2 $RO_HOME/launcher/splash $RO_HOME/.xinitrc $RO_HOME/.bash_profile"
# tty1 login must not wait on terminal queries Plymouth never answers
ssh "$HOST" "sudo tee $RO/etc/systemd/system/getty@tty1.service.d/noquery.conf >/dev/null" < "$SYSTEM_DIR/getty-tty1-noquery.conf"

echo "==> Installing the initramfs settings for building in the chroot"
ssh "$HOST" "sudo tee $RO/etc/initramfs-tools/conf.d/overlayroot >/dev/null" < "$SYSTEM_DIR/initramfs-overlayroot.conf"

echo "==> Rebuilding the initramfs (takes a minute)"
onscreen 15 80 25 "Rebuilding the boot image. Keep the power on."
ssh "$HOST" DRAFT="$DRAFT" bash -s <<'REMOTE_EOF'
set -e
KVER="$(uname -r)"
NEW="/boot/initrd.img-$KVER.splash"
sudo rm -f "/media/root-ro$NEW"
sudo overlayroot-chroot mkinitramfs -o "$NEW" "$KVER"
check=/tmp/splash-check
sudo rm -rf "$check"
if ! sudo unmkinitramfs "/media/root-ro$NEW" "$check" \
   || ! sudo grep -qs "from $DRAFT.html" "$check"/usr/share/plymouth/themes/carplay/carplay.script \
        "$check"/main/usr/share/plymouth/themes/carplay/carplay.script; then
  echo "initramfs build failed or is missing the $DRAFT theme; boot partition untouched" >&2
  exit 1
fi
if ! sudo find "$check" -path '*sbin/fsck.ext4' | grep -q .; then
  echo "initramfs is missing fsck.ext4; boot partition untouched" >&2
  exit 1
fi
sudo rm -rf "$check"
REMOTE_EOF

echo "==> Writing the boot partition"
onscreen 85 95 3 "Writing the boot partition. Keep the power on."
ssh "$HOST" bash -s <<'REMOTE_EOF'
set -e
KVER="$(uname -r)"
NEW="/media/root-ro/boot/initrd.img-$KVER.splash"
FW=/mnt
sudo mount /dev/mmcblk0p1 "$FW"
trap 'sudo umount "$FW"' EXIT
sudo test -f "$FW/initramfs8.bak" || sudo cp "$FW/initramfs8" "$FW/initramfs8.bak"
sudo cp "$NEW" "$FW/initramfs8.new"
sudo sync
sudo mv "$FW/initramfs8.new" "$FW/initramfs8"
if ! grep -q 'vt.global_cursor_default=0' "$FW/cmdline.txt"; then
  sudo cp "$FW/cmdline.txt" "$FW/cmdline.txt.bak"
  sudo sed -i '1 s/$/ vt.global_cursor_default=0/' "$FW/cmdline.txt"
fi
sudo sync
sudo mv "$NEW" "/media/root-ro/boot/initrd.img-$KVER"
ls -la "$FW/initramfs8" "$FW/initramfs8.bak"
cat "$FW/cmdline.txt"
REMOTE_EOF

trap - ERR
onscreen 100 100 1 "It plays from the next start."
echo "==> Done. Reboot the Pi to see it."
