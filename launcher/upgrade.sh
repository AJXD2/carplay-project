#!/bin/bash
# Full system upgrade (security fixes, kernel, boot firmware) for the Pi's
# overlayroot setup, with the progress card on screen (splash/progress.sh).
# Follows INFO.md "Initramfs and kernel updates in the chroot": the FAT boot
# partition is mounted into the chroot so kernel8.img, initramfs8 and the
# firmware land where the Pi boots from.
#
# Why it is shaped like this:
#   - The boot partition is copied to ./backups/ on this machine first. The
#     old kernel's modules stay installed, so restoring that copy onto the
#     card's boot partition boots the previous kernel.
#   - dpkg swaps files under the live overlay. Until the reboot, the running
#     system sees replaced files as dead inodes (mode 0600, no links), so a
#     fresh sudo, systemctl or mount can refuse to run. Everything on the Pi
#     runs in one root shell started before the upgrade, the new initramfs
#     is checked inside the chroot (real files), and the reboot falls back to
#     /proc/sysrq-trigger, which needs only shell builtins.
#   - apt is IPv4 only: a LAN with a broken IPv6 route stalls it for good.
#
# Usage: ./upgrade.sh [--yes] [user@host]   (without --yes: simulate only)

set -euo pipefail

APPLY=false
if [[ "${1:-}" == "--yes" ]]; then APPLY=true; shift; fi
HOST="${1:-ajxd2@raspi.local}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APT='apt-get -o Acquire::ForceIPv4=true'

echo "==> Refreshing package lists and simulating"
ssh "$HOST" "sudo mount -o remount,rw /media/root-ro 2>/dev/null; sudo overlayroot-chroot $APT update >/dev/null 2>&1; sudo overlayroot-chroot $APT -s full-upgrade 2>/dev/null" \
  | grep -E '^[0-9]+ upgraded|^Remv' || true
$APPLY || { echo "==> Simulation only. Run with --yes to apply."; exit 0; }

source "$SCRIPT_DIR/splash/progress.sh"
onscreen_start "$HOST" "Updating the system" "System updated"
onscreen 2 5 3 "Saving the boot partition. Keep the power on."
trap 'onscreen -1 0 1 "Update stopped. See the log on the laptop."' ERR

BACKUP="$SCRIPT_DIR/../backups/bootfs-$(date +%Y%m%d-%H%M%S).tar"
mkdir -p "$(dirname "$BACKUP")"
echo "==> Backing up the boot partition to $BACKUP"
ssh "$HOST" 'sudo mount -o ro /dev/mmcblk0p1 /mnt && sudo tar -C /mnt -cf - . ; sudo umount /mnt' > "$BACKUP"
tar -tf "$BACKUP" | grep -qx './kernel8.img' || { echo "backup is missing kernel8.img" >&2; false; }

echo "==> Upgrading (kernel, firmware, everything; takes a while)"
onscreen 5 85 600 "Installing updates. Keep the power on."
# After this call no new program may start on the Pi until it reboots (libc6,
# bash, sudo are replaced), so the root shell ends by writing the card state
# and rebooting with builtins; the laptop side makes no further ssh calls.
# The connection drops at the reboot, so success is the "==> Rebooting" line.
LOG="${BACKUP%.tar}.log"
ssh "$HOST" "sudo bash -s" <<'REMOTE_EOF' 2>&1 | tee "$LOG" || true
RO=/media/root-ro
APT='apt-get -o Acquire::ForceIPv4=true'
card() { printf '%s\n' "$1" > /tmp/xsplash-progress; }
pause() { local t=$((SECONDS + $1)); while ((SECONDS < t)); do :; done; }
mount -o remount,rw $RO 2>/dev/null
mount /dev/mmcblk0p1 $RO/boot/firmware || { card '-1 0 1 Could not mount the boot partition. Nothing changed.'; exit 1; }
# One chroot call does the upgrade and the checks, so the checks see the real
# new files. overlayroot-chroot exits 0 whatever happens: success is the
# CHECKS-OK line, read with builtins.
ok=0
while IFS= read -r line; do
  printf '%s\n' "$line"
  [[ $line == CHECKS-OK ]] && ok=1
done < <(overlayroot-chroot env DEBIAN_FRONTEND=noninteractive sh -c "
  set -e
  $APT -y -o Dpkg::Options::=--force-confold full-upgrade
  dpkg --audit
  echo \"newest kernel: \$(ls /lib/modules | sort -V | tail -1)\"
  rm -rf /tmp/initrd-check
  unmkinitramfs /boot/firmware/initramfs8 /tmp/initrd-check
  find /tmp/initrd-check -path '*sbin/fsck.ext4' | grep -q . || { echo 'initramfs8 has no fsck.ext4'; exit 1; }
  find /tmp/initrd-check -path '*plymouth/themes/carplay/carplay.script' | grep -q . || { echo 'initramfs8 has no splash theme'; exit 1; }
  find /tmp/initrd-check -name overlayroot | grep -q . || { echo 'initramfs8 has no overlayroot'; exit 1; }
  rm -rf /tmp/initrd-check
  ls -la /boot/firmware/kernel8.img /boot/firmware/initramfs8
  dpkg-query -W ca-certificates chromium libnss3 openssl raspi-firmware
  sync
  echo CHECKS-OK
" 2>&1 </dev/null)
if ((ok == 0)); then
  card '-1 0 1 Update failed. Do not restart yet, check the laptop.'
  echo "UPGRADE FAILED: the boot partition is still mounted at $RO/boot/firmware" >&2
  exit 1
fi
card '100 100 1 Restarting now.'
echo "==> Rebooting"
pause 3
# systemctl may be one of the replaced files; sysrq needs builtins only
systemctl reboot 2>/dev/null || {
  echo s > /proc/sysrq-trigger; pause 3
  echo u > /proc/sysrq-trigger; pause 2
  echo b > /proc/sysrq-trigger
}
REMOTE_EOF
grep -q '^==> Rebooting' "$LOG" || { echo "upgrade failed; log: $LOG" >&2; exit 1; }

trap - ERR
echo "==> Done. Boot partition backup: $BACKUP, log: $LOG"
