# carplay Pi

Notes and tooling for the Raspberry Pi 4 CarPlay dongle box. This repo
exists because the Pi's root filesystem is read-only at runtime, so
nothing done directly on the device persists unless you go through one
of the methods documented below. Read this before you SSH in and start
changing things: it *will* get reverted on reboot otherwise.

See [README.md](README.md) for an overview and screenshots.

## Hardware / OS

- **Raspberry Pi 4**: USB-C port is power-only, no OTG/gadget mode. USB-A
  ports are host-only too. There is no way to get a terminal over a USB
  cable on this board; use the network or GPIO UART.
- Raspberry Pi OS (Debian trixie), kernel `6.12.47+rpt-rpi-v8`.
- Hostname: `raspi`. User: `ajxd2`.
- Power: needs a genuine 5.1V/3A USB-C PD supply into a wall outlet. A
  computer's USB port or a cheap/thin cable will trigger an undervoltage
  warning and throttle the CPU / risk SD corruption. There's no
  "raise the voltage" fix, it's a current-delivery problem, not a
  software setting. (`avoid_warnings=1` in `config.txt` only hides the
  icon, doesn't fix the actual undervoltage: don't use it as a fix.)

## Read-only root (`overlayroot`): the most important thing to understand

The Pi boots with `overlayroot="tmpfs:recurse=0"` (see
`/etc/overlayroot.conf`). This means:

- The real filesystem (`/dev/mmcblk0p2`, ext4) is mounted **read-only**
  at `/media/root-ro`.
- Everything else (`/`, `/home`, `/etc`, ...) is a **tmpfs overlay** on
  top of that, `upperdir=/media/root-rw/overlay`.
- Anything written while the Pi is running normally (`apt install`,
  editing a config file, anything) goes into that tmpfs upper layer
  and is **gone on the next reboot or power cycle**.

This is intentional and correct for a device that gets its power cut
abruptly (car ignition off) instead of shut down cleanly. It protects
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
# (No "--" before the command: overlayroot-chroot <cmd...> directly.)

# Best-effort remount back to read-only when done:
ssh ajxd2@raspi.local 'sudo mount -o remount,ro /media/root-ro'
```

**Known kernel quirk:** the remount back to `ro` frequently fails with
`mount point is busy` while the overlay is actively mounted on top of
it. This is non-fatal, it just means the real partition stays
writable for the rest of this boot session (same power-loss-corruption
risk as a normal filesystem until next reboot). It always resets
cleanly to read-only on the next boot regardless. If you want the
protection back immediately, `sudo reboot`.

**Another quirk:** overlayfs caches directory listings the first time
something is looked up. If you install a new package (new files
appearing in an already-accessed directory like `/usr/bin`), those new
files **will not show up in the live session**, you have to `sudo
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

- `systemd-networkd` (enabled) does DHCP on both `eth0` and `wlan0`.
  Configs at `/etc/systemd/network/10-eth0.network` and
  `20-wlan0.network`. **Not** `dhcpcd` (present but unused/not enabled).
- Wi-Fi auth is `wpa_supplicant@wlan0.service` (enabled), config at
  `/etc/wpa_supplicant/wpa_supplicant-wlan0.conf` (root-only, `600`).
