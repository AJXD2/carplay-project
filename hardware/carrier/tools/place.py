"""Footprint placement for the carrier board (used by gen_pcb.py).

Coordinates are millimetres on the KiCad sheet, board top-left at ORIGIN,
viewed from the TOP side: the side that faces the firewall, which is also
how you see the display from behind. The Pi sits under the board and plugs
into J2 from the bottom.

Everything about the Pi comes from the official HAT mechanical drawing
(datasheets/hat-mechanical.pdf) in the Pi's own frame: board 85 x 56, header
along the top edge, USB/Ethernet on the right short edge. PI below says where
that frame sits on our board. It is PROVISIONAL until the Pi's position on
the display is measured (the photos show it rotated 180 degrees with the
ports toward the display's left edge).
"""
import math

import pcbnew

PLACED = set()

# --- Pi placement on the board (provisional) -------------------------------
# (x, y) of the Pi's own top-left corner in board coordinates, and rotation
# of the Pi frame (0 = header at top / ports right; 180 = header at bottom /
# ports left).
PI = dict(x=2.0, y=23.5, rot=180)

PI_W, PI_H = 85.0, 56.0
PI_HOLES = [(3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)]
PI_PIN1 = (32.5 - 24.13, 3.5 + 1.27)        # inner row, end away from the USB ports
PORT_BLOCK = (63.0, -2.0, 90.0, 58.0)      # USB + Ethernet, taller than the board height
DSI_FLEX = (-1.0, 19.5, 5.0, 36.5)          # HAT spec display flex cutout

# block anchors (board coordinates); provisional until the Pi is measured
AMP_AT = (108.0, 68.0)                      # TAS6424 centre


def mm(v):
    return pcbnew.FromMM(v)


def pi_to_board(px, py):
    """Point in the Pi frame -> board coordinates (relative to board origin)."""
    a = math.radians(PI["rot"])
    cx, cy = PI_W / 2, PI_H / 2
    dx, dy = px - cx, py - cy
    rx = dx * math.cos(a) - dy * math.sin(a)
    ry = dx * math.sin(a) + dy * math.cos(a)
    # the rotated Pi keeps its bounding box at PI[x], PI[y]
    if PI["rot"] % 180 == 0:
        return PI["x"] + PI_W / 2 + rx, PI["y"] + PI_H / 2 + ry
    return PI["x"] + PI_H / 2 + rx, PI["y"] + PI_W / 2 + ry


def pi_rect(r):
    xs, ys = zip(pi_to_board(r[0], r[1]), pi_to_board(r[2], r[3]))
    return min(xs), min(ys), max(xs), max(ys)


def outline_points(x0, y0, w, h):
    """Board edge: the display outline, minus a notch around the Pi's
    USB/Ethernet block wherever it meets the edge."""
    nx0, ny0, nx1, ny1 = pi_rect(PORT_BLOCK)
    nx0, nx1 = max(nx0, 0.0), min(nx1, w)
    ny0, ny1 = max(ny0, 0.0), min(ny1, h)
    pts = [(0, 0), (w, 0), (w, h), (0, h)]
    if nx0 <= 0.5:                                      # notch on the left edge
        pts = [(0, 0), (w, 0), (w, h), (0, h), (0, ny1), (nx1, ny1), (nx1, ny0), (0, ny0)]
    elif nx1 >= w - 0.5:                                # notch on the right edge
        pts = [(0, 0), (w, 0), (w, ny0), (nx0, ny0), (nx0, ny1), (w, ny1), (w, h), (0, h)]
    return [(x0 + x, y0 + y) for x, y in pts]


def cutouts():
    """Internal slots (board coordinates): the display ribbon cutout."""
    return [pi_rect(DSI_FLEX)]


def put(fp, x, y, rot=0, bottom=False):
    if bottom and not fp.IsFlipped():
        fp.Flip(fp.GetPosition(), False)
    fp.SetOrientationDegrees(rot)
    fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    PLACED.add(fp.GetReference())


