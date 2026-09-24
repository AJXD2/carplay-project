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


def has(fp, text):
    return any(text in n for n in nets_of(fp))


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
    P(9.0, -27.5, one(amp, "470uF"))                   # PVDD bulk, clear of the heatsink


# --- harness, input protection, buck ------------------------------------------

J1_PIN1 = (159.0, 44.0)                     # vertical along the right edge
PROT_Y = 33.0                               # battery path row
BUCK_AT = (62.0, 13.0)                      # LM61460 centre


def place_harness(fps, ox, oy):
    """J1 stands along the right edge, pins 1..10 running down, next to the
    amp's filter caps so the speaker runs stay short."""
    j1 = fps["J1"]
    x, y = ox + J1_PIN1[0], oy + J1_PIN1[1]
    for rot in (0, 90, 180, 270):
        put_pad(j1, 1, x, y, rot)
        p2, p11 = pad_xy(j1, 2), pad_xy(j1, 11)
        if abs(p2[0] - x) < 0.05 and p2[1] > y and p11[0] < x:
            return
    raise SystemExit("J1: no rotation found")


def place_protection(fps, ox, oy):
    """Battery enters top-right and runs left: TVS, input cap, Q1 (reverse
    battery, source toward the battery), Q2 (load disconnect), output cap.
    The drain tabs face each other so VMID is a short fat node."""
    g = section(fps, "protection")
    y = oy + PROT_Y
    X = lambda v: ox + v
    put(one(g, "SMBJ33CA"), X(156.0), y - 1.0, 90)
    c_in, c_out = sorted(find(g, "100nF", ["+12V_"], n=2), key=lambda f: has(f, "+12V_PROT"))
    put(c_in, X(150.8), y, 90)
    qs = find(g, "BUK7Y4R8-60E", n=2)
    q1 = next(q for q in qs if has(q, "+12V_BATT"))
    q2 = next(q for q in qs if q is not q1)
    put(q1, X(143.2), y, 180)
    put(q2, X(134.4), y, 0)
    put(c_out, X(128.6), y, 90)
    # controller above the FET row, gate network below Q2's gate
    put(one(g, "LM74800-Q1"), X(139.5), y - 9.0)
    put(one(g, "100R"), X(129.6), y + 5.0, 90)
    put(one(g, "22nF"), X(129.6), y + 8.6, 90)
    put(one(g, "100nF", ["VMID"]), X(135.2), y - 9.0, 90)
    put(one(g, "220nF"), X(137.0), y - 12.6)
    for i, v in enumerate(("95.3k", "5.11k", "3.65k")):
        put(one(g, v), X(144.2), y - 11.6 + 1.6 * i)


def place_buck(fps, ox, oy):
    """LM61460 per SNVSB70F 11.2: 100 nF across each VIN/PGND pair, 10 uF
    right behind, coil straight off SW, output caps after it; analog parts
    on the quiet left side. TLV75533 below."""
    g = section(fps, "buck")
    bx, by = ox + BUCK_AT[0], oy + BUCK_AT[1]
    P = lambda dx, dy, f, rot=0: put(f, bx + dx, by + dy, rot)
    u = one(g, "LM61460-Q1")
    P(0, 0, u)
    hf = find(g, "100nF", ["+12V_PROT"], n=2)
    P(1.15, 2.85, hf[0])
    P(1.15, -2.85, hf[1])
    bulk = find(g, "10uF", ["+12V_PROT"], n=2)
    P(1.15, 5.6, bulk[0])
    P(1.15, -5.6, bulk[1])
    P(9.0, 0, one(g, "4.7uH"))
    c47 = find(g, "47uF", n=2)
    P(17.6, -2.6, c47[0], 90)
    P(21.2, -2.6, c47[1], 90)
    P(19.4, 2.9, one(g, "100nF", ["+5V"]))
    # boot: CBOOT (pin 14) / RBOOT (pin 13) sit top-left
    P(-3.0, -3.6, one(g, "100nF", ["CBOOT"]), 90)
    P(-4.8, -3.6, one(g, "0R"), 90)
    # analog side, clear of the switching loop
    P(-4.2, -0.2, one(g, "1uF", ["VCC"]), 90)
    P(-6.6, -3.6, one(g, "1uF", ["+5V"]), 90)                 # BIAS
    P(-2.0, 3.8, one(g, "33.2k"), 90)                         # RT
    P(-3.7, 4.8, one(g, "100k", ["EN"]), 90)
    P(-5.3, 4.8, one(g, "26.7k"), 90)
    P(-6.9, 1.2, one(g, "100k", ["FB"]), 90)                  # RFBT
    P(-8.5, 1.2, one(g, "24.9k"), 90)                         # RFBB
    P(-10.1, 1.2, one(g, "1k"), 90)                            # RFF
    P(-11.7, 1.2, one(g, "22pF"), 90)                         # CFF
    # 3.3 V LDO
    P(8.0, 11.0, one(g, "TLV75533PDBV"))
    P(4.4, 11.0, one(g, "1uF", ["+5V"]), 90)
    P(11.6, 11.0, one(g, "1uF", ["+3V3"]), 90)


# --- slow, low-power circuits: packed in rows ---------------------------------

