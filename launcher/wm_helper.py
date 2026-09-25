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
    """The focused window, or None. After the focused app is killed, openbox
    can keep reporting its (now destroyed) id as active; the next app that
    starts may then be handed that very same id by X, so treating the dead
    id as a baseline would make wait_for_new_active_window() miss the new
    window entirely. A window that no longer exists doesn't count."""
    r = _run("xdotool", "getactivewindow")
    winid = r.stdout.strip() if r.returncode == 0 else ""
    if not winid or _run("xdotool", "getwindowname", winid).returncode != 0:
        return None
    return winid


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


def _pid_tree(pid):
    pids, frontier = [], [str(pid)]
    while frontier:
        cur = frontier.pop()
        pids.append(cur)
        r = _run("pgrep", "-P", cur)
        frontier.extend(r.stdout.split())
    return pids


def find_window_for_pid_tree(pid, min_w=400, min_h=300):
    """Find an already-mapped app window by process rather than by focus
    change. Used when wait_for_new_active_window() timed out (a slow cold
    start) but the app came up afterwards: without this, the app's tile
    would stay dead until the process exited. Walks the whole process tree
    because an AppImage's window belongs to a child, not the wrapper."""
    best, best_area = None, 0
    for p in _pid_tree(pid):
        r = _run("xdotool", "search", "--onlyvisible", "--pid", p)
        for winid in r.stdout.split():
            size = get_window_size(winid)
            if size and size[0] >= min_w and size[1] >= min_h and size[0] * size[1] > best_area:
                best, best_area = winid, size[0] * size[1]
    return best


def hide_window(winid):
    if winid:
        _run("xdotool", "windowunmap", winid)


def show_window(winid):
    if winid:
        _run("xdotool", "windowmap", winid)
        _run("xdotool", "windowactivate", winid)
        _run("xdotool", "windowraise", winid)


def make_override_redirect(winid, width=800, height=480):
    """Strip WM decorations permanently and keep them stripped.

    Chromium's --kiosk fullscreen/undecorated state is dynamic (tied to
    window visibility), unlike a plain NOFRAME window attribute -- so once
    this window gets unmapped/remapped by hide_window()/show_window() (e.g.
    switching to another app and back), Chromium can drop out of fullscreen
    and openbox then re-applies its default titlebar/border on the next
    map. Marking the window override-redirect makes the WM stop managing it
    entirely (the same technique overlay_tab.py already uses natively via
    Xlib), so no unmap/map cycle can ever bring decorations back. Requires
    an unmap/map cycle of its own to actually drop an existing WM frame.
    """
    if not winid:
        return
    _run("xdotool", "set_window", "--overrideredirect", "1", winid)
    _run("xdotool", "windowunmap", winid)
    _run("xdotool", "windowmap", winid)
    # Before override-redirect took effect, openbox may have briefly framed
    # this window in a decorated frame and positioned/sized the *client*
    # inset within it (e.g. X=10,Y=20,780x455 for a ~10px border + ~20px
    # titlebar) -- that inset geometry sticks around even after the frame
    # itself is gone, showing up as a black border around the kiosk UI.
    # Pin it back to exactly fill the screen.
    _run("xdotool", "windowmove", winid, "0", "0")
    _run("xdotool", "windowsize", winid, str(width), str(height))


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