def put_pad(fp, pad, x, y, rot=0, bottom=False):
    """Place so that pad `pad` lands on (x, y)."""
    put(fp, 0, 0, rot, bottom)
    p = next(p for p in fp.Pads() if p.GetNumber() == str(pad)).GetPosition()
    fp.SetPosition(pcbnew.VECTOR2I(mm(x) - p.x, mm(y) - p.y))


def pad_xy(fp, pad):
    p = next(p for p in fp.Pads() if p.GetNumber() == str(pad)).GetPosition()
    return pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)


def is_placed(fp):
    return fp.GetReference() in PLACED


# --- sections --------------------------------------------------------------

def place_pi(fps, ox, oy):
    """J2 on the bottom, pin 1 over the Pi's pin 1; H1-H4 over the Pi holes."""
    j2 = fps["J2"]
    x1, y1 = pi_to_board(*PI_PIN1)
    # flipped socket: pick the rotation whose pin 3 steps along the header
    # and whose pin 2 steps to the outer row, exactly as on the Pi
    want3 = pi_to_board(PI_PIN1[0] + 2.54, PI_PIN1[1])
    want2 = pi_to_board(PI_PIN1[0], PI_PIN1[1] - 2.54)
    for rot in (0, 90, 180, 270):
        put_pad(j2, 1, ox + x1, oy + y1, rot, bottom=True)
        p2, p3 = pad_xy(j2, 2), pad_xy(j2, 3)
        if (abs(p3[0] - (ox + want3[0])) < 0.05 and abs(p3[1] - (oy + want3[1])) < 0.05 and
                abs(p2[0] - (ox + want2[0])) < 0.05 and abs(p2[1] - (oy + want2[1])) < 0.05):
            break
    else:
        raise SystemExit("J2: no rotation matches the Pi header")
    for ref, (hx, hy) in zip(("H1", "H2", "H3", "H4"), PI_HOLES):
        bx, by = pi_to_board(hx, hy)
        put(fps[ref], ox + bx, oy + by)


# --- finding parts ---------------------------------------------------------

def nets_of(fp):
    return {p.GetNetname() for p in fp.Pads() if p.GetNetname()}


def section(fps, name):
    return {r: f for r, f in fps.items() if f.GetFieldText("Section") == name}


def find(group, value=None, nets=(), fp_has=None, n=1):
    """Parts in `group` with this value whose pads touch all of `nets`
    (a net matches if its name contains the given text)."""
    hits = []
    for r, f in sorted(group.items()):
        if r in PLACED:
            continue
        if value and f.GetValue() != value:
            continue
        if fp_has and fp_has not in str(f.GetFPID().GetLibItemName()):
            continue
        fn = nets_of(f)
        if all(any(t in x for x in fn) for t in nets):
            hits.append(f)
    if n and len(hits) < n:
        raise SystemExit(f"find: {value} {nets}: {len(hits)} of {n}")
    return hits[:n] if n else hits


def one(*a, **k):
    return find(*a, **k)[0]


# --- amplifier block ---------------------------------------------------------

AMP_CH = {"4": "RR", "3": "RL", "2": "FR", "1": "FL"}
AMP_ROW = {"4": -12.0, "3": -4.0, "2": 4.0, "1": 12.0}      # coil rows (y from chip centre)
BOOT_Y = {("4", "P"): -6.99, ("4", "M"): -5.08, ("3", "P"): -3.8, ("3", "M"): -1.9,
          ("2", "P"): 1.9, ("2", "M"): 3.8, ("1", "P"): 5.08, ("1", "M"): 6.99}
COIL_X = {"P": 18.8, "M": 32.8}                              # coil column centres
HEATSINK_Y = 15.5                                            # screw distance from chip centre


