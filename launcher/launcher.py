#!/usr/bin/env python3
import pygame, subprocess, sys, os, time, json
import wm_helper as wm

W, H = 800, 480
pygame.init()
pygame.display.set_caption("launcher")
pygame.mouse.set_visible(False)
clock = pygame.time.Clock()
title_font = pygame.font.SysFont("dejavusans", 24, bold=True)
clock_font = pygame.font.SysFont("dejavusansmono", 26, bold=True)
tile_font = pygame.font.SysFont("dejavusans", 21, bold=True)
vol_font = pygame.font.SysFont("dejavusans", 19, bold=True)
sub_font = pygame.font.SysFont("dejavusans", 14)
settings_font = pygame.font.SysFont("dejavusans", 22, bold=True)
toast_font = pygame.font.SysFont("dejavusans", 16, bold=True)

# Palette matches pi-monitor/dunstrc's "Refined Card" style, so the
# launcher and the notification popups read as one system.
BG = (19, 19, 19)
TILE_BG = (28, 28, 36)
TILE_BORDER = (58, 58, 58)
TILE_BORDER_RUNNING = (86, 138, 98)
TILE_BORDER_PRESSED = (120, 140, 160)
ACCENT = (90, 107, 122)
TEXT_PRIMARY = (240, 240, 240)
TEXT_MUTED = (160, 160, 168)
TEXT_DIM = (120, 120, 128)
TOAST_OK = (86, 138, 98)
TOAST_FAIL = (163, 58, 50)
WELL_BG = (18, 18, 23)  # recessed plate behind each icon -- darker than the tile itself

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(SCRIPT_DIR, "assets", "icons")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
CONFIG_REMOTE_PATH = "/media/root-ro/home/ajxd2/launcher/config.json"
AUTOLAUNCH_LOG = "/tmp/launcher_autolaunch.log"

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

TILE_W, TILE_H = 220, 140
TILE_GAP = 30
TILE_Y = 190
ICON_SIZE = 36
WELL_SIZE = 60

HEADER_RAIL_Y = 88

PILL_W, PILL_H = 150, 40
PILL_X, PILL_Y = W - PILL_W - 24, 25
MINUS_ZONE = (PILL_X, PILL_Y, 44, PILL_H)
PLUS_ZONE = (PILL_X + PILL_W - 44, PILL_Y, 44, PILL_H)

# 64x64 -- large enough to be a reliable touch target even in a screen
# corner, and reused verbatim as the settings view's back button so the
# "go to/from settings" control always lives in the same spot.
SETTINGS_ZONE = (24, 13, 64, 64)


def load_icons():
    icons = {}
    for app in APPS:
        path = os.path.join(ICON_DIR, f"{app['icon']}.png")
        try:
            img = pygame.image.load(path).convert_alpha()
            icons[app["icon"]] = pygame.transform.smoothscale(img, (ICON_SIZE, ICON_SIZE))
        except Exception:
            icons[app["icon"]] = None
    try:
        gear = pygame.image.load(os.path.join(ICON_DIR, "settings.png")).convert_alpha()
        icons["settings"] = pygame.transform.smoothscale(gear, (32, 32))
    except Exception:
        icons["settings"] = None
    return icons


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


def hit_rect(pos, rect):
    x, y, w, h = rect
    return x <= pos[0] <= x + w and y <= pos[1] <= y + h


def tile_rects():
    n = len(APPS)
    total_w = n * TILE_W + (n - 1) * TILE_GAP
    start_x = (W - total_w) / 2
    return [(start_x + i * (TILE_W + TILE_GAP), TILE_Y, TILE_W, TILE_H) for i in range(n)]


screen = pygame.display.set_mode((W, H), pygame.NOFRAME)
pygame.display.flip()
ICONS = load_icons()
time.sleep(0.3)
launcher_winid = wm.get_active_window()
wm.write_launcher_winid(launcher_winid)

volume = get_volume()
launching = False  # true while blocked in open_app(); tiles ignore taps during this
view = "grid"  # "grid" or "settings"
pending_default = config["default_app"]
pending_auto_launch = config["auto_launch"]
save_toast_until = 0
save_toast_ok = True
pressed_index = None
pressed_at = 0


