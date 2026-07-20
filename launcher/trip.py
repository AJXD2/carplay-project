#!/usr/bin/env python3
import pygame, sys, json, os

W, H = 800, 480
pygame.init()
pygame.display.set_caption("trip")
screen = pygame.display.set_mode((W, H), pygame.NOFRAME)
pygame.mouse.set_visible(False)
clock = pygame.time.Clock()
title_font = pygame.font.SysFont("dejavusans", 27, bold=True)
tab_font = pygame.font.SysFont("dejavusans", 18, bold=True)
row_font = pygame.font.SysFont("dejavusans", 18)
value_font = pygame.font.SysFont("dejavusansmono", 22, bold=True)
hint_font = pygame.font.SysFont("dejavusans", 14)

# matches launcher.py / info.py's "Refined Card" palette
BG = (19, 19, 19)
TILE_BG = (28, 28, 36)
TILE_BORDER = (58, 58, 58)
TEXT_PRIMARY = (240, 240, 240)
TEXT_MUTED = (160, 160, 168)
ACCENT = (90, 107, 122)
TAB_ACTIVE = (58, 107, 122)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(SCRIPT_DIR, "trip_state.json")

DEFAULT_STATE = {
    "speed_mph": 60.0,
    "distance_mi": 10.0,
    "gallons_price": 3.50,
    "gallons_used": 0.0,
    "mpg": 28.0,
}


def load_state():
    try:
        with open(STATE_PATH) as f:
            data = json.load(f)
        merged = dict(DEFAULT_STATE)
        merged.update(data)
        return merged
    except Exception:
        return dict(DEFAULT_STATE)


def save_state(state):
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


state = load_state()

TABS = ["Convert", "Trip Cost"]
active_tab = 0

TAB_Y = 74
TAB_H = 40


def tab_rects():
    rects = []
    x = 28
    for name in TABS:
        w = tab_font.size(name)[0] + 40
        rects.append((x, TAB_Y, w, TAB_H))
        x += w + 12
    return rects


# --- Convert tab: mph<->kmh, mi<->km, gal<->L, F<->C, all driven off one
# base value per row with +/- steppers so it works with touch alone. ---
CONVERT_ROWS = [
    {"label": "Speed", "key": "speed_mph", "unit_a": "mph", "unit_b": "km/h", "to_b": lambda v: v * 1.60934, "step": 5},
    {"label": "Distance", "key": "distance_mi", "unit_a": "mi", "unit_b": "km", "to_b": lambda v: v * 1.60934, "step": 1},
    {"label": "Fuel Price", "key": "gallons_price", "unit_a": "$/gal", "unit_b": "$/L", "to_b": lambda v: v / 3.78541, "step": 0.1},
    {"label": "Temp", "key": "temp_f", "unit_a": "°F", "unit_b": "°C", "to_b": lambda v: (v - 32) * 5 / 9, "step": 5},
]
if "temp_f" not in state:
    state["temp_f"] = 70.0

ROW_H = 64
ROW_Y0 = 140
STEP_BTN_W = 44


def convert_row_rects():
    rects = []
    y = ROW_Y0
    for row in CONVERT_ROWS:
        minus = (60, y, STEP_BTN_W, ROW_H - 12)
        plus = (W - 60 - STEP_BTN_W, y, STEP_BTN_W, ROW_H - 12)
        rects.append((row, minus, plus, y))
        y += ROW_H
    return rects


# --- Trip Cost tab: distance / mpg / price -> estimated fuel cost ---
TRIP_FIELDS = [
    {"label": "Distance (mi)", "key": "distance_mi", "step": 5},
    {"label": "Fuel Economy (mpg)", "key": "mpg", "step": 1},
    {"label": "Price ($/gal)", "key": "gallons_price", "step": 0.1},
]


def trip_field_rects():
    rects = []
    y = ROW_Y0
    for field in TRIP_FIELDS:
        minus = (60, y, STEP_BTN_W, ROW_H - 12)
        plus = (W - 60 - STEP_BTN_W, y, STEP_BTN_W, ROW_H - 12)
        rects.append((field, minus, plus, y))
        y += ROW_H
    return rects


def hit(rect, pos):
    x, y, w, h = rect
    return x <= pos[0] <= x + w and y <= pos[1] <= y + h


def fmt(v):
    if abs(v - round(v)) < 0.01:
        return f"{v:.0f}"
    return f"{v:.2f}"


