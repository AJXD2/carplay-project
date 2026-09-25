#!/usr/bin/env python3
"""On-screen splash helpers for X, in the launcher's Dash style.

  xsplash.py boot
      Plays the installed boot splash's loop fullscreen from the moment X
      starts until the launcher's Chromium window is up. Plymouth has to
      stop before Xorg can take the display, and Chromium takes ~10 s more
      to appear, so without this the screen sits on a still frame.
      Started from ~/.xinitrc.

  xsplash.py progress STATEFILE [TITLE [DONE_TITLE]]
      A small card at the top of the screen with a message and an amber
      progress bar, for installs pushed to the Pi (see progress.sh). It
      leaves the rest of the screen alone, so CarPlay stays usable. The
      installer drives it by rewriting STATEFILE with one line:
          <pct> <target> <seconds> <message>
      The bar sits at pct and eases toward target over about `seconds`
      (for steps that take a while but report nothing). pct 100 shows the
      message as done and closes after a few seconds; pct -1 shows it as a
      failure. Deleting STATEFILE closes the card.

Needs python3-xlib and PIL, both on the Pi.
"""
import json
import math
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from Xlib import X, display
from Xlib.ext import shape

THEME = Path("/usr/share/plymouth/themes/carplay")
READY_FILE = Path("/tmp/carplay_pi_launcher_winid")   # written by server.py
FONTS = Path.home() / "launcher/web/fonts"

# Dash palette, same values as the :root block in web/style.css
BG = (0x15, 0x17, 0x1a)
PANEL = (0x1e, 0x21, 0x25)
PANEL_HI = (0x26, 0x2a, 0x2f)
RULE = (0x2c, 0x30, 0x35)
TEXT = (0xec, 0xe7, 0xdf)
STEEL = (0x8a, 0x8f, 0x96)
AMBER = (0xf0, 0xa5, 0x3a)
RED = (0xd6, 0x49, 0x3e)


def font(name, size):
    for path in (FONTS / name, Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def overlay_window(d, x, y, w, h, bg):
    screen = d.screen()
    pixel = screen.default_colormap.alloc_color(*(c * 257 for c in bg)).pixel
    win = screen.root.create_window(
        x, y, w, h, 0, screen.root_depth, X.InputOutput, X.CopyFromParent,
        background_pixel=pixel, override_redirect=True,
        event_mask=X.ExposureMask)
    return win, win.create_gc(foreground=pixel)


# -- boot ---------------------------------------------------------------------

def boot(max_seconds=60, settle=1.0):
    try:
        meta = json.loads((THEME / "frames.json").read_text())
    except (OSError, ValueError):
        return  # theme predates frames.json: the feh background still shows
    d = display.Display()
    sw, sh = d.screen().width_in_pixels, d.screen().height_in_pixels
    win, gc = overlay_window(d, 0, 0, sw, sh, tuple(meta["bg"]))
    ox, oy = (sw - 800) // 2 + meta["x"], (sh - 480) // 2 + meta["y"]

    # Upload every loop frame once; each tick is then a server-side copy.
    frames = []
    for i in range(meta["n_loop"]):
        img = Image.open(THEME / f"loop_{i:03}.png").convert("RGB")
        pm = win.create_pixmap(img.width, img.height, d.screen().root_depth)
        pm.put_pil_image(gc, 0, 0, img)
        frames.append((pm, img.width, img.height))
    win.map()

    period = 1.0 / meta["fps"]
    start = time.monotonic()
    ready_at = None
    i = 0
    while True:
        now = time.monotonic()
        if ready_at is None and READY_FILE.exists():
            ready_at = now  # give Chromium a moment to paint the page
        if (ready_at and now - ready_at >= settle) or now - start >= max_seconds:
            break
        pm, w, h = frames[i % len(frames)]
        win.copy_area(gc, pm, 0, 0, w, h, ox, oy)
        if i % 8 == 0:
            win.configure(stack_mode=X.Above)  # stay over Chromium until it's ready
        d.flush()
        i += 1
        time.sleep(max(0.0, start + i * period - time.monotonic()))
    win.destroy()  # picom fades it out, revealing the launcher
    d.flush()
    why = "launcher ready" if ready_at else "timed out"
    print(f"xsplash boot: {why} after {time.monotonic() - start:.1f} s, {i} frames", flush=True)


# -- progress -----------------------------------------------------------------

CARD_W, CARD_H = 440, 84
SS = 2  # supersampling for smooth corners and text


def render_card(message, frac, state, title="Updating", done_title="Update complete"):
    w, h = CARD_W * SS, CARD_H * SS
    img = Image.new("RGB", (w, h), BG)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), 14 * SS, fill=255)
    body = Image.new("RGB", (w, h), RULE)
    bd = ImageDraw.Draw(body)
    for y in range(SS, h - SS):
        t = min(1.0, y / (h * 0.4))
        bd.line((SS, y, w - SS - 1, y),
                fill=tuple(round(a + (b - a) * t) for a, b in zip(PANEL_HI, PANEL)))
    img.paste(body, (0, 0), mask)
    dr = ImageDraw.Draw(img)

    title = {"done": done_title, "failed": "Update failed"}.get(state, title)
    dr.text((20 * SS, 14 * SS), title, font=font("barlow-600.woff2", 19 * SS),
            fill=RED if state == "failed" else TEXT)
    dr.text((20 * SS, 40 * SS), message, font=font("barlow-400.woff2", 15 * SS), fill=STEEL)

    # track and fill, like the launcher's volume bar but thinner
    x0, x1, y = 20 * SS, w - 20 * SS, 68 * SS
    dr.rounded_rectangle((x0, y, x1, y + 4 * SS), 2 * SS, fill=RULE)
    fill = RED if state == "failed" else AMBER
    if frac > 0:
        dr.rounded_rectangle((x0, y, x0 + max(4 * SS, (x1 - x0) * frac), y + 4 * SS), 2 * SS, fill=fill)

    small_mask = mask.resize((CARD_W, CARD_H), Image.BOX)
    spans = []
    for yy in range(CARD_H):
        row = [x for x in range(CARD_W) if small_mask.getpixel((x, yy)) >= 128]
        spans.append((row[0], row[-1] + 1) if row else None)
    return img.resize((CARD_W, CARD_H), Image.BOX), spans


