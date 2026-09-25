#!/usr/bin/env python3
"""Launcher backend: serves the kiosk web UI and owns app/process state.

Replaces the old pygame launcher.py. Spawns Chromium in kiosk mode pointed
at its own local HTTP server, and treats Chromium's window exactly like any
other app window via wm_helper (captured, then registered as "home" for
overlay_tab.py).

Only real separate programs (CarPlay, Flappy Bird) are spawned as apps.
Info, Trip Calc, Logs, Devices and Settings are in-page views of the kiosk,
backed by the small JSON API below.

Manual recovery if this ever gets stuck: SSH in, `pkill -9 -f chromium` and
`pkill -9 -f server.py`, then run `python3 /home/ajxd2/launcher/launcher.py`
by hand for the old pygame fallback UI.

`python3 server.py --dev` serves the UI on http://127.0.0.1:8734 without
spawning Chromium, touching X, or writing to /media/root-ro -- for working
on the frontend from a laptop.
"""
import glob
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import dongle
import persist
import wm_helper as wm

DEV = "--dev" in sys.argv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(SCRIPT_DIR, "web")
ICON_DIR = os.path.join(SCRIPT_DIR, "assets", "icons")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
TRIP_PATH = os.path.join(SCRIPT_DIR, "trip_state.json")
VOLUME_PATH = os.path.join(SCRIPT_DIR, "volume.json")
LAUNCHER_LOG = "/tmp/server_startup.log"
CARPLAY_CONFIG = "~/.config/react-carplay/config.json"

HOST, PORT = "127.0.0.1", 8734
CHROMIUM_PROFILE = "/tmp/chromium-kiosk-profile"
CARPLAY_APPIMAGE = "/home/ajxd2/react-carplay.AppImage"
# Extracted + audio-patched copy installed by tools/patch_carplay_audio.py
# (adds a jitter buffer to react-carplay's audio player to stop crackling).
# Falls back to the stock AppImage if it's missing.
CARPLAY_PATCHED = "/home/ajxd2/react-carplay/AppRun"
CARPLAY_BIN = CARPLAY_PATCHED if os.path.exists(CARPLAY_PATCHED) else CARPLAY_APPIMAGE

APPS = [
    {
        "name": "CarPlay",
        # --enable-logging=stderr makes Electron print the renderer's
        # console (e.g. react-carplay's "starting mic") into /tmp/carplay.log.
        "cmd": [CARPLAY_BIN, "--no-sandbox", "--enable-logging=stderr"],
        "binary": "react-carplay",
        # AppRun normally gets APPDIR from the AppImage runtime; without it,
        # it guesses from its first argument and fails.
        "env": {"APPDIR": os.path.dirname(CARPLAY_PATCHED)},
        "log": "/tmp/carplay.log",
        "proc": None,
        "winid": None,
    },
    {
        "name": "Flappy Bird",
        "cmd": ["python3", f"{SCRIPT_DIR}/flappy.py"],
        "binary": "python3",
        "log": "/tmp/flappy.log",
        "proc": None,
        "winid": None,
    },
]

launcher_winid = None
launch_lock = threading.Lock()
dongle_mgr = dongle.DongleManager()


def log(msg):
    try:
        with open(LAUNCHER_LOG, "a") as f:
            f.write(f"{time.ctime()}: {msg}\n")
    except Exception:
        pass


def find_app(name):
    return next((a for a in APPS if a["name"] == name), None)


def app_running(app):
    return app["proc"] is not None and app["proc"].poll() is None


def persist_file(path, text):
    """Write a small state file so it survives reboot. In --dev mode, just
    write it locally."""
    if DEV:
        with open(path, "w") as f:
            f.write(text)
        return True
    return persist.write_through(path, text)


# -- launcher config --------------------------------------------------------

def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        if cfg.get("default_app") in [a["name"] for a in APPS]:
            return {"default_app": cfg["default_app"], "auto_launch": bool(cfg.get("auto_launch"))}
    except Exception:
        pass
    return {"default_app": None, "auto_launch": False}


def save_config(cfg):
    return persist_file(CONFIG_PATH, json.dumps(cfg))


config = load_config()


# -- trip calc state ----------------------------------------------------------

TRIP_DEFAULTS = {"speed_mph": 60.0, "distance_mi": 10.0, "gallons_price": 3.50,
                 "mpg": 28.0, "temp_f": 70.0}


