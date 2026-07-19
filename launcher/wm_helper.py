"""Shared window-management + audio-priority helpers for the launcher,
overlay tab, and any app that needs to coordinate with them. Uses
xdotool for window ops (works with openbox-managed windows, unlike the
override-redirect tab which deliberately bypasses the WM) and pactl for
per-app audio.
"""
import subprocess
import time

LAUNCHER_WINID_FILE = "/tmp/carplay_pi_launcher_winid"


def _run(*args):
    return subprocess.run(args, capture_output=True, text=True)


def get_active_window():
    r = _run("xdotool", "getactivewindow")
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def get_window_size(winid):
    r = _run("xdotool", "getwindowgeometry", "--shell", winid)
    if r.returncode != 0:
        return None
    w = h = None
    for line in r.stdout.splitlines():
        if line.startswith("WIDTH="):
            w = int(line.split("=", 1)[1])
        elif line.startswith("HEIGHT="):
            h = int(line.split("=", 1)[1])
    return (w, h) if w is not None and h is not None else None


def wait_for_new_active_window(previous_id, timeout=15.0, interval=0.2, min_w=400, min_h=300):
    """Waits for focus to land on a window that's actually big enough to
    be the real app, not a transient helper/splash window some apps
    (Electron in particular) briefly create and focus during startup."""
    elapsed = 0.0
    while elapsed < timeout:
        cur = get_active_window()
        if cur and cur != previous_id:
            size = get_window_size(cur)
            if size and size[0] >= min_w and size[1] >= min_h:
                return cur
        time.sleep(interval)
        elapsed += interval
    return None


def hide_window(winid):
    if winid:
        _run("xdotool", "windowunmap", winid)


def show_window(winid):
    if winid:
        _run("xdotool", "windowmap", winid)
        _run("xdotool", "windowactivate", winid)
        _run("xdotool", "windowraise", winid)


def write_launcher_winid(winid):
    with open(LAUNCHER_WINID_FILE, "w") as f:
        f.write(winid)


def read_launcher_winid():
    try:
        with open(LAUNCHER_WINID_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def find_sink_inputs(binary_substring):
    """A single app can own more than one sink-input (CarPlay does), and
    stale ones from earlier processes can linger, so this returns every
    match rather than assuming there's only one."""
    r = _run("pactl", "list", "sink-inputs")
    cur_idx = None
    found = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("Sink Input #"):
            cur_idx = line.split("#", 1)[1]
        if "application.process.binary" in line and binary_substring in line:
            found.append(cur_idx)
    return found


def set_app_mute(binary_substring, mute):
    for idx in find_sink_inputs(binary_substring):
        _run("pactl", "set-sink-input-mute", idx, "1" if mute else "0")


def apply_audio_priority(active_binary):
    """CarPlay always stays unmuted and is never touched by app-switching;
    whatever else is active gets muted so it can never compete with it."""
    set_app_mute("react-carplay", False)
    if active_binary and active_binary != "react-carplay":
        set_app_mute(active_binary, True)
