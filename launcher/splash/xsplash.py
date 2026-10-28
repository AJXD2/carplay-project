#!/usr/bin/env python3
"""On-screen splash helpers for X, in the launcher's Dash style.

  xsplash.py boot
      Plays the installed boot splash's loop fullscreen from the moment X
      starts until the launcher's Chromium window is up. Plymouth has to
      stop before Xorg can take the display, and Chromium takes ~10 s more
      to appear, so without this the screen sits on a still frame.
      Started from ~/.xinitrc.

  xsplash.py progress STATEFILE [TITLE [DONE_TITLE]]
      The update view for installs pushed to the Pi (see progress.sh). It
      opens full screen, above CarPlay and the launcher: title, a large
      percentage and bar, the current message and "Keep the power on".
      Tapping anywhere (or its Hide button) shrinks it to a small card at
      the top of the screen that leaves CarPlay usable; tapping the card
      brings the full screen back. A short chime plays when it opens and a
      softer one when it finishes (update-chime.wav and update-done.wav next
      to this file, via paplay; silently skipped if anything is missing).
      The installer drives it by rewriting STATEFILE with one line:
          <pct> <target> <seconds> <message>
      The bar sits at pct and eases toward target over about `seconds`
      (for steps that take a while but report nothing). pct 100 shows the
      message as done and closes after a few seconds; pct -1 shows it as a
      failure. Deleting STATEFILE closes the view.

Needs python3-xlib and PIL, both on the Pi.
"""
import functools
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from Xlib import X, display
from Xlib.ext import shape

THEME = Path("/usr/share/plymouth/themes/carplay")
READY_FILE = Path("/tmp/carplay_pi_launcher_winid")   # written by server.py
HERE = Path(__file__).resolve().parent
# On the Pi the fonts are in the deployed launcher; next to the repo copy for previews
FONT_DIRS = (Path.home() / "launcher/web/fonts", HERE.parent / "web/fonts")

# Dash palette, same values as the :root block in web/style.css
BG = (0x15, 0x17, 0x1a)
PANEL = (0x1e, 0x21, 0x25)
PANEL_HI = (0x26, 0x2a, 0x2f)
RULE = (0x2c, 0x30, 0x35)
PRESSED = (0x2c, 0x31, 0x37)
TEXT = (0xec, 0xe7, 0xdf)
STEEL = (0x8a, 0x8f, 0x96)
AMBER = (0xf0, 0xa5, 0x3a)
RED = (0xd6, 0x49, 0x3e)


@functools.lru_cache(maxsize=None)
def font(name, size):
    bold = "dejavu/DejaVuSans-Bold.ttf" if "-6" in name else "dejavu/DejaVuSans.ttf"
    paths = [d / name for d in FONT_DIRS]
    paths += [Path("/usr/share/fonts/truetype") / bold, Path("/usr/share/fonts/TTF") / Path(bold).name]
    for path in paths:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def put_image(win, gc, x, y, img, rows=64):
    """put_pil_image in strips small enough to go out as one request each:
    python-xlib's own splitting of a tall image overruns the image's bottom
    edge and paints black below it."""
    for top in range(0, img.height, rows):
        win.put_pil_image(gc, x, y + top, img.crop((0, top, img.width, min(img.height, top + rows))))


def overlay_window(d, x, y, w, h, bg, events=X.ExposureMask):
    screen = d.screen()
    pixel = screen.default_colormap.alloc_color(*(c * 257 for c in bg)).pixel
    win = screen.root.create_window(
        x, y, w, h, 0, screen.root_depth, X.InputOutput, X.CopyFromParent,
        background_pixel=pixel, override_redirect=True,
        event_mask=events)
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

SS = 2  # supersampling for smooth corners and text
CARD_W, CARD_H = 440, 84
FULL_W, FULL_H = 800, 480
POWER_NOTE = re.compile(r"\s*Keep the power on\.?\s*$")


def panel_image(w, h, radius):
    """A Dash panel (w, h at SS scale) on BG: 1 px rule edge, lit from the top.
    Returns the image and its rounded-corner mask."""
    img = Image.new("RGB", (w, h), BG)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=255)
    body = Image.new("RGB", (w, h), RULE)
    bd = ImageDraw.Draw(body)
    for y in range(SS, h - SS):
        t = min(1.0, y / (h * 0.4))
        bd.line((SS, y, w - SS - 1, y),
                fill=tuple(round(a + (b - a) * t) for a, b in zip(PANEL_HI, PANEL)))
    img.paste(body, (0, 0), mask)
    return img, mask


