# carplay Pi

Notes and tooling for the Raspberry Pi 4 CarPlay dongle box. This repo
exists because the Pi's root filesystem is read-only at runtime, so
nothing done directly on the device persists unless you go through one
of the methods documented below. Read this before you SSH in and start
changing things — it *will* get reverted on reboot otherwise.

## Hardware / OS

- **Raspberry Pi 4** — USB-C port is power-only, no OTG/gadget mode. USB-A
  ports are host-only too. There is no way to get a terminal over a USB
  cable on this board; use the network or GPIO UART.
- Raspberry Pi OS (Debian trixie), kernel `6.12.47+rpt-rpi-v8`.
- Hostname: `raspi`. User: `ajxd2`.
- Power: needs a genuine 5.1V/3A USB-C PD supply into a wall outlet. A
  computer's USB port or a cheap/thin cable will trigger an undervoltage
  warning and throttle the CPU / risk SD corruption. There's no
  "raise the voltage" fix — it's a current-delivery problem, not a
  software setting. (`avoid_warnings=1` in `config.txt` only hides the
  icon, doesn't fix the actual undervoltage — don't use it as a fix.)

## Read-only root (`overlayroot`) — the most important thing to understand

The Pi boots with `overlayroot="tmpfs:recurse=0"` (see
`/etc/overlayroot.conf`). This means:

- The real filesystem (`/dev/mmcblk0p2`, ext4) is mounted **read-only**
  at `/media/root-ro`.
- Everything else (`/`, `/home`, `/etc`, ...) is a **tmpfs overlay** on
  top of that — `upperdir=/media/root-rw/overlay`.
- Anything written while the Pi is running normally — `apt install`,
  editing a config file, anything — goes into that tmpfs upper layer
  and is **gone on the next reboot or power cycle**.

This is intentional and correct for a device that gets its power cut
abruptly (car ignition off) instead of shut down cleanly — it protects
the SD card from corruption. Don't disable it permanently; work with
it instead.

### How to make a change actually persist

Two ways, both write straight to the real ext4 partition, bypassing
the tmpfs overlay entirely:

**A. Over SSH, while the Pi is running (preferred, no physical access needed):**

```sh
# Remount the real partition read-write:
ssh ajxd2@raspi.local 'sudo mount -o remount,rw /media/root-ro'

# Then write files under /media/root-ro/... instead of the normal path, e.g.:
ssh ajxd2@raspi.local 'sudo tee /media/root-ro/home/ajxd2/some-file'

# For anything needing a proper package-manager/root context (apt installs etc),
# use the overlayroot-chroot helper instead of remounting manually:
ssh ajxd2@raspi.local 'sudo overlayroot-chroot apt-get install -y <pkg>'
# (No "--" before the command — overlayroot-chroot <cmd...> directly.)

# Best-effort remount back to read-only when done:
ssh ajxd2@raspi.local 'sudo mount -o remount,ro /media/root-ro'
```

**Known kernel quirk:** the remount back to `ro` frequently fails with
`mount point is busy` while the overlay is actively mounted on top of
it. This is non-fatal — it just means the real partition stays
writable for the rest of this boot session (same power-loss-corruption
risk as a normal filesystem until next reboot). It always resets
cleanly to read-only on the next boot regardless. If you want the
protection back immediately, `sudo reboot`.

**Another quirk:** overlayfs caches directory listings the first time
something is looked up. If you install a new package (new files
appearing in an already-accessed directory like `/usr/bin`), those new
files **will not show up in the live session** — you have to `sudo
reboot` for the overlay to remount fresh and pick them up. Writing a
brand-new file into a path that's never been touched this boot (e.g. a
new subdirectory under `/home/ajxd2/`) *does* show up live immediately
via the overlay's fallthrough-to-lower behavior. When in doubt, reboot
to be sure.

**B. Offline, by pulling the SD card:**

Mount it on another machine (rootfs partition is `ext4`, boot partition
is `vfat`), edit files directly, unmount, put it back. Slower, but
useful if the Pi won't boot / network is unreachable / you need to fix
something SSH-related itself (like `authorized_keys`).

```sh
lsblk -f                              # find the device, e.g. /dev/sdb
udisksctl mount -b /dev/sdb2          # mounts rootfs at /run/media/$USER/rootfs
udisksctl mount -b /dev/sdb1          # mounts boot partition at .../bootfs
# ... edit files under /run/media/$USER/rootfs/... ...
udisksctl unmount -b /dev/sdb2
```

If your local user has the same UID as `ajxd2` on the Pi (id 1000),
you can write to `ajxd2`-owned files without `sudo` at all.

## Networking