def handle_tap(pos):
    global active_tab
    for i, rect in enumerate(tab_rects()):
        if hit(rect, pos):
            active_tab = i
            return

    if active_tab == 0:
        for row, minus, plus, y in convert_row_rects():
            key = row["key"]
            step = row["step"]
            if hit(minus, pos):
                state[key] = round(state[key] - step, 2)
                save_state(state)
                return
            if hit(plus, pos):
                state[key] = round(state[key] + step, 2)
                save_state(state)
                return
    else:
        for field, minus, plus, y in trip_field_rects():
            key = field["key"]
            step = field["step"]
            if hit(minus, pos):
                state[key] = max(0, round(state[key] - step, 2))
                save_state(state)
                return
            if hit(plus, pos):
                state[key] = round(state[key] + step, 2)
                save_state(state)
                return


def draw_tabs():
    for i, (rect, name) in enumerate(zip(tab_rects(), TABS)):
        x, y, w, h = rect
        bg = TAB_ACTIVE if i == active_tab else TILE_BG
        pygame.draw.rect(screen, bg, rect, border_radius=8)
        pygame.draw.rect(screen, TILE_BORDER, rect, 1, border_radius=8)
        surf = tab_font.render(name, True, TEXT_PRIMARY)
        screen.blit(surf, (x + w / 2 - surf.get_width() / 2, y + h / 2 - surf.get_height() / 2))


def draw_stepper(rect_minus, rect_plus, label_text, value_text):
    for rect, sym in ((rect_minus, "-"), (rect_plus, "+")):
        pygame.draw.rect(screen, TILE_BG, rect, border_radius=8)
        pygame.draw.rect(screen, TILE_BORDER, rect, 1, border_radius=8)
        surf = value_font.render(sym, True, TEXT_PRIMARY)
        x, y, w, h = rect
        screen.blit(surf, (x + w / 2 - surf.get_width() / 2, y + h / 2 - surf.get_height() / 2))


def draw_convert():
    for row, minus, plus, y in convert_row_rects():
        draw_stepper(minus, plus, row["label"], None)
        a_val = state[row["key"]]
        b_val = row["to_b"](a_val)
        label_surf = row_font.render(row["label"], True, TEXT_MUTED)
        screen.blit(label_surf, (60, y - 20))
        val_surf = value_font.render(f"{fmt(a_val)} {row['unit_a']}", True, TEXT_PRIMARY)
        screen.blit(val_surf, (W / 2 - val_surf.get_width() / 2 - 90, y + (ROW_H - 12) / 2 - val_surf.get_height() / 2))
        eq_surf = row_font.render("=", True, TEXT_MUTED)
        screen.blit(eq_surf, (W / 2 - 6, y + (ROW_H - 12) / 2 - eq_surf.get_height() / 2))
        b_surf = value_font.render(f"{fmt(b_val)} {row['unit_b']}", True, TEXT_PRIMARY)
        screen.blit(b_surf, (W / 2 + 20, y + (ROW_H - 12) / 2 - b_surf.get_height() / 2))


def draw_trip():
    for field, minus, plus, y in trip_field_rects():
        draw_stepper(minus, plus, field["label"], None)
        label_surf = row_font.render(field["label"], True, TEXT_MUTED)
        screen.blit(label_surf, (60, y - 20))
        val_surf = value_font.render(fmt(state[field["key"]]), True, TEXT_PRIMARY)
        screen.blit(val_surf, (W / 2 - val_surf.get_width() / 2, y + (ROW_H - 12) / 2 - val_surf.get_height() / 2))

    distance = state["distance_mi"]
    mpg = max(state["mpg"], 0.1)
    price = state["gallons_price"]
    gallons = distance / mpg
    cost = gallons * price

    y = ROW_Y0 + ROW_H * len(TRIP_FIELDS) + 20
    pygame.draw.line(screen, TILE_BORDER, (60, y), (W - 60, y), 1)
    y += 20
    result = f"~{gallons:.2f} gal  ->  ${cost:.2f} estimated fuel cost"
    result_surf = tab_font.render(result, True, TEXT_PRIMARY)
    screen.blit(result_surf, (W / 2 - result_surf.get_width() / 2, y))


running = True
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
            handle_tap(pos)

    screen.fill(BG)
    title = title_font.render("Trip Calc", True, TEXT_PRIMARY)
    screen.blit(title, (28, 24))
    draw_tabs()

    if active_tab == 0:
        draw_convert()
    else:
        draw_trip()

    hint = hint_font.render("tap +/- to adjust, esc to quit", True, TEXT_MUTED)
    screen.blit(hint, (10, H - 26))

    pygame.display.flip()
    clock.tick(30)

pygame.quit()
sys.exit()