def card_spans():
    """Per-row x spans of the card's rounded shape, for the X SHAPE extension."""
    mask = Image.new("L", (CARD_W * SS, CARD_H * SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, CARD_W * SS - 1, CARD_H * SS - 1), 14 * SS, fill=255)
    small = mask.resize((CARD_W, CARD_H), Image.BOX)
    spans = []
    for yy in range(CARD_H):
        row = [x for x in range(CARD_W) if small.getpixel((x, yy)) >= 128]
        spans.append((row[0], row[-1] + 1) if row else None)
    return spans


def headline(state, title, done_title):
    return {"done": done_title, "failed": "Update failed"}.get(state, title)


def render_card(message, frac, state, title="Updating", done_title="Update complete"):
    """The compact card (CARD_W x CARD_H): title, message and a thin bar."""
    w, h = CARD_W * SS, CARD_H * SS
    img, _ = panel_image(w, h, 14 * SS)
    dr = ImageDraw.Draw(img)

    dr.text((20 * SS, 14 * SS), headline(state, title, done_title),
            font=font("barlow-600.woff2", 19 * SS), fill=RED if state == "failed" else TEXT)
    small = font("barlow-400.woff2", 15 * SS)
    dr.text((20 * SS, 40 * SS), wrap(dr, message, small, (CARD_W - 40) * SS, 1)[0], font=small, fill=STEEL)
    # chevron pointing down: tapping the card expands it to the full screen
    cx, cy = (CARD_W - 28) * SS, 24 * SS
    dr.line([(cx - 6 * SS, cy - 3 * SS), (cx, cy + 3 * SS), (cx + 6 * SS, cy - 3 * SS)],
            fill=STEEL, width=2 * SS, joint="curve")

    # track and fill, like the launcher's volume bar but thinner
    x0, x1, y = 20 * SS, w - 20 * SS, 68 * SS
    dr.rounded_rectangle((x0, y, x1, y + 4 * SS), 2 * SS, fill=RULE)
    fill = RED if state == "failed" else AMBER
    if frac > 0:
        dr.rounded_rectangle((x0, y, x0 + max(4 * SS, (x1 - x0) * frac), y + 4 * SS), 2 * SS, fill=fill)
    return img.resize((CARD_W, CARD_H), Image.BOX)


# Full-screen layout, in screen pixels. The panel inset and the content
# columns are shared by the static layer and the live (numeral + bar) layer.
PX0, PX1 = 24, FULL_W - 24            # panel left/right
X0, X1 = 60, FULL_W - 60              # content left/right
BAR_Y, BAR_H = 290, 16
DYN_BOX = (0, 150, FULL_W, 316)       # the part that changes while running


def spaced(dr, xy, text, fnt, fill, gap):
    """Text with extra letter spacing (small caps labels), baseline anchored."""
    x, y = xy
    for ch in text:
        dr.text((x, y), ch, font=fnt, fill=fill, anchor="ls")
        x += fnt.getlength(ch) + gap


def wrap(dr, text, fnt, width, lines):
    """Greedy word wrap to at most `lines` lines; the last one gets an ellipsis."""
    out, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and dr.textlength(trial, font=fnt) > width:
            out.append(cur)
            cur = word
        else:
            cur = trial
    out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        while out[-1] and dr.textlength(out[-1] + "...", font=fnt) > width:
            out[-1] = out[-1].rsplit(" ", 1)[0] if " " in out[-1] else out[-1][:-1]
        out[-1] += "..."
    return out


def draw_badge(dr, cx, cy, r, state):
    """Round status badge: amber check for done, red exclamation for failed."""
    r *= SS
    cx, cy = cx * SS, cy * SS
    dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=RED if state == "failed" else AMBER)
    if state == "failed":
        wd = round(r * 0.17)
        dr.rounded_rectangle((cx - wd, cy - r * 0.50, cx + wd, cy + r * 0.12), wd, fill=TEXT)
        dr.ellipse((cx - wd * 1.1, cy + r * 0.34, cx + wd * 1.1, cy + r * 0.34 + wd * 2.2), fill=TEXT)
    else:
        pts = [(cx - r * 0.38, cy + r * 0.02), (cx - r * 0.10, cy + r * 0.30), (cx + r * 0.42, cy - r * 0.28)]
        dr.line(pts, fill=BG, width=round(r * 0.18), joint="curve")
        for px, py in (pts[0], pts[-1]):
            e = r * 0.09
            dr.ellipse((px - e, py - e, px + e, py + e), fill=BG)


