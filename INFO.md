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
- **Device removal is NOT in the USB protocol -- but it exists in the
  dongle's own web admin panel.** Over the USB wire protocol there is no
  remove/forget command (confirmed: tried the documented set plus
  `BoxSettings` (0x19) writes carrying `DevList`/`delDevList`/`removeDev`
  fields, plus `SendFile` to guessed paired-store paths, plus a real
  physical power-cycle -- the `DevList` survived all of it). The removal
  capability lives instead in the dongle's **built-in HTTP admin panel**,
  which the USB investigation never looked at:
  - The dongle runs a WiFi AP `AutoKit-8169` (WPA2-PSK, password
    `12345678`, BSSID `00:e0:4c:64:1b:24`). Joining it gets a DHCP lease
    on **`192.168.43.0/24`** (this unit -- *not* the `192.168.50.x` the
    generic Carlinkit docs claim), with the panel at
    **`http://192.168.43.1`** (a Vue SPA). The Pi has a single `wlan0`,
    so joining this AP drops the Pi's own network unless it also has
    `eth0` up -- pin SSH to the `eth0` IP first, then repurpose `wlan0`.
  - The panel's entire API is one endpoint: `POST /cgi-bin/server.cgi`,
    multipart form fields `cmd` / `item` / `val` / `ts` (ms) / `sign`
    (md5, computed by the panel JS). Observed calls:
    - **Remove one paired device:** `cmd=set, item=delDev,
      val=<MAC>` -> `{"err":0}`. Verified: removing `A4:CF:99:0B:A3:16`
      dropped the box's `DevList` from 4 to 3, confirmed by an
      independent USB `BoxInfo` read afterward.
    - Read full state (incl. `DevList`, `Settings`, `BoxInfo`):
      `cmd=infos`.
    - Reboot the dongle: `cmd=restart`.
  - Using the panel UI from a phone (join the AP, browse to
    `192.168.43.1`, delete the device) is the easy path -- the JS signs
    requests for you. It can also be scripted headless: the signing was
    reverse-engineered and `launcher/tools/ccpa_panel.py` implements it
    (see the full API section below).
  - Simpler alternatives that also work: the phone's own Settings ->
    General -> CarPlay -> (car) -> "Forget This Car", or a full wipe via
    the panel's factory reset / the physical pinhole reset button (clears
    ALL pairings + WiFi/BT config, so every phone re-pairs).
- **Don't bother with alternate/custom firmware.** Carlinkit added an
  activation-lock mechanism (`/etc/uuid_sign`) after community
  reverse-engineering became known to them; a firmware that fails
  activation has no known unlock path. There's also no documented live
  root/shell access to this hardware (no UART/SSH/telnet), only
  hardware flash programming, which isn't worth the bricking risk --
  especially now that device management is reachable through the stock
  web panel above without touching firmware at all.

### The dongle web panel API (`server.cgi`) -- full map

The panel at `http://192.168.43.1` is a Vue SPA; its entire backend is
one endpoint, `POST /cgi-bin/server.cgi` (multipart/form-data). Client:
`launcher/tools/ccpa_panel.py` (stdlib-only, works headless or through
an `ssh -D` SOCKS tunnel with `--proxy socks5h://127.0.0.1:1080`).

**Request signing** (reversed from `PublicV2.js` `signFormData`, verified
byte-for-byte against captured requests):

- Every request carries `ts` (epoch ms) and `sign`.
- `sign = md5( "k1=v1&k2=v2&..." + SALT )` where the pairs are all the
  other fields (`cmd`, `item`, `val`, `ts`, ...), **keys sorted
  ascending**, joined by `&`. `SALT = "HweL*@M@JEYUnvPw9G36MVB9X6u@2qxK"`
  (hardcoded in the JS bundle).
- Empty `item`/`val` are omitted entirely (not sent as empty) -- send
  them and the signature won't match, you get `403`.