def open_app(app):
    global launcher_winid, launching
    launching = True
    if app["proc"] is None or app["proc"].poll() is not None:
        prev_active = wm.get_active_window()
        app["proc"] = subprocess.Popen(app["cmd"])
        new_win = wm.wait_for_new_active_window(prev_active, timeout=15.0)
        app["winid"] = new_win
    # Only hide the launcher once the app's window is confirmed -- if the
    # window never showed up (e.g. a broken auto-launch default on boot),
    # leaving the launcher hidden with no focused window would strand the
    # user on a blank screen with nothing to tap.
    if app["winid"]:
        wm.hide_window(launcher_winid)
        wm.show_window(app["winid"])
    wm.apply_audio_priority(app["binary"])
    launching = False


def draw_pill_button(rect, label, active=False):
    x, y, w, h = rect
    color = ACCENT if active else TILE_BORDER
    pygame.draw.rect(screen, color, rect, border_radius=h // 2)
    surf = vol_font.render(label, True, TEXT_PRIMARY)
    screen.blit(surf, (x + w / 2 - surf.get_width() / 2, y + h / 2 - surf.get_height() / 2))


def draw_settings_button(rect):
    """The gear button, top-left. Also drawn at the same rect in the
    settings view as the back button, so the control that opens settings
    and the one that leaves it always live in the same spot -- a fixed
    console position rather than something you have to hunt for."""
    x, y, w, h = rect
    pygame.draw.rect(screen, WELL_BG, rect, border_radius=12)
    pygame.draw.rect(screen, TILE_BORDER, rect, width=1, border_radius=12)
    gear = ICONS.get("settings")
    if gear:
        screen.blit(gear, (x + w / 2 - gear.get_width() / 2, y + h / 2 - gear.get_height() / 2))


def draw_header():
    draw_settings_button(SETTINGS_ZONE)

    title = title_font.render("CARPLAY PI", True, TEXT_PRIMARY)
    screen.blit(title, (SETTINGS_ZONE[0] + SETTINGS_ZONE[2] + 18, 26))

    # clock, dashboard-style: bold and bright rather than a muted label,
    # right-aligned before the volume pill
    now = time.strftime("%H:%M")
    clock_surf = clock_font.render(now, True, TEXT_PRIMARY)
    screen.blit(clock_surf, (PILL_X - clock_surf.get_width() - 22, PILL_Y + PILL_H / 2 - clock_surf.get_height() / 2))

    # accent rail -- the one bright line in an otherwise dark, restrained
    # header, standing in for the trim strip on a real console
    pygame.draw.rect(screen, ACCENT, (0, HEADER_RAIL_Y, W, 3))


def draw_grid():
    draw_header()

    for i, (rect, app) in enumerate(zip(tile_rects(), APPS)):
        x, y, w, h = rect
        running_now = app["proc"] is not None and app["proc"].poll() is None
        pressed_now = pressed_index == i and time.time() - pressed_at < 0.15
        # a physical press nudges the switch down 2px rather than just
        # recoloring it -- reads as tactile instead of a flat hover state
        y_off = 2 if pressed_now else 0
        y = y + y_off
        h = h - y_off

        border_color = TILE_BORDER_PRESSED if pressed_now else TILE_BORDER
        pygame.draw.rect(screen, TILE_BG, (x, y, w, h), border_radius=8)
        pygame.draw.rect(screen, border_color, (x, y, w, h), width=2, border_radius=8)

        # a lit strip along the top edge stands in for a switch's backlight,
        # rather than a small corner dot that's easy to miss at a glance
        if running_now:
            pygame.draw.rect(screen, TILE_BORDER_RUNNING, (x + 3, y + 3, w - 6, 4), border_radius=2)

        well_x = x + w / 2 - WELL_SIZE / 2
        well_y = y + 16
        pygame.draw.rect(screen, WELL_BG, (well_x, well_y, WELL_SIZE, WELL_SIZE), border_radius=10)
        icon = ICONS.get(app["icon"])
        if icon:
            screen.blit(icon, (x + w / 2 - icon.get_width() / 2, well_y + WELL_SIZE / 2 - icon.get_height() / 2))
        name_y = well_y + WELL_SIZE + 10

        name_surf = tile_font.render(app["name"], True, TEXT_PRIMARY)
        screen.blit(name_surf, (x + w / 2 - name_surf.get_width() / 2, name_y))
        note_surf = sub_font.render(app["note"], True, TEXT_DIM)
        screen.blit(note_surf, (x + w / 2 - note_surf.get_width() / 2, y + h - 24))

    # volume pill: [-] 25% [+]
    pygame.draw.rect(screen, TILE_BG, (PILL_X, PILL_Y, PILL_W, PILL_H), border_radius=PILL_H // 2)
    pygame.draw.rect(screen, TILE_BORDER, (PILL_X, PILL_Y, PILL_W, PILL_H), width=1, border_radius=PILL_H // 2)
    draw_pill_button(MINUS_ZONE, "-")
    draw_pill_button(PLUS_ZONE, "+")
    vol_label = vol_font.render(f"{volume}%", True, TEXT_MUTED)
    screen.blit(vol_label, (PILL_X + PILL_W / 2 - vol_label.get_width() / 2, PILL_Y + PILL_H / 2 - vol_label.get_height() / 2))


SAVE_ZONE = (W - 160, H - 62, 136, 46)
TOGGLE_ZONE = (W - 110, 140, 62, 34)
BACK_ZONE = SETTINGS_ZONE  # same rect as the gear -- one fixed spot for the settings control either way


def app_row_rects():
    return [(60, 190 + i * 56, W - 120, 44) for i in range(len(APPS))]


def draw_settings():
    global pending_default

    draw_settings_button(BACK_ZONE)
    title = settings_font.render("Settings", True, TEXT_PRIMARY)
    screen.blit(title, (BACK_ZONE[0] + BACK_ZONE[2] + 18, 26))
    pygame.draw.rect(screen, ACCENT, (0, HEADER_RAIL_Y, W, 3))

    label = sub_font.render("Auto-launch a default app on boot", True, TEXT_MUTED)
    screen.blit(label, (60, 118))

    # toggle
    tx, ty, tw, th = TOGGLE_ZONE
    toggle_color = TOAST_OK if pending_auto_launch else TILE_BORDER
    pygame.draw.rect(screen, toggle_color, TOGGLE_ZONE, border_radius=th // 2)
    knob_x = tx + tw - th if pending_auto_launch else tx
    pygame.draw.circle(screen, TEXT_PRIMARY, (int(knob_x + th / 2), int(ty + th / 2)), th // 2 - 3)

    default_label = sub_font.render("Default app", True, TEXT_MUTED)
    screen.blit(default_label, (60, 168))

    for rect, app in zip(app_row_rects(), APPS):
        x, y, w, h = rect
        selected = pending_default == app["name"]
        pygame.draw.rect(screen, TILE_BG, rect, border_radius=8)
        pygame.draw.rect(screen, TILE_BORDER, rect, width=1, border_radius=8)
        if selected:
            # a lit left edge instead of an inverted fill -- reads as
            # "this switch is engaged," consistent with the tiles' top rail
            pygame.draw.rect(screen, ACCENT, (x, y, 4, h), border_radius=2)
        icon = ICONS.get(app["icon"])
        if icon:
            small = pygame.transform.smoothscale(icon, (26, 26))
            screen.blit(small, (x + 18, y + h / 2 - 13))
        name_surf = tile_font.render(app["name"], True, TEXT_PRIMARY)
        screen.blit(name_surf, (x + 60, y + h / 2 - name_surf.get_height() / 2))

    # save button
    pygame.draw.rect(screen, ACCENT, SAVE_ZONE, border_radius=10)
    save_label = tile_font.render("Save", True, TEXT_PRIMARY)
    screen.blit(save_label, (SAVE_ZONE[0] + SAVE_ZONE[2] / 2 - save_label.get_width() / 2,
                              SAVE_ZONE[1] + SAVE_ZONE[3] / 2 - save_label.get_height() / 2))

    if time.time() < save_toast_until:
        toast_color = TOAST_OK if save_toast_ok else TOAST_FAIL
        toast_text = "Saved" if save_toast_ok else "Save failed"
        toast_surf = toast_font.render(toast_text, True, TEXT_PRIMARY)
        toast_w = toast_surf.get_width() + 32
        toast_rect = (W / 2 - toast_w / 2, H - 120, toast_w, 40)
        pygame.draw.rect(screen, toast_color, toast_rect, border_radius=20)
        screen.blit(toast_surf, (toast_rect[0] + 16, toast_rect[1] + 10))


def handle_settings_tap(pos):
    global view, pending_auto_launch, pending_default, save_toast_until, save_toast_ok

    if hit_rect(pos, BACK_ZONE):
        pending_default = config["default_app"]
        pending_auto_launch = config["auto_launch"]
        view = "grid"
        return
    if hit_rect(pos, TOGGLE_ZONE):
        pending_auto_launch = not pending_auto_launch
        return
    if hit_rect(pos, SAVE_ZONE):
        cfg = {"default_app": pending_default, "auto_launch": pending_auto_launch}
        ok = save_config(cfg)
        if ok:
            config["default_app"] = pending_default
            config["auto_launch"] = pending_auto_launch
        save_toast_ok = ok
        save_toast_until = time.time() + 1.5
        return
    for rect, app in zip(app_row_rects(), APPS):
        if hit_rect(pos, rect):
            pending_default = app["name"]
            return


def try_auto_launch():
    if not (config.get("auto_launch") and config.get("default_app")):
        return
    target = next((a for a in APPS if a["name"] == config["default_app"]), None)
    if not target:
        return
    screen.fill(BG)
    msg = tile_font.render(f"Starting {target['name']}...", True, TEXT_PRIMARY)
    screen.blit(msg, (W / 2 - msg.get_width() / 2, H / 2 - 15))
    pygame.display.flip()
    open_app(target)
    if not target["winid"]:
        try:
            with open(AUTOLAUNCH_LOG, "a") as f:
                f.write(f"{time.ctime()}: auto-launch failed for {target['name']}\n")
        except Exception:
            pass


try_auto_launch()

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
            pos = event.pos if event.type == pygame.MOUSEBUTTONDOWN else (event.x * W, event.y * H)
            if view == "settings":
                handle_settings_tap(pos)
                continue
            if hit_rect(pos, SETTINGS_ZONE):
                pending_default = config["default_app"]
                pending_auto_launch = config["auto_launch"]
                view = "settings"
            elif hit_rect(pos, MINUS_ZONE):
                volume = set_volume(volume - 5)
            elif hit_rect(pos, PLUS_ZONE):
                volume = set_volume(volume + 5)
            elif not launching:
                for i, (rect, app) in enumerate(zip(tile_rects(), APPS)):
                    if hit_rect(pos, rect):
                        pressed_index = i
                        pressed_at = time.time()
                        screen.fill(BG)
                        draw_grid()
                        pygame.display.flip()
                        time.sleep(0.1)
                        # open_app() blocks the loop below, so paint an
                        # immediate "Launching..." frame by hand first,
                        # otherwise the screen just looks frozen and
                        # invites exactly the impatient re-tap that
                        # caused the duplicate-launch bug.
                        screen.fill(BG)
                        msg = tile_font.render(f"Launching {app['name']}...", True, TEXT_PRIMARY)
                        screen.blit(msg, (W / 2 - msg.get_width() / 2, H / 2 - 15))
                        pygame.display.flip()
                        open_app(app)
                        pressed_index = None
                        break
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False

    if view == "grid":
        volume = get_volume()

    screen.fill(BG)
    if view == "settings":
        draw_settings()
    else:
        draw_grid()

    pygame.display.flip()
    clock.tick(30)

pygame.quit()
sys.exit()
