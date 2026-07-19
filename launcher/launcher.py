#!/usr/bin/env python3
import pygame, subprocess, sys, os, time
import wm_helper as wm

W, H = 800, 480
pygame.init()
pygame.display.set_caption("launcher")
pygame.mouse.set_visible(False)
clock = pygame.time.Clock()
title_font = pygame.font.SysFont("dejavusans", 27, bold=True)
tile_font = pygame.font.SysFont("dejavusans", 21, bold=True)
vol_font = pygame.font.SysFont("dejavusans", 19, bold=True)
sub_font = pygame.font.SysFont("dejavusans", 14)

# Palette matches pi-monitor/dunstrc's "Refined Card" style, so the
# launcher and the notification popups read as one system.
BG = (19, 19, 19)
TILE_BG = (28, 28, 36)
TILE_BORDER = (58, 58, 58)
TILE_BORDER_RUNNING = (86, 138, 98)
ACCENT = (90, 107, 122)
TEXT_PRIMARY = (240, 240, 240)
TEXT_MUTED = (160, 160, 168)
TEXT_DIM = (120, 120, 128)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

APPS = [
    {
        "name": "CarPlay",
        "note": "stays running in background",
        "cmd": ["/home/ajxd2/react-carplay.AppImage", "--no-sandbox"],
        "binary": "react-carplay",
        "proc": None,
        "winid": None,
    },
    {
        "name": "Flappy Bird",
        "note": "tap the tab to come back",
        "cmd": ["python3", f"{SCRIPT_DIR}/flappy.py"],
        "binary": "python3",
        "proc": None,
        "winid": None,
    },
    {
        "name": "Info",
        "note": "live system status",
        "cmd": ["python3", f"{SCRIPT_DIR}/info.py"],
        "binary": "python3",
        "proc": None,
        "winid": None,
    },
]

TILE_W, TILE_H = 220, 140
TILE_GAP = 30
TILE_Y = 168

PILL_W, PILL_H = 150, 40
PILL_X, PILL_Y = W - PILL_W - 24, 20
MINUS_ZONE = (PILL_X, PILL_Y, 44, PILL_H)
PLUS_ZONE = (PILL_X + PILL_W - 44, PILL_Y, 44, PILL_H)


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
time.sleep(0.3)
launcher_winid = wm.get_active_window()
wm.write_launcher_winid(launcher_winid)

volume = get_volume()
launching = False  # true while blocked in open_app(); tiles ignore taps during this


def open_app(app):
    global launcher_winid, launching
    launching = True
    if app["proc"] is None or app["proc"].poll() is not None:
        prev_active = wm.get_active_window()
        app["proc"] = subprocess.Popen(app["cmd"])
        new_win = wm.wait_for_new_active_window(prev_active, timeout=15.0)
        app["winid"] = new_win
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


running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
            pos = event.pos if event.type == pygame.MOUSEBUTTONDOWN else (event.x * W, event.y * H)
            if hit_rect(pos, MINUS_ZONE):
                volume = set_volume(volume - 5)
            elif hit_rect(pos, PLUS_ZONE):
                volume = set_volume(volume + 5)
            elif not launching:
                for rect, app in zip(tile_rects(), APPS):
                    if hit_rect(pos, rect):
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
                        break
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False

    volume = get_volume()

    screen.fill(BG)
    title = title_font.render("carplay pi", True, TEXT_PRIMARY)
    screen.blit(title, (28, 24))
    pygame.draw.line(screen, TILE_BORDER, (28, 66), (W - 28, 66), 1)

    for rect, app in zip(tile_rects(), APPS):
        x, y, w, h = rect
        running_now = app["proc"] is not None and app["proc"].poll() is None
        border_color = TILE_BORDER_RUNNING if running_now else TILE_BORDER
        pygame.draw.rect(screen, TILE_BG, rect, border_radius=10)
        pygame.draw.rect(screen, border_color, rect, width=2, border_radius=10)
        if running_now:
            pygame.draw.circle(screen, TILE_BORDER_RUNNING, (x + w - 16, y + 16), 4)
        name_surf = tile_font.render(app["name"], True, TEXT_PRIMARY)
        screen.blit(name_surf, (x + w / 2 - name_surf.get_width() / 2, y + h / 2 - 20))
        note_surf = sub_font.render(app["note"], True, TEXT_DIM)
        screen.blit(note_surf, (x + w / 2 - note_surf.get_width() / 2, y + h / 2 + 14))

    # volume pill: [-] 25% [+]
    pygame.draw.rect(screen, TILE_BG, (PILL_X, PILL_Y, PILL_W, PILL_H), border_radius=PILL_H // 2)
    pygame.draw.rect(screen, TILE_BORDER, (PILL_X, PILL_Y, PILL_W, PILL_H), width=1, border_radius=PILL_H // 2)
    draw_pill_button(MINUS_ZONE, "-")
    draw_pill_button(PLUS_ZONE, "+")
    vol_label = vol_font.render(f"{volume}%", True, TEXT_MUTED)
    screen.blit(vol_label, (PILL_X + PILL_W / 2 - vol_label.get_width() / 2, PILL_Y + PILL_H / 2 - vol_label.get_height() / 2))

    pygame.display.flip()
    clock.tick(30)

pygame.quit()
sys.exit()