def load_trip():
    state = dict(TRIP_DEFAULTS)
    try:
        with open(TRIP_PATH) as f:
            data = json.load(f)
        state.update({k: float(v) for k, v in data.items() if k in TRIP_DEFAULTS})
    except Exception:
        pass
    return state


def save_trip(data):
    state = load_trip()
    for k, v in data.items():
        if k in TRIP_DEFAULTS:
            v = float(v)
            if math.isfinite(v):
                state[k] = v if k == "temp_f" else max(0.0, v)
    return persist_file(TRIP_PATH, json.dumps(state)), state


# -- volume / backlight -----------------------------------------------------

def get_volume():
    try:
        out = subprocess.check_output(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], text=True)
        return int(out.split("/")[1].strip().rstrip("%"))
    except Exception:
        return -1


def set_volume(pct):
    pct = max(0, min(100, pct))
    subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{pct}%"])
    return pct


# Volume survives reboot: PulseAudio's own restore database lives in
# ~/.config/pulse on the tmpfs overlay (lost every power cut), and openbox
# autostart forces 100% at boot. So the launcher remembers the level itself,
# restores it on startup, and persists it once a change has settled -- no
# matter what changed it (the volume bar, CarPlay, pactl over SSH).
VOLUME_SETTLE_S = 4


def load_saved_volume():
    try:
        with open(VOLUME_PATH) as f:
            pct = int(json.load(f)["percent"])
        return pct if 0 <= pct <= 100 else None
    except Exception:
        return None