def read_state(path):
    try:
        pct, target, secs, message = path.read_text().strip().split(" ", 3)
        return float(pct), float(target), float(secs), message
    except (OSError, ValueError):
        return None


def progress(statefile, title="Updating", done_title="Update complete", idle_timeout=900):
    path = Path(statefile)
    d = display.Display()
    sw = d.screen().width_in_pixels
    win, gc = overlay_window(d, (sw - CARD_W) // 2, 14, CARD_W, CARD_H, BG)
    shaped = False

    last = None       # last state line seen
    since = time.monotonic()
    done_at = None
    shown = None
    while True:
        now = time.monotonic()
        st = read_state(path)
        if st is None:
            if not path.exists():
                break
            st = last
        if st != last:
            last, since = st, now
        if st is None:
            time.sleep(0.2)
            continue
        pct, target, secs, message = st
        if pct >= 100:
            state, frac = "done", 1.0
            done_at = done_at or now
        elif pct < 0:
            state, frac = "failed", 1.0
            done_at = done_at or now
        else:
            # ease toward target: covers ~63% of the gap per `secs`, never arrives
            k = 1.0 - math.exp(-(now - since) / max(secs, 0.1)) if target > pct else 0.0
            state, frac = "running", (pct + (target - pct) * k) / 100.0
        key = (message, round(frac * CARD_W), state)
        if key != shown:
            img, spans = render_card(message, frac, state, title, done_title)
            if not shaped and d.has_extension("SHAPE"):
                rects = [(s[0], y, s[1] - s[0], 1) for y, s in enumerate(spans) if s]
                win.shape_rectangles(shape.SO.Set, shape.SK.Bounding, X.YXBanded, 0, 0, rects)
                shaped = True
                win.map()
            elif not shaped:
                shaped = True
                win.map()
            win.put_pil_image(gc, 0, 0, img)
            win.configure(stack_mode=X.Above)
            d.flush()
            shown = key
        elif int(now * 10) % 5 == 0:
            # an install may restart Chromium, whose window would land on top
            win.configure(stack_mode=X.Above)
            d.flush()
        if done_at and now - done_at > (8 if state == "failed" else 5):
            break
        if now - since > idle_timeout:
            break
        time.sleep(0.1)
    win.destroy()
    d.flush()
    try:
        path.unlink()
    except OSError:
        pass


if __name__ == "__main__":
    if sys.argv[1:2] == ["boot"]:
        boot()
    elif sys.argv[1:2] == ["progress"] and 3 <= len(sys.argv) <= 5:
        progress(*sys.argv[2:])
    else:
        sys.exit(__doc__)
