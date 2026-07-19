#!/usr/bin/env python3
# Small always-on-top touch tab, bottom-center of the screen, that sits
# above whatever fullscreen app is running (CarPlay included) via a raw
# X11 override-redirect window. Tapping it hides whatever's currently
# active and brings the launcher back to front (apps keep running in
# the background, they're never killed).

from Xlib import X, display
import wm_helper as wm

W, H = 800, 480
TAB_W, TAB_H = 100, 28
TAB_X = (W - TAB_W) // 2
TAB_Y = H - TAB_H

d = display.Display()
screen = d.screen()
root = screen.root
colormap = screen.default_colormap


def color(r, g, b):
    return colormap.alloc_color(r * 257, g * 257, b * 257).pixel


# matches launcher.py / pi-monitor/dunstrc's "Refined Card" palette
BG = color(28, 28, 36)
FG = color(240, 240, 240)

win = root.create_window(
    TAB_X, TAB_Y, TAB_W, TAB_H, 0,
    screen.root_depth,
    X.InputOutput,
    X.CopyFromParent,
    background_pixel=BG,
    event_mask=X.ExposureMask | X.ButtonPressMask,
    override_redirect=True,
)
win.map()

BORDER = color(58, 58, 58)
bg_gc = win.create_gc(foreground=BG)
fg_gc = win.create_gc(foreground=FG)
border_gc = win.create_gc(foreground=BORDER)


def draw():
    win.fill_rectangle(bg_gc, 0, 0, TAB_W, TAB_H)
    win.rectangle(border_gc, 0, 0, TAB_W - 1, TAB_H - 1)
    bar_h = 3
    widths = [26, 20, 14, 8, 2]
    cx = TAB_W // 2
    top = 6
    for i, w in enumerate(widths):
        y = top + i * (bar_h + 1)
        win.fill_rectangle(fg_gc, cx - w // 2, y, w, bar_h)
    d.flush()


def go_home():
    launcher_winid = wm.read_launcher_winid()
    if not launcher_winid:
        return
    current = wm.get_active_window()
    if current and current != launcher_winid:
        wm.hide_window(current)
    wm.show_window(launcher_winid)


while True:
    ev = d.next_event()
    if ev.type == X.Expose:
        draw()
    elif ev.type == X.ButtonPress:
        go_home()