def place_amp(fps, ax, ay):
    """TAS6424 flow-through layout after the EVM (SLOSE73A fig 12-1): chip
    vertical, supply/analog caps left, outputs right into two coil columns
    (P legs, then M legs routed underneath on the bottom layer), heatsink
    screws at both ends of the chip."""
    amp, flt = section(fps, "amp"), section(fps, "filter")
    u = one(amp, "TAS6424E-Q1")
    put(u, ax, ay)
    P = lambda dx, dy, f, rot=0: put(f, ax + dx, ay + dy, rot)

    # left: VBAT, VREG/VCOM (to AREF), AVDD (to AVSS), GVDD x2, VDD. Horizontal
    # caps stacked one courtyard apart, chip-side pad toward their pins.
    P(-8.4, -9.4, one(amp, "1uF", ["+12V_PROT"], fp_has="0805"))
    P(-8.0, -7.5, one(amp, "1uF", ["VREG"]))
    P(-8.0, -5.85, one(amp, "1uF", ["VCOM"]))
    P(-8.0, -4.2, one(amp, "1uF", ["AVDD"]))
    g1, g2 = find(amp, "2.2uF", ["GVDD"], n=2)
    P(-8.4, -2.3, g1)
    P(-8.4, -0.2, g2)
    P(-8.0, 2.86, one(amp, "1uF", ["+3V3"]))

    # right: boot caps in two columns, PVDD decoupling at the corners and middle
    for ch in AMP_CH:
        for leg, x in (("P", 6.4), ("M", 8.3)):
            P(x, BOOT_Y[(ch, leg)], one(amp, "1uF", [f"BST_{ch}{leg}"]), 90)
    small = find(amp, "100nF", ["+12V_PROT"], n=3)
    bulk = find(amp, "10uF", ["+12V_PROT"], n=3)
    P(5.6, -10.9, small[0])
    P(7.4, -13.2, bulk[0])
    P(10.6, 0.0, small[1], 90)
    P(12.7, 0.0, bulk[1], 90)
    P(5.6, 10.9, small[2])
    P(7.4, 13.2, bulk[2])

    # coils and filter caps, one row per channel
    for ch, name in AMP_CH.items():
        for leg, pol in (("P", "+"), ("M", "-")):
            cx, cy = COIL_X[leg], AMP_ROW[ch]
            P(cx, cy, one(flt, "3.3uH", [f"AMP_{name}{pol}"]))
            P(cx + 5.8, cy - 1.6, one(flt, "1uF", [f"SPK_{name}{pol}"]), 90)
            P(cx + 5.8, cy + 2.0, one(flt, "1nF", [f"SPK_{name}{pol}"]), 90)

    # heatsink screws (grounded) at both ends of the chip
    hs = find(section(fps, "misc"), "Heatsink", n=2)
    P(0, -HEATSINK_Y, hs[0])
    P(0, HEATSINK_Y, hs[1])
    P(-12.0, 20.0, one(amp, "470uF"))


def park(fps, origin, size):
    """Grid below the board, grouped by reference prefix."""
    x0, y0 = origin
    x, y = x0, y0 + size[1] + 15
    row_h = 0
    for ref in sorted((r for r in fps if r not in PLACED),
                      key=lambda r: (r.rstrip("0123456789"), int(r[len(r.rstrip("0123456789")):] or 0))):
        fp = fps[ref]
        bb = fp.GetBoundingBox(False)
        w, h = pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight())
        if x + w > x0 + size[0] + 60:
            x, y = x0, y + row_h + 3
            row_h = 0
        fp.SetPosition(pcbnew.VECTOR2I(mm(x + w / 2), mm(y + h / 2)))
        x += w + 3
        row_h = max(row_h, h)


def place_all(board, fps, origin, size):
    ox, oy = origin
    place_pi(fps, ox, oy)
    place_amp(fps, ox + AMP_AT[0], oy + AMP_AT[1])
    park(fps, origin, size)
