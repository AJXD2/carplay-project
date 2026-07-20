#!/usr/bin/env python3
import pygame, subprocess, sys, time

W, H = 800, 480
pygame.init()
pygame.display.set_caption("logs")
screen = pygame.display.set_mode((W, H), pygame.NOFRAME)
pygame.mouse.set_visible(False)
clock = pygame.time.Clock()
title_font = pygame.font.SysFont("dejavusans", 27, bold=True)
tab_font = pygame.font.SysFont("dejavusans", 16, bold=True)
line_font = pygame.font.SysFont("dejavusansmono", 14)
hint_font = pygame.font.SysFont("dejavusans", 14)

# matches launcher.py / info.py's "Refined Card" palette
BG = (19, 19, 19)
TILE_BG = (28, 28, 36)
TILE_BORDER = (58, 58, 58)
TEXT_PRIMARY = (240, 240, 240)
TEXT_MUTED = (160, 160, 168)
TAB_ACTIVE = (58, 107, 122)


def sh(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
    except Exception as e:
        return f"(failed to read log: {e})"


SOURCES = [
    {"name": "Autolaunch", "cmd": "tail -n 300 /tmp/launcher_autolaunch.log"},
    {"name": "System", "cmd": "journalctl -n 300 --no-pager"},
    {"name": "Kernel", "cmd": "dmesg | tail -n 300"},
]

active_source = 0
scroll = 0
lines = []
last_refresh = 0

TAB_Y = 74
TAB_H = 36
VIEW_Y0 = 122
VIEW_Y1 = H - 60
LINE_H = 18
VISIBLE_LINES = (VIEW_Y1 - VIEW_Y0) // LINE_H

UP_ZONE = (W - 60, VIEW_Y0, 44, (VIEW_Y1 - VIEW_Y0) // 2 - 4)
DOWN_ZONE = (W - 60, VIEW_Y0 + (VIEW_Y1 - VIEW_Y0) // 2 + 4, 44, (VIEW_Y1 - VIEW_Y0) // 2 - 4)


def tab_rects():
    rects = []
    x = 28
    for s in SOURCES:
        w = tab_font.size(s["name"])[0] + 36
        rects.append((x, TAB_Y, w, TAB_H))
        x += w + 10
    return rects


def hit(rect, pos):
    x, y, w, h = rect
    return x <= pos[0] <= x + w and y <= pos[1] <= y + h


def refresh():
    global lines
    raw = sh(SOURCES[active_source]["cmd"])
    lines = raw.splitlines() or ["(empty)"]


def clamp_scroll():
    global scroll
    max_scroll = max(0, len(lines) - VISIBLE_LINES)
    scroll = max(0, min(scroll, max_scroll))


def handle_tap(pos):
    global active_source, scroll
    for i, rect in enumerate(tab_rects()):
        if hit(rect, pos):
            if i != active_source:
                active_source = i
                scroll = 0
                refresh()
            return
    if hit(UP_ZONE, pos):
        scroll -= VISIBLE_LINES // 2 or 1
        clamp_scroll()
        return
    if hit(DOWN_ZONE, pos):
        scroll += VISIBLE_LINES // 2 or 1
        clamp_scroll()
        return


refresh()

running = True
drag_start_y = None
drag_start_scroll = 0
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False
        elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
            if event.type == pygame.FINGERDOWN:
                pos = (event.x * W, event.y * H)
            else:
                pos = event.pos
            drag_start_y = pos[1]
            drag_start_scroll = scroll
            handle_tap(pos)
        elif event.type in (pygame.MOUSEMOTION, pygame.FINGERMOTION) and drag_start_y is not None:
            if event.type == pygame.FINGERMOTION:
                y = event.y * H
            else:
                if not event.buttons[0]:
                    continue
                y = event.pos[1]
            delta_lines = int((drag_start_y - y) / LINE_H)
            scroll = drag_start_scroll + delta_lines
            clamp_scroll()
        elif event.type in (pygame.MOUSEBUTTONUP, pygame.FINGERUP):
            drag_start_y = None

    now = time.time()
    if now - last_refresh >= 3.0:
        refresh()
        clamp_scroll()
        last_refresh = now

    screen.fill(BG)
    title = title_font.render("Logs", True, TEXT_PRIMARY)
    screen.blit(title, (28, 24))

    for i, (rect, s) in enumerate(zip(tab_rects(), SOURCES)):
        x, y, w, h = rect
        bg = TAB_ACTIVE if i == active_source else TILE_BG
        pygame.draw.rect(screen, bg, rect, border_radius=8)
        pygame.draw.rect(screen, TILE_BORDER, rect, 1, border_radius=8)
        surf = tab_font.render(s["name"], True, TEXT_PRIMARY)
        screen.blit(surf, (x + w / 2 - surf.get_width() / 2, y + h / 2 - surf.get_height() / 2))

    pygame.draw.rect(screen, TILE_BG, (28, VIEW_Y0, W - 56, VIEW_Y1 - VIEW_Y0), border_radius=8)
    pygame.draw.rect(screen, TILE_BORDER, (28, VIEW_Y0, W - 56, VIEW_Y1 - VIEW_Y0), 1, border_radius=8)

    visible = lines[scroll:scroll + VISIBLE_LINES]
    y = VIEW_Y0 + 6
    for line in visible:
        surf = line_font.render(line[:88], True, TEXT_PRIMARY)
        screen.blit(surf, (38, y))
        y += LINE_H

    for rect, sym in ((UP_ZONE, "^"), (DOWN_ZONE, "v")):
        pygame.draw.rect(screen, TILE_BG, rect, border_radius=8)
        pygame.draw.rect(screen, TILE_BORDER, rect, 1, border_radius=8)
        surf = tab_font.render(sym, True, TEXT_PRIMARY)
        x, y2, w, h = rect
        screen.blit(surf, (x + w / 2 - surf.get_width() / 2, y2 + h / 2 - surf.get_height() / 2))

    pos_text = f"{min(scroll + 1, len(lines))}-{min(scroll + VISIBLE_LINES, len(lines))} / {len(lines)}"
    pos_surf = hint_font.render(pos_text, True, TEXT_MUTED)
    screen.blit(pos_surf, (28, VIEW_Y1 + 6))

    hint = hint_font.render("drag to scroll, esc to quit", True, TEXT_MUTED)
    screen.blit(hint, (W - 28 - hint.get_width(), VIEW_Y1 + 6))

    pygame.display.flip()
    clock.tick(30)

pygame.quit()
sys.exit()