- Only the activation call (`cmd=a`) already contains a field named
  `sign` (a cloud-issued one); `signFormData` renames it to `sg` before
  computing its own `sign`.

**Commands seen in the bundle / verified live:**

| `cmd` | args | effect | kind |
|---|---|---|---|
| `infos` | -- | full state: `CarInfo`, `BoxInfo`, `Settings` (49 keys), `DevList`, `LangList`, `WifiChannelList` | read |
| `BoxMonitor` | -- | live dongle telemetry: `CpuRate`, `CpuTemp`, `CpuFreq`, `MemRate`, `WifiRX`, `WifiTX` | read |
| `upgradeState` | -- | firmware-update progress: `err`, `progress`, `failReason` | read |
| `logFile` / `appLogFile` / `sdkLogFile` | -- | download an obfuscated log blob (prefixed `^^^^$$$`, ~MBs) | read |
| `set` | `item`,`val` | change one thing (see items below) | write |
| `carInfo` | `brand`/`model`/`year`/`userid` | set the car identity shown in the panel | write |
| `restart` | -- | reboot the dongle | action |
| `reset` / `resetApp` | -- | confirm-dialog resets in the UI (settings/app reset); **not tested here** -- treat as destructive | action |
| `a` | `is`,`code`,`sign`(->`sg`),`tabId`,`burnType` | activation handshake (ties to `BoxInfo.needActive=1` + the cloud call to `file.paplink.cn/ad/a/upgrade/check2Box`) | action |

**`cmd=set item=<...>`** items are the `Settings` keys from `infos`. The
panel bundle knows about 49 (`fps`, `gps`, `lang`, `micGain`, `MicMode`,
...), but **this unit's firmware only reports 14**: `CallQuality`,
`ScreenDPI`, `Udisk`, `autoConn`, `autoPlay`, `backRecording`, `bitRate`,
`displaySize`, `mediaDelay`, `mediaSound`, `naviVolume`, `startDelay`,
`wifi5GSwitch`, `wifiChannel`. Special items: **`delDev`** (`val=<MAC>`,
removes a paired device -- the whole point), `resetLogo` (`val=""`), and
`lang` (special-cased in the JS).

Two settings matter for audio (see "Audio" below):

- **`CallQuality`**: 0 = Norm, 1 = Clear, 2 = HD. **Must be 0 here.** At HD
  (2), the far end of a phone call hears nothing from the car mic, while
  Siri works fine. react-carplay always sends mic audio as 16 kHz mono, and
  HD call mode evidently expects something else. Set with
  `ccpa_panel.py set CallQuality 0`; it's stored on the dongle.
- **`mediaDelay`**: the dongle's audio jitter buffer in ms (panel default
  1000, range 300-2000). Setting it here is pointless: react-carplay
  overwrites it on every connect from its own `config.json`
  (`BoxSettings { mediaDelay }`), so change it there instead.

Quick examples:

```sh
# on a machine joined to the AutoKit-8169 AP (or add --proxy for a tunnel)
python3 launcher/tools/ccpa_panel.py listdev            # paired devices
python3 launcher/tools/ccpa_panel.py deldev A4:CF:99:0B:A3:16
python3 launcher/tools/ccpa_panel.py monitor            # cpu/temp/mem
python3 launcher/tools/ccpa_panel.py get wifiChannel
python3 launcher/tools/ccpa_panel.py set wifiChannel 149
```

To reach it from the Pi without a phone: the Pi's `wlan0` can join the
AP (see `AutoKit-8169`/`12345678` above) while SSH stays on `eth0`; or a
laptop can `ssh -D 1080 -N ajxd2@<pi-eth0-ip>` and point the tool at
`--proxy socks5h://127.0.0.1:1080`.

## What's actually running

- `launcher/server.py` (see below) is what autostarts, not
  `react-carplay.AppImage` directly. CarPlay is one of its apps.