def full_base(message, state, title, done_title):
    """Everything on the full-screen view that doesn't move while it runs, at SS scale."""
    S = SS
    img = Image.new("RGB", (FULL_W * S, FULL_H * S), BG)
    panel, mask = panel_image((PX1 - PX0) * S, (FULL_H - 2 * PX0) * S, 20 * S)
    img.paste(panel, (PX0 * S, PX0 * S), mask)
    dr = ImageDraw.Draw(img)
    lit = RED if state == "failed" else AMBER

    # eyebrow with a status dot, and the Hide button
    dr.ellipse(((X0) * S, 58 * S, (X0 + 10) * S, 68 * S), fill=lit)
    spaced(dr, ((X0 + 24) * S, 70 * S), "SYSTEM UPDATE", font("barlow-500.woff2", 17 * S), STEEL, 2.6 * S)
    bx0, by0, bx1, by1 = X1 - 150, 44, X1, 96
    dr.rounded_rectangle((bx0 * S, by0 * S, bx1 * S, by1 * S), 26 * S, fill=PRESSED, outline=RULE, width=S)
    cx, cy = (bx0 + 36) * S, 71 * S      # chevron pointing up, toward where the card goes
    dr.line([(cx - 9 * S, cy + 4 * S), (cx, cy - 5 * S), (cx + 9 * S, cy + 4 * S)],
            fill=TEXT, width=3 * S, joint="curve")
    dr.text(((bx0 + 62) * S, 79 * S), "Hide", font=font("barlow-500.woff2", 24 * S), fill=TEXT, anchor="ls")

    # headline, shrunk if a long title would overflow
    text = headline(state, title, done_title)
    size = 46
    while size > 28 and dr.textlength(text, font=font("barlow-600.woff2", size * S)) > (X1 - X0) * S:
        size -= 2
    dr.text((X0 * S, 150 * S), text, font=font("barlow-600.woff2", size * S),
            fill=RED if state == "failed" else TEXT, anchor="ls")

    # message (the footer already says to keep the power on) and footer
    if state == "running":
        message = POWER_NOTE.sub("", message) or "Working"
    fnt = font("barlow-400.woff2", 27 * S)
    for i, line in enumerate(wrap(dr, message, fnt, (X1 - X0) * S, 2)):
        dr.text((X0 * S, (350 + 36 * i) * S), line, font=fnt, fill=TEXT, anchor="ls")
    if state == "running":
        dr.text((X0 * S, 428 * S), "Keep the power on", font=font("barlow-500.woff2", 23 * S),
                fill=AMBER, anchor="ls")
    hint = font("barlow-400.woff2", 19 * S)
    dr.text((X1 * S, 428 * S), "Tap anywhere to hide", font=hint, fill=STEEL, anchor="rs")
    return img