class VolumeKeeper(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.saved = load_saved_volume()

    def restore(self):
        if self.saved is not None:
            set_volume(self.saved)
            log(f"restored volume to {self.saved}%")

    def run(self):
        last = None
        while True:
            time.sleep(VOLUME_SETTLE_S)
            cur = get_volume()
            # only persist once the level has held for a full interval, so
            # dragging the slider doesn't remount the SD card every step
            if cur >= 0 and cur == last and cur != self.saved:
                if persist_file(VOLUME_PATH, json.dumps({"percent": cur})):
                    self.saved = cur
            last = cur


# Real backlight control (not just a CSS overlay) -- ajxd2 is in the
# `video` group so this is writable without sudo, and it dims the whole
# physical screen (CarPlay included), which is the actual point of a
# night-driving dim, not just the launcher's own page.
_backlight_candidates = glob.glob("/sys/class/backlight/*/brightness")
BACKLIGHT_PATH = _backlight_candidates[0] if _backlight_candidates else None
BACKLIGHT_MAX_PATH = BACKLIGHT_PATH.replace("brightness", "max_brightness") if BACKLIGHT_PATH else None
BACKLIGHT_DIM_FRACTION = 0.12


def _backlight_max():
    try:
        with open(BACKLIGHT_MAX_PATH) as f:
            return int(f.read().strip())
    except Exception:
        return 255


def get_dimmed():
    if not BACKLIGHT_PATH:
        return False
    try:
        with open(BACKLIGHT_PATH) as f:
            current = int(f.read().strip())
        return current <= _backlight_max() * BACKLIGHT_DIM_FRACTION + 1
    except Exception:
        return False


def set_dimmed(dimmed):
    if not BACKLIGHT_PATH:
        return False
    try:
        maxb = _backlight_max()
        level = int(maxb * BACKLIGHT_DIM_FRACTION) if dimmed else maxb
        with open(BACKLIGHT_PATH, "w") as f:
            f.write(str(level))
        return True
    except Exception:
        return False


# The UI's night palette follows this flag, not the backlight reading, so
# night mode still works (and survives a Chromium reload) on a screen
# without a controllable backlight.
night_mode = get_dimmed()


# -- info view --------------------------------------------------------------

def _sh(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        return ""


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


THROTTLE_BITS = [
    (0x1, "Undervoltage now"), (0x2, "Frequency capped now"), (0x4, "Throttled now"),
    (0x10000, "Undervoltage since boot"), (0x20000, "Frequency capped since boot"),
    (0x40000, "Throttled since boot"),
]


def get_throttle():
    m = re.search(r"0x([0-9a-fA-F]+)", _sh(["vcgencmd", "get_throttled"]))
    if not m:
        return {"ok": None, "flags": []}
    bits = int(m.group(1), 16)
    flags = [label for bit, label in THROTTLE_BITS if bits & bit]
    return {"ok": not flags, "flags": flags}


def get_ip(iface):
    m = re.search(r"inet (\S+)/", _sh(["ip", "-4", "-o", "addr", "show", iface]))
    return m.group(1) if m else None


def get_disk(path):
    try:
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        used = total - st.f_bfree * st.f_frsize
        return {"used": used, "total": total}
    except OSError:
        return None


def get_mem():
    info = {}
    for line in (_read("/proc/meminfo") or "").splitlines():
        k, _, v = line.partition(":")
        info[k.strip()] = int(v.split()[0]) * 1024 if v.split() else 0
    total = info.get("MemTotal", 0)
    return {"used": total - info.get("MemAvailable", 0), "total": total}


def time_synced():
    """True once systemd-timesyncd has set the clock from NTP this boot. The
    Pi has no RTC, so until then the clock is whatever the last boot image
    held (months stale), and showing it would be confidently wrong."""
    if DEV:
        return True
    return _sh(["timedatectl", "show", "-p", "NTPSynchronized", "--value"]) == "yes"


def dongle_on_usb():
    for path in glob.glob("/sys/bus/usb/devices/*/idVendor"):
        if _read(path) == "1314":
            return True
    return False


def get_info():
    temp = _read("/sys/class/thermal/thermal_zone0/temp")
    uptime = _read("/proc/uptime")
    load = (_read("/proc/loadavg") or "").split()[:3]
    return {
        "hostname": socket.gethostname(),
        "uptime_s": int(float(uptime.split()[0])) if uptime else None,
        "temp_c": int(temp) / 1000 if temp else None,
        "throttle": get_throttle(),
        "load": [float(x) for x in load],
        "cpus": os.cpu_count(),
        "mem": get_mem(),
        "sd": get_disk("/media/root-ro" if os.path.isdir("/media/root-ro") else "/"),
        "overlay": get_disk("/media/root-rw") if os.path.isdir("/media/root-rw") else None,
        "eth0": get_ip("eth0"),
        "wlan0": get_ip("wlan0"),
        "wifi_ssid": dongle.current_ssid() if not DEV else None,
        "volume": get_volume(),
        "dongle_usb": dongle_on_usb(),
        "carplay_running": app_running(APPS[0]),
    }


def get_mic_level(seconds=0.35):
    """Sample the default capture source briefly and return its level in
    dBFS, so a dead or unplugged mic is visible from the Info view."""
    try:
        r = subprocess.run(
            ["timeout", str(seconds), "parec", "--format=s16le", "--channels=1",
             "--rate=16000", "--raw", "--latency-msec=50"],
            capture_output=True, timeout=seconds + 2)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    data = r.stdout
    n = len(data) // 2
    if n == 0:
        return {"ok": False, "error": "no audio captured"}
    samples = memoryview(data[: n * 2]).cast("h")
    peak = max(abs(s) for s in samples) or 1
    rms = math.sqrt(sum(s * s for s in samples) / n) or 1
    return {"ok": True,
            "peak_db": round(20 * math.log10(peak / 32768), 1),
            "rms_db": round(20 * math.log10(rms / 32768), 1),
            "source": _sh(["pactl", "get-default-source"])}


# -- logs view --------------------------------------------------------------

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _tail_file(path, n):
    try:
        with open(path, errors="replace") as f:
            return f.read().splitlines()[-n:]
    except OSError:
        return [f"{path} doesn't exist yet."]


LOG_SOURCES = {
    "launcher": lambda n: _tail_file(LAUNCHER_LOG, n),
    "carplay": lambda n: _tail_file(APPS[0]["log"], n),
    "system": lambda n: _sh(["journalctl", "-n", str(n), "--no-pager", "-o", "short"]).splitlines(),
    "kernel": lambda n: _sh(["dmesg"]).splitlines()[-n:],
}


def get_logs(source, n=300):
    fn = LOG_SOURCES.get(source)
    if not fn:
        return None
    return [ANSI.sub("", line) for line in fn(n)]


# -- apps -------------------------------------------------------------------

def spawn(app):
    out = open(app["log"], "ab")
    try:
        return subprocess.Popen(app["cmd"], stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env={**os.environ, **app.get("env", {})})
    finally:
        out.close()


def open_app(app):
    """Launch (or refocus) an app, hiding the launcher (Chromium) window.
    Only hides the launcher once the app's window is confirmed -- if it
    never showed up (e.g. a broken auto-launch default on boot), leaving
    the launcher hidden with nothing focused would strand the user on a
    blank screen with nothing to tap.
    """
    if not app_running(app):
        prev_active = wm.get_active_window()
        app["proc"] = spawn(app)
        app["winid"] = wm.wait_for_new_active_window(prev_active, timeout=15.0)
        if app["winid"] is None:
            # A restarted app can get the exact window id its dead
            # predecessor had (X reuses client id ranges), so "focus moved
            # to a new window" never fires. Find it by process instead.
            app["winid"] = wm.find_window_for_pid_tree(app["proc"].pid)
    elif app["winid"] is None:
        # Still running but its window was never captured (slow cold start
        # outlived the wait above): look it up by process instead of
        # leaving the tile dead until the process exits.
        app["winid"] = wm.find_window_for_pid_tree(app["proc"].pid)
    if app["winid"]:
        wm.hide_window(launcher_winid)
        wm.show_window(app["winid"])
    else:
        log(f"no window found for {app['name']}")
    wm.apply_audio_priority(app["binary"])
    return app["winid"] is not None


def try_auto_launch():
    if not (config.get("auto_launch") and config.get("default_app")):
        return
    target = find_app(config["default_app"])
    if not target:
        return
    with launch_lock:
        ok = open_app(target)
    if not ok:
        log(f"auto-launch failed for {target['name']}")


def kill_stale_processes():
    """server.py runs under a respawn loop in openbox autostart. If a previous
    instance crashed, its Chromium and CarPlay are still alive but no longer
    tracked; a second CarPlay would fight the first for the USB dongle, so
    clear them out and start clean."""
    subprocess.run(["pkill", "-9", "-f", "--", f"--user-data-dir={CHROMIUM_PROFILE}"])
    subprocess.run(["pkill", "-9", "-x", "react-carplay"])  # the AppImage's Electron processes
    subprocess.run(["pkill", "-9", "-f", CARPLAY_APPIMAGE])  # its mount wrapper
    subprocess.run(["pkill", "-9", "-f", f"{SCRIPT_DIR}/flappy.py"])
    time.sleep(1)


def start_chromium_and_wait():
    global launcher_winid
    # server.py is the sole owner of Chromium's lifecycle, so a leftover
    # profile dir from a prior run of this process (e.g. a -9 kill during
    # testing, which leaves SingletonLock/SingletonSocket behind) can make
    # a fresh Chromium think another instance already owns it and refuse
    # to open a window -- wipe it on every start for a guaranteed-clean
    # profile instead of reusing a possibly-stale one across restarts.
    shutil.rmtree(CHROMIUM_PROFILE, ignore_errors=True)
    os.makedirs(CHROMIUM_PROFILE, exist_ok=True)
    prev_active = wm.get_active_window()
    proc = subprocess.Popen([
        "chromium",
        "--kiosk",
        f"--app=http://{HOST}:{PORT}/",
        "--noerrdialogs",
        "--disable-infobars",
        "--disable-session-crashed-bubble",
        "--overscroll-history-navigation=0",
        "--disable-pinch",
        f"--user-data-dir={CHROMIUM_PROFILE}",
        "--no-first-run",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    launcher_winid = wm.wait_for_new_active_window(prev_active, timeout=20.0)
    if not launcher_winid:
        # a restarted Chromium can reuse its predecessor's window id, so the
        # focus-change wait above never fires; find the window by process
        launcher_winid = wm.find_window_for_pid_tree(proc.pid)
    if launcher_winid:
        wm.make_override_redirect(launcher_winid)
        wm.write_launcher_winid(launcher_winid)
        wm.show_window(launcher_winid)
    else:
        log("chromium window never appeared")


# -- HTTP -------------------------------------------------------------------

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}


def _inside(path, root):
    root = os.path.abspath(root)
    return os.path.commonpath([path, root]) == root


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep stdout/stderr quiet; use log() for anything that matters

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        if path == "/":
            path = "/index.html"
        if path.startswith("/assets/icons/"):
            fs_path = os.path.join(ICON_DIR, os.path.basename(path))
        else:
            fs_path = os.path.join(WEB_DIR, urllib.parse.unquote(path).lstrip("/"))
        fs_path = os.path.abspath(fs_path)
        if not (_inside(fs_path, WEB_DIR) or _inside(fs_path, ICON_DIR)):
            self.send_response(404)
            self.end_headers()
            return
        ext = os.path.splitext(fs_path)[1]
        try:
            with open(fs_path, "rb") as f:
                body = f.read()
        except OSError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", MIME_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path, query = url.path, urllib.parse.parse_qs(url.query)
        if path == "/api/status":
            # one cheap poll for everything the home screen shows
            self._json(200, {
                "apps": [{"name": a["name"], "running": app_running(a)} for a in APPS],
                "dongle_usb": dongle_on_usb(),
                "time_synced": time_synced(),
                "volume": get_volume(),
                "dimmed": night_mode,
            })
        elif path == "/api/volume":
            self._json(200, {"percent": get_volume()})
        elif path == "/api/config":
            self._json(200, config)
        elif path == "/api/dim":
            self._json(200, {"dimmed": night_mode})
        elif path == "/api/info":
            self._json(200, get_info())
        elif path == "/api/mic":
            self._json(200, get_mic_level())
        elif path == "/api/trip":
            self._json(200, load_trip())
        elif path == "/api/logs":
            lines = get_logs(query.get("source", ["launcher"])[0])
            if lines is None:
                self._json(404, {"ok": False, "reason": "unknown source"})
            else:
                self._json(200, {"lines": lines})
        elif path == "/api/devices":
            # Opening the Devices view: kick off the wlan0 join if needed and
            # report a simple state the UI can show a skeleton against. Only
            # actually query the dongle once the link is up.
            dongle_mgr.ensure_connecting()
            status = dongle_mgr.status()
            payload = {"state": status["state"], "error": status["error"],
                       "devices": None, "monitor": None}
            if status["state"] == "ready":
                try:
                    payload["devices"] = dongle_mgr.devices()
                    payload["monitor"] = dongle_mgr.monitor()
                except Exception as e:
                    payload["state"] = "error"
                    payload["error"] = f"dongle query failed: {e}"
            self._json(200, payload)
        else:
            self._static(path)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}

        try:
            self._post(data)
        except (ValueError, TypeError) as e:
            self._json(400, {"ok": False, "reason": str(e)})

    def _post(self, data):
        if self.path == "/api/launch":
            app = find_app(data.get("name"))
            if not app:
                self._json(404, {"ok": False, "reason": "unknown app"})
                return
            if DEV:
                self._json(200, {"ok": False, "reason": "dev mode"})
                return
            if not launch_lock.acquire(blocking=False):
                self._json(409, {"ok": False, "reason": "already launching"})
                return
            try:
                ok = open_app(app)
            finally:
                launch_lock.release()
            self._json(200, {"ok": ok})
        elif self.path == "/api/volume":
            if "percent" in data:
                new_vol = set_volume(int(data["percent"]))
            else:
                new_vol = set_volume(get_volume() + int(data.get("delta", 0)))
            self._json(200, {"percent": new_vol})
        elif self.path == "/api/config":
            default_app = data.get("default_app")
            if default_app is not None and not find_app(default_app):
                self._json(400, {"ok": False, "reason": "unknown app"})
                return
            cfg = {"default_app": default_app, "auto_launch": bool(data.get("auto_launch"))}
            ok = save_config(cfg)
            if ok:
                config.update(cfg)
            self._json(200, {"ok": ok})
        elif self.path == "/api/trip":
            ok, state = save_trip(data)
            self._json(200, {"ok": ok, "state": state})
        elif self.path == "/api/dim":
            global night_mode
            night_mode = bool(data.get("dimmed"))
            backlight = set_dimmed(night_mode)
            self._json(200, {"ok": True, "backlight": backlight, "dimmed": night_mode})
        elif self.path == "/api/devices/remove":
            mac = data.get("mac")
            if not mac:
                self._json(400, {"ok": False, "reason": "missing mac"})
                return
            try:
                ok = dongle_mgr.remove(mac)
            except Exception as e:
                self._json(200, {"ok": False, "reason": str(e)})
                return
            self._json(200, {"ok": ok})
        elif self.path == "/api/devices/disconnect":
            # Leaving the Devices view: hand wlan0 back to its home network so
            # the app never permanently hijacks the Pi's Wi-Fi.
            ok = dongle_mgr.disconnect()
            self._json(200, {"ok": ok})
        else:
            self._json(404, {"ok": False, "reason": "not found"})


def main():
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        if DEV:
            print(f"dev mode: http://{HOST}:{PORT}/")
            while True:
                time.sleep(3600)
        log("starting")
        dongle_mgr.reset_on_startup()
        kill_stale_processes()
        persist.Watcher([CARPLAY_CONFIG], log=log).start()
        volume_keeper = VolumeKeeper()
        volume_keeper.restore()
        volume_keeper.start()
        start_chromium_and_wait()
        try_auto_launch()
        while True:
            time.sleep(3600)
    except Exception:
        log("fatal error:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