- Desktop stack: `agetty` autologin on `tty1` → `.xinitrc` → `Xorg` →
  `openbox` (window manager) → autostart script launches the launcher +
  overlay tab, `pulseaudio`, `picom` (compositor), `unclutter`, `dunst` +
  `pi-monitor.sh` (see below).
- `picom` config lives in the repo at `launcher/system/picom.conf` (deployed
  by `launcher/deploy.sh`). App switching is an X unmap + map, which picom
  animates: the incoming app grows in from 96% as it fades up, the
  outgoing one fades out, and dunst notifications slide down from the top.
  It must stay on the `xrender` backend: the Pi's GPU fails picom's GL
  shader check (`GLSL 3.30 is not supported`). If picom dies, windows still
  draw, just without effects.
- No Docker, no other custom services beyond stock Bluetooth/PulseAudio.

## Boot splash

- The Plymouth theme is `carplay` (`/usr/share/plymouth/themes/carplay`),
  generated from a draft in `launcher/splash/`: each `N-name.html` is an
  800x480 page animated with CSS, and `render.py` steps it frame by frame in
  headless Chromium into a theme under `launcher/splash/build/<draft>/`
  (entrance frames played once, then a loop). Installed: `4-bulb-check`.
- Install with `launcher/splash/install.sh <draft>`. Plymouth runs from the
  initramfs, so the script rebuilds it in `overlayroot-chroot` (with
  `MODULES=most` and `FSTYPE=ext4` in a temporary config copy: the Pi's
  `MODULES=dep` can't find the root device in the chroot, and the fsck hook
  can't detect its type) and writes it to `initramfs8` on the FAT boot
  partition itself. It checks the new image holds the draft and `fsck.ext4`
  before touching the boot partition, and shows a progress card on the
  Pi's screen while it runs. Backups: `themes/carplay-rings`,
  `initramfs8.bak`, `cmdline.txt.bak`, `~/.xinitrc.orig`,
  `~/.bash_profile.orig`.
- Hand-off to X: `~/.bash_profile` (repo copy `launcher/system/bash_profile`)
  quits Plymouth with `--retain-splash` and starts Xorg with `-nocursor`, so
  no pointer is ever drawn. `~/.xinitrc` (`launcher/system/xinitrc`) sets
  the root background to the theme's `last_frame.png` and runs
  `launcher/splash/xsplash.py boot`, which keeps the splash loop playing
  until the launcher writes `/tmp/carplay_pi_launcher_winid` (Chromium takes
  ~10 s after X starts; without it the screen sat on a still frame).
  `vt.global_cursor_default=0` on the kernel command line hides the console
  text cursor.

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

- **`launcher/server.py`**: the backend, started by a respawn loop in
  openbox autostart. Stdlib-only (`http.server.ThreadingHTTPServer` -- no
  `pip`/Flask on this device, deliberately not installed for this). Owns
  the `APPS` list (only the real separate programs: CarPlay and Flappy
  Bird), process/window state, config, volume, and the JSON API the
  frontend calls: `/api/status` (one poll for app state, dongle presence,
  volume, night mode, clock sync), `/api/launch`, `/api/volume`,
  `/api/config`, `/api/dim`, `/api/info`, `/api/mic`, `/api/trip`,
  `/api/logs?source=launcher|carplay|system|kernel`, `/api/devices*`.
  Startup order: bind the HTTP port first, hand `wlan0` back if a previous
  run died mid-Phones-view, **kill any stale kiosk Chromium / CarPlay /
  Flappy left by a previous run** (a respawned server can't re-attach to
  them, and two CarPlays fight over the dongle's USB interface), start the
  persistence watcher and volume keeper, start Chromium, auto-launch.
  - Chromium's window gets `wm_helper.make_override_redirect()` applied
    once at startup: Chromium's kiosk/fullscreen state is *dynamic* (tied
    to visibility), so the plain unmap/map cycle `hide_window()`/
    `show_window()` use would otherwise let openbox re-decorate it
    (titlebar, borders, black margin) the first time you switch away and
    back. Override-redirect makes the WM stop managing the window, and it's
    re-pinned to `0,0 800x480`.
  - Wipes `/tmp/chromium-kiosk-profile` on every start: a leftover
    `SingletonLock` can make a fresh Chromium silently refuse to open.
  - **Window capture and X id reuse.** Apps are captured by waiting for
    focus to move to a new, big-enough window. When an app is killed and
    restarted, X can hand the new window the *same id* the dead one had,
    and openbox keeps reporting the dead id as active, so "focus moved to a
    new window" never fires (this showed up as "chromium window never
    appeared" and "no window found for CarPlay"). `get_active_window()`
    now ignores ids that no longer exist, and if the wait still times out,
    `find_window_for_pid_tree()` finds the app's window by process.
  - Each app's stdout/stderr goes to `/tmp/<app>.log`; CarPlay runs with
    `--enable-logging=stderr`, so `/tmp/carplay.log` has react-carplay's
    renderer console (`starting mic`, `UNDERFLOW`, connect events).
  - Night mode: the moon button writes `/sys/class/backlight/*/brightness`
    (`ajxd2` is in `video`, no sudo) so the whole physical screen dims,
    CarPlay included, and switches the launcher to a warmer, darker palette.
  - `python3 server.py --dev` serves the UI locally without Chromium, X, or
    any writes to `/media/root-ro`, for frontend work on another machine.
- **`launcher/web/`**: the frontend, plain HTML/CSS/JS, no build step, fonts
  bundled in `web/fonts/` (Barlow, OFL) since the device is usually offline.
  "Dash" style: graphite surfaces and one accent color, instrument-cluster
  amber, for anything lit (running app, active control, volume level). Home
  is a big CarPlay tile plus a 3x2 grid; everything else is an in-page view
  with a Back button, switched by `showView()` in `app.js`:
  - **Info**: CPU temp, power (undervoltage), dongle presence on USB, a live
    **microphone level meter** (samples the default source with `parec`),
    memory, SD card, IPs, and "cleared on reboot" (overlay RAM in use).
  - **Trip Calc**: trip fuel cost + unit conversion, press-and-hold
    steppers, values persisted across reboots.
  - **Logs**: launcher, CarPlay, system journal, kernel; native touch
    scrolling with a jump-to-newest button.
  - **Phones**: the dongle's paired phones, via its web panel (below).
  - **Settings**: open CarPlay or Flappy on startup; applies on tap.
  - The clock shows `--:--` / "Clock not set" until NTP has synced, rather
    than the stale time the Pi boots with (see "Clock" below).
- **`launcher/wm_helper.py`**: shared window-management + audio helpers
  used by `server.py` and `overlay_tab.py`: window capture (above), hide/
  show, override-redirect, and `apply_audio_priority(binary)`: **CarPlay
  always has audio priority**, its sink-inputs are unmuted on every app
  switch and whatever else is active gets muted instead.
- **`launcher/persist.py`**: all write-through to the real partition (see
  "Runtime state that survives reboot" below).
- **`launcher/overlay_tab.py`**: a small always-on-top "go home" tab,
  bottom-center of the screen. Built as a raw X11 **override-redirect**
  window (via `python3-xlib`) so it floats above *any* fullscreen app
  including CarPlay. Tapping it hides whatever's active and shows the
  launcher; nothing gets killed. It only reads the window id in
  `/tmp/carplay_pi_launcher_winid`. Drawn in the launcher's Dash palette:
  the face is pre-rendered with PIL (4x, scaled down for smooth edges) and
  the rounded top corners are cut with the X SHAPE extension. Without PIL it
  falls back to a plain square panel.
- **`launcher/launcher.py`** (+ `flappy.py`, `info.py`, `trip.py`,
  `logs.py`): the original pygame implementation. Not autostarted; kept as
  a manual fallback (tiles now laid out in two rows so all five fit the
  800px screen): SSH in, `pkill -9 -f chromium` and `pkill -9 -f
  server.py`, then `python3 /home/ajxd2/launcher/launcher.py` by hand.
  `flappy.py` is still what the new launcher's Flappy tile runs.
- **Phones view** (backed by `launcher/dongle.py`): lists the dongle's
  paired phones and forgets them, plus a live dongle CPU/temp/mem line. It
  talks to the dongle's web panel (`http://192.168.43.1/cgi-bin/server.cgi`)
  since the USB protocol can't edit the paired list. That panel is only
  reachable over the dongle's Wi-Fi AP, so opening the view **borrows
  `wlan0`** to join `AutoKit-8169`, and leaving it hands `wlan0` back via
  `wpa_cli reconfigure`. A generation counter makes sure a join that's
  still in flight when you leave hands `wlan0` back instead of parking it
  on the dongle's AP, and server startup does the same if a previous run
  died mid-view. Using this view interrupts an SSH-over-`wlan0` session
  (use `eth0`). `launcher/tools/ccpa_panel.py` is the standalone CLI
  equivalent (with working `--proxy socks5h://` support for an `ssh -D`
  tunnel).

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

- If `server.py` restarts (crash, redeploy), it can't re-attach to apps
  the previous run started, so it kills them on startup and starts clean;
  with auto-launch on, CarPlay comes straight back. Expect a few seconds of
  CarPlay reconnecting whenever the server restarts.
- Killing Chromium's process tree with `pkill -9 -f chromium` reliably
  drops the *current* SSH session for a couple of seconds (looks like a
  brief system-wide hiccup, maybe GPU/DRM cleanup on this Pi) even though
  the device itself is fine -- `deploy.sh` runs that kill as its own,
  last, `ssh` call for exactly this reason. If you're ever scripting
  something similar by hand, don't chain other cleanup commands after it
  in the same remote shell; they won't run.

- `launcher/deploy.sh [--autostart] [user@host]`: same `/media/root-ro`
  write-through pattern as `pi-monitor/deploy.sh`. Copies the launcher as
  one `tar` stream with `--overwrite` (files are rewritten in place: tar's
  default of replacing them with new inodes leaves the running overlay
  serving the old cached copies until reboot), installs `~/.asoundrc`, runs
  the idempotent react-carplay audio patch, then restarts the stack. If the
  autostart respawn loop is running it only kills the stack and lets the
  loop bring `server.py` back, never starting a second copy by hand. By
  default it **doesn't touch the openbox autostart file**; pass
  `--autostart` (after verifying on the real touchscreen) to install the
  launcher block and point the startup `amixer` lines at the USB adapter by
  name. Also installs the `chromium` apt package persistently if missing.

## Audio

Everything CarPlay plays (music, calls, Siri, navigation) arrives from the
phone over Wi-Fi to the dongle, then over USB to react-carplay, which plays
it through PulseAudio to the Unitek USB adapter (`card "Device"`). The mic
goes the other way: USB adapter -> PulseAudio -> react-carplay
(`getUserMedia`, 16 kHz mono) -> dongle -> phone, only while the phone asks
for it (`starting mic` / `stopping mic` in `/tmp/carplay.log`).

Fixes applied, and why:

- **Crackling: react-carplay's audio player had no jitter buffer.** Its
  AudioWorklet started playing the moment 128 frames (~3 ms) existed and
  went silent for a render quantum whenever the next packet was slightly
  late, which wireless CarPlay makes constant (20-35 `UNDERFLOW`s a minute
  in the log). `launcher/tools/patch_carplay_audio.py` extracts the
  AppImage once to `~/react-carplay` and swaps in
  `tools/carplay_audio_worklet.js`: it waits for 120 ms of audio before
  (re)starting, and if the buffer's *minimum* over 3 s stays 60 ms above
  that (slow clock drift, not a burst), drops the excess once so latency
  can't creep up on a long drive. Same-size in-place edit of `app.asar`,
  SHA-256-checked, idempotent, run by `deploy.sh`. `server.py` runs
  `~/react-carplay/AppRun` (with `APPDIR` set; `AppRun` can't find itself
  without it) and falls back to the stock AppImage if it's missing. Result:
  zero underflows in the same listening test. The original AppImage is
  untouched.
- **Mic dead on phone calls: dongle `CallQuality` was HD.** Set to Norm
  (0). See the dongle panel section.
- **react-carplay `mediaDelay` 300 -> 1000** (in
  `~/.config/react-carplay/config.json`, persisted): the dongle-side jitter
  buffer, which react-carplay pushes to the dongle on every connect. 300
  was the minimum; 1000 is the panel's default.
- **PulseAudio buffer**: `/etc/pulse/daemon.conf` had
  `default-fragment-size-msec = 15` with `tsched=0` in `default.pa` (about
  60 ms of buffer). Now 25 ms x `default-fragments = 8` (~200 ms), still
  `tsched=0`. Persisted to `/media/root-ro/etc/pulse/daemon.conf`.
- **`~/.asoundrc`** (repo: `launcher/system/asoundrc`) routes plain-ALSA
  programs through PulseAudio. The old one pinned `defaults.pcm.card 1`,
  but card numbers move between boots (1 is now HDMI, no capture) and
  those defaults only accept an index. Autostart's `amixer` lines use
  `-c Device` (the adapter's name) for the same reason.
- CarPlay's `height` in its config stays at **640** (react-carplay's
  default). 480 looked right until the window was hidden and shown again,
  after which CarPlay's page grew scrollbars.

## Runtime state that survives reboot

The launcher persists state through `launcher/persist.py`
(`write_through()`: remount `/media/root-ro` rw, write a temp file, sync,
rename, best-effort remount ro):

- `launcher/config.json` (startup app) and `launcher/trip_state.json`
  (Trip Calc values): written on change.
- `launcher/volume.json`: PulseAudio's own restore database lives on the
  tmpfs overlay and autostart forces 100% at boot, so `server.py` restores
  the saved level on startup and saves it once a change has held for ~4 s,
  whatever changed it.
- `~/.config/react-carplay/config.json`: react-carplay writes this itself
  when you change its settings; a watcher thread notices (every 3 s, only
  complete JSON) and persists it.

## Clock (no RTC)

The Pi 4 has no real-time clock and no `fake-hwclock` here, so every boot
starts at whatever time the image last held (currently Mar 31) until
`systemd-timesyncd` syncs over the network, which in the car may never
happen. The launcher shows `--:--` / "Clock not set" until
`timedatectl` reports `NTPSynchronized=yes`; CarPlay's own status bar
always shows the phone's time. Real fix: a DS3231 I2C RTC module (GPIO pins
1/3/5/9) plus `dtoverlay=i2c-rtc,ds3231` in `/boot/firmware/config.txt`,
seeded once with `sudo hwclock -w` while online.

## Security notes

- react-carplay listens on **`0.0.0.0:4000`** (socket.io) with no auth,
  reachable from any network the Pi joins. There's no firewall. A
  persistent nftables ruleset (allow `lo`, established, 22; drop the rest)
  would close it; test it carefully, since a mistake can lock out SSH.
- SSH is pubkey-only; the launcher API binds to `127.0.0.1`.

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
| Launcher / CarPlay logs | `/tmp/server_startup.log`, `/tmp/carplay.log` (or the Logs view) |
| Dongle settings | `python3 launcher/tools/ccpa_panel.py infos` (on the AutoKit Wi-Fi) |
| Re-apply the CarPlay audio patch | `sudo python3 ~/launcher/tools/patch_carplay_audio.py` |
| Frontend dev server | `cd launcher && python3 server.py --dev` |
| Fully reset the overlay / pick up new packages | `sudo reboot` |