def _size(fp, rot):
    fp.SetOrientationDegrees(rot)
    cy = fp.GetCourtyard(pcbnew.F_CrtYd)
    bb = cy.BBox() if cy.OutlineCount() else fp.GetBoundingBox(False)
    pos = fp.GetPosition()
    return (pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight()),
            pcbnew.ToMM(bb.GetCenter().x - pos.x), pcbnew.ToMM(bb.GetCenter().y - pos.y))


def pack(parts, x0, y0, x1, gap=0.8, rot=0):
    """Lay parts out left to right in rows between x0 and x1, keeping their
    order (so a signal chain reads left to right). Returns the y below."""
    x, y, row_h = x0, y0, 0.0
    for fp in parts:
        w, h, cx, cy = _size(fp, rot)
        if x + w > x1 and x > x0:
            x, y, row_h = x0, y + row_h + gap, 0.0
        put(fp, x + w / 2 - cx, y + h / 2 - cy, rot)
        x += w + gap
        row_h = max(row_h, h)
    return y + row_h + gap


def chain(g, *specs):
    """Parts by (value, net) in order, skipping ones already placed."""
    return [one(g, v, [n] if n else []) for v, n in specs]


def place_small(fps, ox, oy):
    X, Y = (lambda v: ox + v), (lambda v: oy + v)

    # RTC, coin cell, ID EEPROM over the Pi (top side is free there)
    rtc = section(fps, "rtc")
    put(one(rtc, "CR2032"), X(33.0), Y(45.8))
    put(one(rtc, "DS3231SN"), X(71.0), Y(38.0))
    y = pack(chain(rtc, ("100nF", "+3V3"), ("10k", "RTC_INT")), X(64.0), Y(45.0), X(80.0))
    put(one(rtc, "CAT24C32"), X(71.0), y + 4.0)
    pack(find(rtc, n=0), X(62.0), y + 8.5, X(81.0))

    # MCLK option (not fitted) beside the RTC
    clk = section(fps, "clock")
    pack(find(clk, n=0), X(40.0), Y(59.6), X(62.0))

    # key / lights / reverse sensing and power hold, next to J1's control pins
    hold = section(fps, "hold")
    y = Y(88.0)
    for net in ("ACC_ON", "LIGHTS_ON", "REVERSE"):
        base = next(f for f in find(hold, "MMBT3904", n=0) if has(f, net))
        parts = [one(hold, "47k", [f"Net-({base.GetReference()}-B)"]),
                 one(hold, "10k", [f"Net-({base.GetReference()}-B)"]),
                 one(hold, "100nF", [f"Net-({base.GetReference()}-B)"]), base,
                 one(hold, "10k", [net])]
        pack(parts, X(126.0), y, X(164.0))
        y += 4.2
    pack(find(hold, n=0), X(96.0), Y(96.0), X(124.0))

    # steering wheel + battery ADC
    swc = section(fps, "swc")
    put(one(swc, "ADS1115IDGS"), X(80.0), Y(92.0))
    pack(find(swc, n=0), X(56.0), Y(86.0), X(76.0))

    # fans along the bottom-left edge so their cables come off the board edge
    fans = section(fps, "fans")
    for i, net in enumerate(("FAN1", "FAN2")):
        hdr = next(f for f in find(fans, n=0) if f.GetValue() == net)
        put(hdr, X(4.0 + 24.0 * i), Y(97.5))
        rest = [f for f in find(fans, n=0) if any(net in n for n in nets_of(f)) or
                has(f, f"Net-({hdr.GetReference()}-PWM)")]
        pack(rest, X(2.0 + 24.0 * i), Y(84.0), X(24.0 + 24.0 * i))

    # debug UART (not fitted) in the corner
    put(fps["J3"], X(52.0), Y(95.0))


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


def heatsink_outline(board, ox, oy):
    """Heatsink footprint (tools/heatsink.py) on Dwgs.User and F.Fab, so tall
    parts stay out from under it. Everything under it must be < 2.2 mm."""
    ax, ay = ox + AMP_AT[0], oy + AMP_AT[1]
    for layer in (pcbnew.Dwgs_User, pcbnew.F_Fab):
        r = pcbnew.PCB_SHAPE(board)
        r.SetShape(pcbnew.SHAPE_T_RECT)
        r.SetStart(pcbnew.VECTOR2I(mm(ax - 10.0), mm(ay - 20.7)))
        r.SetEnd(pcbnew.VECTOR2I(mm(ax + 10.0), mm(ay + 20.7)))
        r.SetLayer(layer)
        r.SetWidth(mm(0.15))
        board.Add(r)
    t = pcbnew.PCB_TEXT(board)
    t.SetText("HEATSINK 20x41.4 (mech/heatsink.step): parts under it < 2.2 mm")
    t.SetLayer(pcbnew.Dwgs_User)
    t.SetPosition(pcbnew.VECTOR2I(mm(ax), mm(ay + 22.0)))
    t.SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
    board.Add(t)


def place_all(board, fps, origin, size):
    ox, oy = origin
    place_pi(fps, ox, oy)
    place_amp(fps, ox + AMP_AT[0], oy + AMP_AT[1])
    place_harness(fps, ox, oy)
    place_protection(fps, ox, oy)
    place_buck(fps, ox, oy)
    place_small(fps, ox, oy)
    heatsink_outline(board, ox, oy)
    park(fps, origin, size)