- `systemd-networkd` (enabled) does DHCP on both `eth0` and `wlan0` —
  configs at `/etc/systemd/network/10-eth0.network` and
  `20-wlan0.network`. **Not** `dhcpcd` (present but unused/not enabled).
- Wi-Fi auth is `wpa_supplicant@wlan0.service` (enabled), config at
  `/etc/wpa_supplicant/wpa_supplicant-wlan0.conf` (root-only, `600`).
- `NetworkManager.service` is also enabled but effectively inert —
  `system-connections/` is empty and `NetworkManager.conf` sets
  `managed=false` for ifupdown. It's a leftover, not what's actually
  bringing interfaces up. Ignore it.
- `avahi-daemon` was **masked** (`/etc/systemd/system/avahi-daemon.service`
  symlinked to `/dev/null`) out of the box, which is why `raspi.local`
  didn't resolve. We unmasked and enabled it (done, persisted). If a
  fresh image ever has this problem again:
  ```sh
  sudo rm /media/root-ro/etc/systemd/system/avahi-daemon.service
  sudo ln -s /lib/systemd/system/avahi-daemon.service \
    /media/root-ro/etc/systemd/system/multi-user.target.wants/avahi-daemon.service
  ```
  (or the SSH-live equivalent using `overlayroot-chroot`).

## SSH access

- `authorized_keys` lives at `/home/ajxd2/.ssh/authorized_keys` (was
  empty — that's why a new machine couldn't get in). Add a new laptop's
  key by appending its `~/.ssh/id_ed25519.pub` to that file (through
  one of the persistence methods above, not a plain live SSH edit, or
  it'll disappear on reboot).
- `PasswordAuthentication` is commented out (defaults to whatever
  sshd's compiled default is — currently pubkey-only in practice since
  no password login has worked). Pubkey is the supported path.
- The `ajxd2` account has **passwordless sudo**, and UID 1000 matches a
  typical single-user Linux desktop, which is how the SD-card-editing
  trick above works without needing the Pi's password at all.

## What's actually running

- `react-carplay.AppImage` (Electron app, the actual CarPlay dongle
  software) — auto-started fullscreen from `~/.config/openbox/autostart`,
  restarted in a loop if it crashes (`while true; do ... AppImage; sleep 2; done`).
- Desktop stack: `agetty` autologin on `tty1` → `.xinitrc` → `Xorg` →
  `openbox` (window manager) → autostart script launches CarPlay,
  `pulseaudio`, `picom` (compositor), `unclutter`, and now `dunst` +
  `pi-monitor.sh` (see below).
- No Docker, no other custom services beyond stock Bluetooth/PulseAudio.

## pi-monitor — temp/network notifications

`pi-monitor/` in this repo is a small on-screen alert system, since the
CarPlay app runs fullscreen with no window chrome:

- `pi-monitor/pi-monitor.sh` — polls every 10s, pops up a `dunst`
  notification (via `notify-send`) when CPU temp crosses 70°C (warn) /
  80°C (critical), re-alerting every 5 min while sustained, and clears
  when it drops back down. Also pops up the IP address the moment
  `eth0` gets a link with an address.
- Installed persistently: `dunst` + `libnotify-bin` via
  `overlayroot-chroot`, script lives at `~/pi-monitor/pi-monitor.sh` on
  the Pi, both started from a marked block appended to
  `~/.config/openbox/autostart`.
- `pi-monitor/deploy.sh [user@host]` — the actual devex fix. Edit
  `pi-monitor.sh` here, run `./deploy.sh`, and it:
  1. remounts `/media/root-ro` rw on the Pi
  2. copies the script there (persists across reboot)
  3. ensures the autostart block exists (idempotent, won't duplicate)
  4. best-effort remounts back to `ro`
  5. kills and relaunches the live `dunst`/`pi-monitor.sh` processes on
     the running session so you see the change immediately, without
     waiting for a reboot

  No SD card pulling required for iterating on this script. (Remember
  the "new packages need a reboot to appear live" caveat above if you
  ever add a dependency via `apt`.)

## Quick reference

| Task | Command |
|---|---|
| SSH in | `ssh ajxd2@raspi.local` |
| Check temp | `cat /sys/class/thermal/thermal_zone0/temp` (millidegrees C) or `vcgencmd measure_temp` |
| Check IP | `ip -4 -br addr show eth0` |
| Make root writable (this boot only) | `sudo mount -o remount,rw /media/root-ro` |
| Install a package persistently | `sudo overlayroot-chroot apt-get install -y <pkg>` |
| Deploy pi-monitor changes | `cd pi-monitor && ./deploy.sh` |
| Fully reset the overlay / pick up new packages | `sudo reboot` |
