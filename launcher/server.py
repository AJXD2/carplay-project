#!/usr/bin/env python3
"""Launcher backend: serves the kiosk web UI and owns app/process state.

Replaces the old pygame launcher.py. Spawns Chromium in kiosk mode pointed
at its own local HTTP server, and treats Chromium's window exactly like any
other app window via wm_helper (captured, then registered as "home" for
overlay_tab.py).

Manual recovery if this ever gets stuck: SSH in, `pkill -9 -f chromium` and
`pkill -9 -f server.py`, then run `python3 /home/ajxd2/launcher/launcher.py`
by hand for the old pygame fallback UI.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import wm_helper as wm

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(SCRIPT_DIR, "web")
ICON_DIR = os.path.join(SCRIPT_DIR, "assets", "icons")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
CONFIG_REMOTE_PATH = "/media/root-ro/home/ajxd2/launcher/config.json"
AUTOLAUNCH_LOG = "/tmp/launcher_autolaunch.log"
STARTUP_LOG = "/tmp/server_startup.log"

HOST, PORT = "127.0.0.1", 8734
CHROMIUM_PROFILE = "/tmp/chromium-kiosk-profile"

APPS = [
    {
        "name": "CarPlay",
        "note": "stays running in background",
        "cmd": ["/home/ajxd2/react-carplay.AppImage", "--no-sandbox"],
        "binary": "react-carplay",
        "icon": "carplay",
        "proc": None,
        "winid": None,
    },
    {
        "name": "Flappy Bird",
        "note": "tap the tab to come back",
        "cmd": ["python3", f"{SCRIPT_DIR}/flappy.py"],
        "binary": "python3",
        "icon": "flappy",
        "proc": None,
        "winid": None,
    },
    {
        "name": "Info",
        "note": "live system status",
        "cmd": ["python3", f"{SCRIPT_DIR}/info.py"],
        "binary": "python3",
        "icon": "info",
        "proc": None,
        "winid": None,
    },
    {
        "name": "Trip Calc",
        "note": "unit + fuel cost calc",
        "cmd": ["python3", f"{SCRIPT_DIR}/trip.py"],
        "binary": "python3",
        "icon": "trip",
        "proc": None,
        "winid": None,
    },
    {
        "name": "Logs",
        "note": "view system + autolaunch logs",
        "cmd": ["python3", f"{SCRIPT_DIR}/logs.py"],
        "binary": "python3",
        "icon": "logs",
        "proc": None,
        "winid": None,
    },
]

launcher_winid = None
launching = False


def log(msg):
    try:
        with open(STARTUP_LOG, "a") as f:
            f.write(f"{time.ctime()}: {msg}\n")
    except Exception:
        pass


def find_app(name):
    return next((a for a in APPS if a["name"] == name), None)


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
    try:
        subprocess.run(["sudo", "mount", "-o", "remount,rw", "/media/root-ro"], check=True)
        subprocess.run(
            ["sudo", "tee", CONFIG_REMOTE_PATH],
            input=json.dumps(cfg),
            text=True,
            stdout=subprocess.DEVNULL,
            check=True,
        )
        return True
    except Exception:
        return False
    finally:
        subprocess.run(["sudo", "mount", "-o", "remount,ro", "/media/root-ro"])


config = load_config()


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


def open_app(app):
    """Launch (or refocus) an app, hiding the launcher (Chromium) window.
    Only hides the launcher once the app's window is confirmed -- if it
    never showed up (e.g. a broken auto-launch default on boot), leaving
    the launcher hidden with nothing focused would strand the user on a
    blank screen with nothing to tap.
    """
    global launching
    launching = True
    try:
        if app["proc"] is None or app["proc"].poll() is not None:
            prev_active = wm.get_active_window()
            app["proc"] = subprocess.Popen(app["cmd"])
            app["winid"] = wm.wait_for_new_active_window(prev_active, timeout=15.0)
        if app["winid"]:
            wm.hide_window(launcher_winid)
            wm.show_window(app["winid"])
        wm.apply_audio_priority(app["binary"])
    finally:
        launching = False
    return app["winid"] is not None


def try_auto_launch():
    if not (config.get("auto_launch") and config.get("default_app")):
        return
    target = find_app(config["default_app"])
    if not target:
        return
    ok = open_app(target)
    if not ok:
        log(f"auto-launch failed for {target['name']}")


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
    subprocess.Popen([
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
    ])
    launcher_winid = wm.wait_for_new_active_window(prev_active, timeout=20.0)
    if launcher_winid:
        wm.make_override_redirect(launcher_winid)
        wm.write_launcher_winid(launcher_winid)
        wm.show_window(launcher_winid)
    else:
        log("chromium window never appeared")


MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep stdout/stderr quiet; use log() for anything that matters

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        if path == "/":
            path = "/index.html"
        if path.startswith("/assets/icons/"):
            fs_path = os.path.join(ICON_DIR, os.path.basename(path))
        else:
            fs_path = os.path.join(WEB_DIR, path.lstrip("/"))
        fs_path = os.path.abspath(fs_path)
        if not (fs_path.startswith(os.path.abspath(WEB_DIR)) or fs_path.startswith(os.path.abspath(ICON_DIR))):
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
        if self.path == "/api/apps":
            self._json(200, [
                {"name": a["name"], "note": a["note"], "icon": a["icon"],
                 "running": a["proc"] is not None and a["proc"].poll() is None}
                for a in APPS
            ])
        elif self.path == "/api/volume":
            self._json(200, {"percent": get_volume()})
        elif self.path == "/api/config":
            self._json(200, config)
        elif self.path == "/api/dim":
            self._json(200, {"dimmed": get_dimmed()})
        else:
            self._static(self.path)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw)
        except Exception:
            data = {}

        if self.path == "/api/launch":
            global launching
            if launching:
                self._json(409, {"ok": False, "reason": "already launching"})
                return
            app = find_app(data.get("name"))
            if not app:
                self._json(404, {"ok": False, "reason": "unknown app"})
                return
            ok = open_app(app)
            self._json(200, {"ok": ok, "winid": app["winid"]})
        elif self.path == "/api/volume":
            if "percent" in data:
                new_vol = set_volume(int(data["percent"]))
            else:
                new_vol = set_volume(get_volume() + int(data.get("delta", 0)))
            self._json(200, {"percent": new_vol})
        elif self.path == "/api/config":
            cfg = {"default_app": data.get("default_app"), "auto_launch": bool(data.get("auto_launch"))}
            ok = save_config(cfg)
            if ok:
                config.update(cfg)
            self._json(200, {"ok": ok})
        elif self.path == "/api/dim":
            dimmed = bool(data.get("dimmed"))
            ok = set_dimmed(dimmed)
            self._json(200, {"ok": ok, "dimmed": dimmed if ok else get_dimmed()})
        else:
            self._json(404, {"ok": False, "reason": "not found"})


def main():
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
        import threading
        threading.Thread(target=server.serve_forever, daemon=True).start()
        start_chromium_and_wait()
        try_auto_launch()
        while True:
            time.sleep(3600)
    except Exception:
        log("fatal error:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