def full_live(img, frac, state):
    """Draw the numeral and bar onto `img`, which is the DYN_BOX crop of the base at SS scale."""
    S = SS
    dr = ImageDraw.Draw(img)
    oy = DYN_BOX[1]
    num = font("barlow-semi-condensed-600.woff2", 124 * S)
    base_y = (268 - oy) * S

    if state == "failed":
        draw_badge(dr, X0 + 46, 226 - oy, 46, state)
        word = font("barlow-semi-condensed-600.woff2", 76 * S)
        dr.text(((X0 + 124) * S, (250 - oy) * S), "Stopped", font=word, fill=RED, anchor="ls")
    else:
        pct = 100 if state == "done" else min(99, int(frac * 100))
        digits = str(pct)
        dr.text((X0 * S, base_y), digits, font=num, fill=AMBER if state == "done" else TEXT, anchor="ls")
        end = X0 * S + dr.textlength(digits, font=num)
        sign = font("barlow-semi-condensed-500.woff2", 54 * S)
        dr.text((end + 8 * S, base_y), "%", font=sign, fill=STEEL, anchor="ls")
        if state == "done":
            after = end + 8 * S + dr.textlength("%", font=sign)
            draw_badge(dr, round(after / S) + 56, 226 - oy, 40, state)

    y = (BAR_Y - oy) * S
    x0, x1 = X0 * S, X1 * S
    dr.rounded_rectangle((x0, y, x1, y + BAR_H * S), BAR_H * S // 2, fill=RULE)
    if frac > 0 or state != "running":
        fill = RED if state == "failed" else AMBER
        right = x0 + max(BAR_H * S, (x1 - x0) * frac)
        dr.rounded_rectangle((x0, y, right, y + BAR_H * S), BAR_H * S // 2, fill=fill)


class FullView:
    """Full-screen view. The static layer is cached per message/state; while
    only the numeral and bar move, just the DYN_BOX strip is redrawn."""

    def __init__(self, title, done_title):
        self.title, self.done_title = title, done_title
        self.key = self.base = None

    def frames(self, message, frac, state, everything):
        """[(x, y, image)] to paint: the whole screen, or only the live strip."""
        key = (message, state)
        if key != self.key:
            self.key, self.base = key, full_base(message, state, self.title, self.done_title)
            everything = True
        S = SS
        box = tuple(v * S for v in DYN_BOX)
        live = self.base.crop(box)
        full_live(live, frac, state)
        live = live.resize((FULL_W, DYN_BOX[3] - DYN_BOX[1]), Image.BOX)
        if not everything:
            return [(DYN_BOX[0], DYN_BOX[1], live)]
        whole = self.base.resize((FULL_W, FULL_H), Image.BOX)
        whole.paste(live, (DYN_BOX[0], DYN_BOX[1]))
        return [(0, 0, whole)]


def render_full(message, frac, state, title="Updating", done_title="Update complete"):
    """The full-screen view as one FULL_W x FULL_H image (for previews and tests)."""
    return FullView(title, done_title).frames(message, frac, state, True)[0][2]


def read_state(path):
    try:
        pct, target, secs, message = path.read_text().strip().split(" ", 3)
        return float(pct), float(target), float(secs), message
    except (OSError, ValueError):
        return None


def play(name):
    """Fire-and-forget a chime through PulseAudio. Never raises, never waits:
    no sound file, no paplay or no sound server just means no chime."""
    wav = HERE / name
    if not wav.exists():
        return
    env = dict(os.environ)
    run = f"/run/user/{os.getuid()}"
    if "XDG_RUNTIME_DIR" not in env and os.path.isdir(run):
        env["XDG_RUNTIME_DIR"] = run  # started over ssh, so PulseAudio's socket isn't advertised
    try:
        subprocess.Popen(["paplay", str(wav)], env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        pass


def progress(statefile, title="Updating", done_title="Update complete", idle_timeout=900):
    path = Path(statefile)
    d = display.Display()
    scr = d.screen()
    sw, sh = scr.width_in_pixels, scr.height_in_pixels
    buttons = X.ExposureMask | X.ButtonPressMask
    full_win, full_gc = overlay_window(d, (sw - FULL_W) // 2, (sh - FULL_H) // 2, FULL_W, FULL_H, BG, buttons)
    card_win, card_gc = overlay_window(d, (sw - CARD_W) // 2, 14, CARD_W, CARD_H, BG, buttons)
    if d.has_extension("SHAPE"):
        rects = [(s[0], y, s[1] - s[0], 1) for y, s in enumerate(card_spans()) if s]
        card_win.shape_rectangles(shape.SO.Set, shape.SK.Bounding, X.YXBanded, 0, 0, rects)
    wins = {"full": (full_win, full_gc), "card": (card_win, card_gc)}
    full = FullView(title, done_title)

    mode = "full"          # which view is on screen; a tap flips it
    switched = time.monotonic()
    redraw = True          # the visible view needs painting from scratch
    full_win.map()
    card_win.unmap()
    d.flush()
    play("update-chime.wav")

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

        # taps flip between the views; Expose means the visible one lost its pixels
        while d.pending_events():
            ev = d.next_event()
            if ev.type == X.ButtonPress and now - switched > 0.4:
                mode = "card" if mode == "full" else "full"
                wins["card" if mode == "full" else "full"][0].unmap()
                wins[mode][0].map()
                switched, redraw = now, True
            elif ev.type == X.Expose and ev.window.id == wins[mode][0].id and ev.count == 0:
                redraw = True
        win, gc = wins[mode]

        pct, target, secs, message = st
        if pct >= 100:
            state, frac = "done", 1.0
            if not done_at:
                play("update-done.wav")
            done_at = done_at or now
        elif pct < 0:
            state, frac = "failed", 1.0
            done_at = done_at or now
        else:
            # ease toward target: covers ~63% of the gap per `secs`, never arrives
            k = 1.0 - math.exp(-(now - since) / max(secs, 0.1)) if target > pct else 0.0
            state, frac = "running", (pct + (target - pct) * k) / 100.0
        if mode == "full":
            key = (message, state, int(frac * 100), round(frac * (X1 - X0)))
        else:
            key = (message, round(frac * CARD_W), state)
        if redraw or key != shown:
            if mode == "full":
                parts = full.frames(message, frac, state, redraw)
            else:
                parts = [(0, 0, render_card(message, frac, state, title, done_title))]
            for x, y, img in parts:
                put_image(win, gc, x, y, img)
            win.configure(stack_mode=X.Above)
            d.flush()
            shown, redraw = key, False
        elif int(now * 10) % 5 == 0:
            # an install may restart Chromium, whose window would land on top
            win.configure(stack_mode=X.Above)
            d.flush()
        if done_at and now - done_at > (8 if state == "failed" else 5):
            break
        if now - since > idle_timeout:
            break
        time.sleep(0.1)
    for win, _ in wins.values():
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
