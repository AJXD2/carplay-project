#!/usr/bin/env python3
# Small always-on-top touch tab, bottom-center of the screen, that sits
# above whatever fullscreen app is running (CarPlay included) via a raw
# X11 override-redirect window. Tapping it hides whatever's currently
# active and brings the launcher back to front (apps keep running in
# the background, they're never killed).
#
# Styled to match the launcher's "Dash" theme (launcher/web/style.css):
# a graphite tab with rounded top corners, a warm-white home glyph and a
# short steel lamp bar along the bottom edge. Core X can't anti-alias, so
# the face is pre-rendered with PIL at 4x and scaled down, then put onto
# the window; the rounded corners come from the SHAPE extension.

from Xlib import X, display
from Xlib.ext import shape
import wm_helper as wm

W, H = 800, 480
TAB_W, TAB_H = 124, 28          # was 100x28; the tap target only grew
TAB_X = (W - TAB_W) // 2
TAB_Y = H - TAB_H
RADIUS = 12

# Dash palette, same values as the :root block in web/style.css
BG = (0x15, 0x17, 0x1a)         # --bg, what the anti-aliased corner pixels blend into
PANEL = (0x1e, 0x21, 0x25)      # --panel
PANEL_HI = (0x26, 0x2a, 0x2f)   # --panel-hi
RULE = (0x2c, 0x30, 0x35)       # --rule
TEXT = (0xec, 0xe7, 0xdf)       # --text, warm white
STEEL = (0x8a, 0x8f, 0x96)      # --steel

SS = 4                          # supersample factor for the PIL render


def render_face():
    """Return (RGB image, row spans) for the tab at real pixel size.
    Row spans are (x0, x1) per row of pixels that belong to the window
    shape; everything outside them is cut away with SHAPE."""
    from PIL import Image, ImageDraw

    w, h, r = TAB_W * SS, TAB_H * SS, RADIUS * SS

    def px(v):                  # real pixels to supersampled pixels
        return round(v * SS)

    def rounded_top(inset):     # rounded top only, bottom sits on the screen edge
        return (inset, inset, w - 1 - inset, h - 1 + r)

    shape_mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shape_mask).rounded_rectangle(rounded_top(0), r, fill=255)
    body_mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(body_mask).rounded_rectangle(rounded_top(SS), r - SS, fill=255)

    # body: panel-hi at the top fading into panel, like the launcher tiles
    body = Image.new("RGB", (w, h))
    bd = ImageDraw.Draw(body)
    for y in range(h):
        t = min(1.0, y / (h * 0.6))
        bd.line((0, y, w, y), fill=tuple(round(a + (b - a) * t)
                                         for a, b in zip(PANEL_HI, PANEL)))

    # 1px rule around the edge, body inside it
    img = Image.new("RGB", (w, h), RULE)
    img.paste(body, (0, 0), body_mask)
    dr = ImageDraw.Draw(img)

    # home glyph, warm white, 2px stroke, about 18x16
    cx = w / 2
    stroke = px(2)
    dr.line((cx - px(9), px(12.5), cx, px(4), cx + px(9), px(12.5)),
            fill=TEXT, width=stroke, joint="curve")
    dr.line((cx - px(6), px(10), cx - px(6), px(20),
             cx + px(6), px(20), cx + px(6), px(10)),
            fill=TEXT, width=stroke, joint="curve")
    dr.rounded_rectangle((cx - px(2), px(14.5), cx + px(2), px(20)),
                         px(1), fill=TEXT)

    # lamp bar along the bottom edge (3px, rounded top), steel since the
    # tab is a control, not something "lit"; amber stays reserved
    dr.rounded_rectangle((cx - px(12), h - px(3), cx + px(12), h + px(3)),
                         px(1.5), fill=STEEL)

    out = Image.new("RGB", (w, h), BG)
    out.paste(img, (0, 0), shape_mask)
    out = out.resize((TAB_W, TAB_H), Image.BOX)
    small = shape_mask.resize((TAB_W, TAB_H), Image.BOX)

    spans = []
    for y in range(TAB_H):
        row = [x for x in range(TAB_W) if small.getpixel((x, y)) >= 128]
        spans.append((row[0], row[-1] + 1) if row else None)
    return out, spans


def go_home():
    launcher_winid = wm.read_launcher_winid()
    if not launcher_winid:
        return
    current = wm.get_active_window()
    if current and current != launcher_winid:
        wm.hide_window(current)
    wm.show_window(launcher_winid)


def main():
    d = display.Display()
    screen = d.screen()
    root = screen.root
    colormap = screen.default_colormap

    def color(rgb):
        r, g, b = rgb
        return colormap.alloc_color(r * 257, g * 257, b * 257).pixel

    win = root.create_window(
        TAB_X, TAB_Y, TAB_W, TAB_H, 0,
        screen.root_depth,
        X.InputOutput,
        X.CopyFromParent,
        background_pixel=color(PANEL),
        event_mask=X.ExposureMask | X.ButtonPressMask,
        override_redirect=True,
    )

    try:
        face, spans = render_face()
    except ImportError:
        # no PIL: plain square panel, still a working tab
        face, spans = None, None

    if spans and d.has_extension("SHAPE"):
        rects = [(s[0], y, s[1] - s[0], 1) for y, s in enumerate(spans) if s]
        win.shape_rectangles(shape.SO.Set, shape.SK.Bounding,
                             X.YXBanded, 0, 0, rects)
    win.map()

    gc = win.create_gc(foreground=color(PANEL))
    lamp_gc = win.create_gc(foreground=color(STEEL))

    def draw():
        if face is not None:
            win.put_pil_image(gc, 0, 0, face)
        else:
            win.fill_rectangle(gc, 0, 0, TAB_W, TAB_H)
            win.fill_rectangle(lamp_gc, (TAB_W - 28) // 2, TAB_H - 3, 28, 3)
        d.flush()

    while True:
        ev = d.next_event()
        if ev.type == X.Expose:
            draw()
        elif ev.type == X.ButtonPress:
            go_home()


if __name__ == "__main__":
    main()