- `NetworkManager.service` is also enabled but effectively inert:
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
  empty, that's why a new machine couldn't get in). Add a new laptop's
  key by appending its `~/.ssh/id_ed25519.pub` to that file (through
  one of the persistence methods above, not a plain live SSH edit, or
  it'll disappear on reboot).
- `PasswordAuthentication` is commented out (defaults to whatever
  sshd's compiled default is, currently pubkey-only in practice since
  no password login has worked). Pubkey is the supported path.
- The `ajxd2` account has **passwordless sudo**, and UID 1000 matches a
  typical single-user Linux desktop, which is how the SD-card-editing
  trick above works without needing the Pi's password at all.

## The CarPlay dongle itself (Carlinkit CPC200-CCPA)

The physical dongle enumerates as USB `1314:1521` (`Magic Communication
Tec.` / `Auto Box` in the descriptors, broadcasting as `AutoKit-8169`
over WiFi/BT), and is a genuine Carlinkit CPC200-CCPA (confirmed from
the printing on the physical unit) -- an i.MX6UL-based embedded Linux
board, 16MB flash. It reports `boxType: YA`, `productType: A15W`,
`hwVersion: YMA0-WN16-0003`, software `2025.02.25.1521CHY`.

`react-carplay`/`node-carplay` (the app this repo runs) talks to it
over a simple bulk-USB wire protocol reverse-engineered upstream in
`rhysmorgan134/node-CarPlay`'s `src/modules/messages/{common,sendable,
readable}.ts`. Worth knowing if you ever need to script against the
dongle directly (`python3-usb`, install via `sudo overlayroot-chroot
apt-get install -y python3-usb`, works fine for this since it's just
bulk transfers on a vendor-specific interface):

- **Reads available**: manufacturer/serial (USB descriptor), software
  version, box identity/config including the full **paired-device
  list** (`BoxInfo.DevList` -- MAC, name, index, per device), a
  separate raw `BluetoothPairedList` string, box's own WiFi/BT name,
  a live HiCar pairing link, and now-playing media (song/artist/album
  art -- this is genuinely live personal data, be careful taking
  screenshots of a running session).
- **Writes available**: night mode, WiFi band, media transport
  commands, accept/reject call, and file-based cosmetic config
  (`SendFile` to `/etc/box_name`, `/etc/airplay.conf`,
  `/etc/icon_*.png` etc) -- see `launcher/tools/set_dongle_icon.py`,
  which sets a custom name + icon on the phone's CarPlay home-screen
  tile using exactly this mechanism. **File writes to `/etc/` on the
  dongle appear to only take effect after a physical power-cycle of
  the dongle itself** (unplug/replug), not just a CarPlay app restart.
- **No device-removal capability found.** Despite reading the full
  paired-device list, there is no command in the protocol (documented
  or otherwise -- tried ~30 undocumented `Command` values around the
  known pairing cluster) that removes/forgets a specific paired phone.
  To disconnect a phone from this dongle, use the phone's own
  Settings -> General -> CarPlay -> (car) -> "Forget This Car".
- **Don't bother with alternate/custom firmware.** Carlinkit added an
  activation-lock mechanism (`/etc/uuid_sign`) after community
  reverse-engineering became known to them; a firmware that fails
  activation has no known unlock path. There's also no documented live
  root/shell access to this hardware (no UART/SSH/telnet), only
  hardware flash programming, which isn't worth the bricking risk for
  a device-management feature that isn't confirmed to exist in any
  firmware version anyway.

## What's actually running

- `launcher/launcher.py` (see below) is now what autostarts, not
  `react-carplay.AppImage` directly. CarPlay is one of its apps.
- Desktop stack: `agetty` autologin on `tty1` → `.xinitrc` → `Xorg` →
  `openbox` (window manager) → autostart script launches the launcher +
  overlay tab, `pulseaudio`, `picom` (compositor), `unclutter`, `dunst` +
  `pi-monitor.sh` (see below).
- No Docker, no other custom services beyond stock Bluetooth/PulseAudio.

## launcher: CarPlay as one app among others

`launcher/` turns this from a single-purpose CarPlay box into a small
home screen with CarPlay as one tile among a few others (Flappy Bird, a
live system-status app, a trip/fuel-cost calculator, a log viewer), all
controllable via touch, since the car has no keyboard.

The home screen is a **Chromium kiosk** (HTML/CSS/JS UI served by a small
local Python backend), not the original pygame implementation -- pygame's
`FINGERDOWN` touch handling never reliably registered real touchscreen
taps on this hardware (simulated X11 clicks worked fine, which is exactly
what made the bug hard to catch -- real touch and simulated clicks are not
the same code path in SDL), while Chromium's touch handling is the same
stack CarPlay's own Electron app already uses reliably on this device.

- **`launcher/server.py`**: the backend that autostarts instead of the old
  `launcher.py`. Stdlib-only (`http.server.ThreadingHTTPServer` -- no
  `pip`/Flask on this device, deliberately not installed for this). Owns
  the `APPS` list, process/window state, config, and volume; serves
  `launcher/web/` and a small JSON API (`GET/POST /api/apps`, `/launch`,
  `/volume`, `/config`, `/dim`) the frontend calls over `fetch()`. On
  startup it binds its HTTP port *before* spawning Chromium (so there's no
  request-before-the-server-exists race), waits for Chromium's window via
  the same `wait_for_new_active_window()` every other app uses, and
  registers that window as "home" for `overlay_tab.py` exactly like
  `launcher.py` used to.
  - Chromium's window gets `wm_helper.make_override_redirect()` applied
    once at startup: Chromium's kiosk/fullscreen state is *dynamic* (tied
    to visibility), unlike pygame's static `NOFRAME` attribute, so the
    plain unmap/map cycle `hide_window()`/`show_window()` already use for
    every app would otherwise cause openbox to silently re-decorate the
    window (titlebar, borders, and a resulting black margin around the
    kiosk UI) the first time you switch away and back. Override-redirect
    (the same technique `overlay_tab.py` already used) makes the WM stop
    managing the window entirely, and the window is explicitly re-pinned
    to `0,0 800x480` since the brief decorated state can leave stale inset
    geometry behind even after the frame itself is gone.
  - Wipes `/tmp/chromium-kiosk-profile` on every start rather than reusing
    it: a leftover `SingletonLock` from a prior run can make a fresh
    Chromium think another instance already owns the profile and silently
    refuse to open a window at all.
  - Settings screen: pick a default app and toggle whether it auto-launches
    immediately on boot (skipping the grid). Saved to `launcher/config.json`
    -- written through `/media/root-ro` (remount rw, `sudo tee`, remount
    ro, all via `ajxd2`'s passwordless sudo, no redeploy needed) the same
    way `deploy.sh` itself persists files, just triggered live from the
    touchscreen instead of over SSH. Auto-launch reuses the exact same
    `open_app()` path a manual tap uses, with one non-negotiable guard:
    the launcher/Chromium window is only ever hidden once the target app's
    window is confirmed, so a broken default app can never strand you on a
    blank screen with nothing to tap -- the grid stays up as a fallback.
  - Night-dim (moon icon): writes directly to
    `/sys/class/backlight/*/brightness` (`ajxd2` is in the `video` group,
    no sudo needed) rather than a CSS overlay, so it actually dims the
    physical screen -- CarPlay included, not just the launcher's own page.
- **`launcher/web/`**: the frontend (`index.html`/`app.js`/`style.css`),
  plain HTML/CSS/JS with no build step -- there's no reliable internet on
  this device and the UI surface is small enough that a bundler would add
  risk for no benefit. Layout: a top bar (night-dim + date/time), a left
  sidebar (volume +/- and a drag-to-set vertical slider using pointer
  events, settings gear), and full-height app panels with a lit green
  border for whichever app is currently running.
- **`launcher/wm_helper.py`**: shared window-management + audio helpers
  used by `server.py` and `overlay_tab.py` alike:
  - `wait_for_new_active_window()` captures a newly-launched app's
    window by polling `xdotool getactivewindow` until focus lands on
    something big enough to be the real app (`min_w=400, min_h=300` by
    default), not a transient splash/helper window. Electron apps
    (CarPlay included) briefly create small helper windows during
    startup; capturing one of those instead of the real 800x480 window
    was the cause of an apparent "CarPlay is glitched" bug that turned
    out to be a wrong window ID, not a real crash.
  - `apply_audio_priority(binary)`: **CarPlay always has audio
    priority**: its sink-input is explicitly unmuted on every app
    switch and is never touched by anything else the launcher does;
    whatever else is currently active gets muted instead, so it can
    never compete with or interrupt CarPlay's audio. Operates on *all*
    matching sink-inputs for a given app (CarPlay alone creates two),
    not just the first/last match found.
- **`launcher/overlay_tab.py`**: a small always-on-top "go home" tab,
  bottom-center of the screen, a chevron on a dark pill. Built as a raw
  X11 **override-redirect** window (via `python3-xlib`, not the kiosk
  page, which has no way to request this window type from inside a
  browser) so it floats above *any* fullscreen app including CarPlay, the
  same trick `dunst` notifications already rely on. Tapping it hides
  whatever's currently active and un-hides the launcher; nothing gets
  killed. Technology-agnostic by design -- it only ever reads whichever
  window id is in `/tmp/carplay_pi_launcher_winid`, so it needed zero
  changes across the pygame-to-Chromium rewrite.
- **`launcher/launcher.py`** (+ `flappy.py`, `info.py`, `trip.py`,
  `logs.py`): the original pygame implementation. No longer autostarted,
  but left in place, undeployed from autostart, as a documented manual
  fallback: SSH in, `pkill -9 -f chromium` and `pkill -9 -f server.py`,
  then `python3 /home/ajxd2/launcher/launcher.py` by hand.
- **`launcher/info.py`**: a live system-status app (hostname, uptime,
  CPU temp, throttle status via `vcgencmd get_throttled`, load average,
  memory/disk, both IPs, volume), refreshing every second. Answers "is
  it actually undervolting" directly instead of inferring it from
  temperature the way `pi-monitor.sh` does.
- **`launcher/flappy.py`**: a throwaway Flappy Bird clone (pygame
  canvas, tap-to-flap), mostly built to prove random little apps are
  actually viable on this screen, not because it needed to exist.
- **`launcher/trip.py`**: a two-tab (Convert / Trip Cost) unit and
  fuel-cost calculator, state persisted to `launcher/trip_state.json` next
  to the script so values survive an app restart.
- **`launcher/logs.py`**: an on-screen tail of `/tmp/launcher_autolaunch.log`,
  `journalctl`, and `dmesg`, since this device has no attached terminal --
  reading logs otherwise means SSHing in from another machine.
- Visual style shares the same dark, muted palette as `pi-monitor/dunstrc`'s
  "Refined Card" style (same background/border/text colors, translated
  from the pygame RGB tuples into CSS hex values) so the whole UI reads as
  one system rather than bolted-together prototypes.

### The bug that ate most of a session: the old autostart loop

The original `~/.config/openbox/autostart` launched CarPlay directly:
`(while true; do react-carplay.AppImage; sleep 2; done) &`. Every time
the launcher (or a manual `pkill`) killed CarPlay to hide/replace it,
this loop would silently relaunch it 2 seconds later, fighting with the
launcher's own process tracking. This produced duplicate CarPlay
instances and what looked like random glitches for a long time before
being traced to the loop itself via `pstree`, not a bug in the launcher
code. **`launcher/deploy.sh` removes that loop line** as part of
deploying. If you ever hand-restore the old autostart line for some
reason, the launcher's process management will fight it again.

### Known limitations

- If `server.py` itself ever restarts (crash, redeploy) while an app is
  already running, it loses track of that app in its in-memory state,
  the tile will show as "not running" and tapping it again would spawn a
  duplicate rather than re-attaching to the existing process. Restarting
  the whole stack together (as `deploy.sh` does) sidesteps this; a more
  robust version would discover already-running apps by querying X/process
  state on startup instead of trusting in-memory tracking.
- Killing Chromium's process tree with `pkill -9 -f chromium` reliably
  drops the *current* SSH session for a couple of seconds (looks like a
  brief system-wide hiccup, maybe GPU/DRM cleanup on this Pi) even though
  the device itself is fine -- `deploy.sh` runs that kill as its own,
  last, `ssh` call for exactly this reason. If you're ever scripting
  something similar by hand, don't chain other cleanup commands after it
  in the same remote shell; they won't run.

- `launcher/deploy.sh [--autostart] [user@host]`: same
  `/media/root-ro` write-through pattern as `pi-monitor/deploy.sh`. By
  default only copies files and live-restarts the running stack --
  **does not touch the openbox autostart file**, so a bad deploy can't
  break the next boot. Pass `--autostart` (only after verifying the
  live-restarted stack works on the real touchscreen) to rewrite autostart
  and make it boot-persistent. Also installs the `chromium` apt package
  persistently (idempotent, via `overlayroot-chroot`) if it isn't already
  present.

## pi-monitor: temp/network notifications

`pi-monitor/` in this repo is a small on-screen alert system, since the
CarPlay app runs fullscreen with no window chrome:

- `pi-monitor/pi-monitor.sh`: polls every 10s, pops up a `dunst`
  notification (via `notify-send`) when CPU temp crosses 70°C (warn) /
  80°C (critical). Warnings re-alert every 5 min while sustained.
  Critical alerts re-alert every 1 min and also play an audible beep,
  since a red border alone isn't urgent enough to notice while driving.
  Clears with a confirmation notification when temp drops back down.
  Also pops up the IP address the moment `eth0` gets a link with an
  address.
- The critical beep (`pi-monitor/assets/critical-beep.wav`) fully mutes
  the CarPlay audio sink-input before playing and unmutes it right
  after (see `play_critical_alert` in `pi-monitor.sh`), rather than just
  ducking the volume. A partial duck still let the beep get lost in the
  music; full mute is what actually interrupts. The beep itself is a
  synthesized square wave (harsher/more harmonics than a sine, reads as
  sharper), not a stock desktop sound, played at 150% gain via
  `paplay --volume`. Regenerate it with:
  ```sh
  ffmpeg -y -f lavfi -i "aevalsrc=exprs='0.9*(2*gt(sin(2*PI*1500*t)\,0)-1)':s=44100:d=0.15,afade=t=in:d=0.005,afade=t=out:st=0.145:d=0.005" \
    -f lavfi -i "anullsrc=r=44100:cl=stereo:d=0.5" \
    -f lavfi -i "aevalsrc=exprs='0.9*(2*gt(sin(2*PI*1500*t)\,0)-1)':s=44100:d=0.15,afade=t=in:d=0.005,afade=t=out:st=0.145:d=0.005" \
    -filter_complex "[0:a]pan=stereo|c0=c0|c1=c0[b1];[2:a]pan=stereo|c0=c0|c1=c0[b2];[b1][1:a][b2]concat=n=3:v=0:a=1[out]" \
    -map "[out]" -ar 44100 -ac 2 -acodec pcm_s16le pi-monitor/assets/critical-beep.wav
  ```
  (two 150ms beeps at 1500Hz with a 0.5s gap between them)
- Installed persistently: `dunst` and `libnotify-bin` via
  `overlayroot-chroot`. Script and beep asset live at
  `~/pi-monitor/` on the Pi, both dunst and the monitor started from a
  marked block appended to `~/.config/openbox/autostart`.
- `pi-monitor/dunstrc`: the "Refined Card" style (see `pi-monitor/styles/`
  for the 6 variants that were tried and rejected/kept for reference).
  Dark, muted, desaturated frame color as the accent (slate-blue for
  normal, brick-red for critical) rather than a bright saturated color,
  since the brighter Modern Card variant read as too playful. Popups
  appear top-center (`origin = top-center`) with a real colored icon
  per notification (`pi-monitor/assets/icons/info.png` for
  connectivity/info, `warning.png` for thermal warn/critical), rather
  than relying on text glyphs. The icons are hand-authored SVGs
  (`assets/icons/*.svg`, rendered to PNG via `rsvg-convert`), not the
  system's Adwaita symbolic icons: those render in a dark near-black
  fill meant to be recolored by GTK's CSS icon theming, which doesn't
  happen when dunst loads them standalone, so they'd be invisible on a
  dark background. Deployed to `~/.config/dunst/dunstrc` on the Pi.
  Notifications appear instantly (no slide-in animation): dunst has no
  built-in animation system, and its windows are override-redirect,
  which compositors (including the `picom` running here) often exclude
  from effects by design. Untested and left alone rather than sinking
  time into an uncertain experiment.
- `pi-monitor/deploy.sh [user@host]`: the actual devex fix. Edit
  `pi-monitor.sh` here, run `./deploy.sh`, and it:
  1. remounts `/media/root-ro` rw on the Pi
  2. copies the script, assets (beep + icons), and dunstrc there (persists across
     reboot)
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
| Deploy launcher changes | `cd launcher && ./deploy.sh` |
| Fully reset the overlay / pick up new packages | `sudo reboot` |
