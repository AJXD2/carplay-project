"""Footprint placement for the carrier board (used by gen_pcb.py).

Coordinates are millimetres on the KiCad sheet, board top-left at ORIGIN,
viewed from the TOP side: the side that faces the firewall, which is also
how you see the display from behind. The Pi sits under the board and plugs
into J2 from the bottom.

Everything about the Pi comes from the official HAT mechanical drawing
(datasheets/hat-mechanical.pdf) in the Pi's own frame: board 85 x 56, header
along the top edge, USB/Ethernet on the right short edge. PI below says where
that frame sits on our board: measured from Hosyond's back-view drawing,
scaled by the Pi's own 58 x 49 mm hole pattern (4.15 px/mm, both axes
agree to 0.1 %). The Pi is rotated 180 degrees: header at the bottom, ports
toward the left of the back view (the right of the screen from the front).
The display's pogo pads land under GPIO pins 2/4/6 exactly as predicted,
which cross-checks the orientation. Nominal holes: x 58.8 / 116.8, y 35.1 /
84.1 from the display's top-left corner (back view); verify with a ruler.
"""
import math

import pcbnew

PLACED = set()

# --- Pi placement on the board (provisional) -------------------------------
# (x, y) of the Pi's own top-left corner in board coordinates, and rotation
# of the Pi frame (0 = header at top / ports right; 180 = header at bottom /
# ports left).
PI = dict(x=35.3, y=31.6, rot=180)

PI_W, PI_H = 85.0, 56.0
PI_HOLES = [(3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)]
PI_PIN1 = (32.5 - 24.13, 3.5 + 1.27)        # inner row, end away from the USB ports
PORT_BLOCK = (65.0, -1.0, 90.0, 57.0)      # USB + Ethernet (13.5 mm tall): board height is 11 mm
DSI_FLEX = (-1.0, 19.5, 5.0, 36.5)          # HAT spec display flex cutout

# block anchors (board coordinates); provisional until the Pi is measured
AMP_AT = (143.0, 70.0)                      # TAS6424 centre
AMP_ROT = 90                                # block turned so outputs face up and the heatsink
                                            # runs along the right edge


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


# Measured correction: where the display outline really sits relative to the
# Pi, as a shift of the outer edge in mm (+x = right, +y = down, top view).
# Everything else (Pi, parts, notch, slot) stays put; copper keeps 3 mm from
# the edge, so shifts up to about 3 mm need no rerouting.
# Measured 2026-09-24 with calipers, Pi board edge to screen edge: ports
# side 36.65, ribbon side 43.40, GPIO side 15.35, USB-C/HDMI side 31.45
# (rounded down; sums 165.05 x 102.80). Against the photo estimate the
# screen sits 1.35 mm further toward the ports; up/down agrees within 0.15.
OUTLINE_SHIFT = (-1.35, 0.0)


def outline_points(x0, y0, w, h):
    """Board edge: the display outline, minus a notch that runs from the
    Pi's USB/Ethernet block out to the edge the ports face, so the tall
    jacks clear the board and the cables can reach them."""
    nx0, ny0, nx1, ny1 = pi_rect(PORT_BLOCK)
    sx, sy = OUTLINE_SHIFT
    l, t, r, b = sx, sy, w + sx, h + sy
    facing = {0: "right", 90: "up", 180: "left", 270: "down"}[PI["rot"] % 360]
    if facing == "left":
        pts = [(l, t), (r, t), (r, b), (l, b), (l, ny1), (nx1, ny1), (nx1, ny0), (l, ny0)]
    elif facing == "right":
        pts = [(l, t), (r, t), (r, ny0), (nx0, ny0), (nx0, ny1), (r, ny1), (r, b), (l, b)]
    else:
        raise SystemExit("notch for a rotated Pi not written yet")
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

AMP_CH = {"4": "FR", "3": "FL", "2": "RR", "1": "RL"}
AMP_ROW = {"4": -12.0, "3": -4.0, "2": 4.0, "1": 12.0}      # coil rows (y from chip centre)
# boot caps centred on their BST/OUT pin pair (0.635 mm pitch)
BOOT_Y = {("4", "P"): -6.985, ("4", "M"): -5.08, ("3", "P"): -3.175, ("3", "M"): -1.27,
          ("2", "P"): 1.27, ("2", "M"): 3.175, ("1", "P"): 5.08, ("1", "M"): 6.985}
COIL_X = {"P": 22.0, "M": 36.0}                              # coil column centres; the gap
                                                             # to the chip carries the P escapes
                                                             # and the M vias
HEATSINK_Y = 15.5                                            # screw distance from chip centre


def place_amp(fps, ax, ay):
    """TAS6424 flow-through layout after the EVM (SLOSE73A fig 12-1): chip
    vertical, supply/analog caps left, outputs right into two coil columns
    (P legs, then M legs routed underneath on the bottom layer), heatsink
    screws at both ends of the chip."""
    amp, flt = section(fps, "amp"), section(fps, "filter")
    u = one(amp, "TAS6424E-Q1")

    def P(dx, dy, f, rot=0):
        # offsets are drawn for the chip upright; turn them with the block
        # (KiCad angles are counter-clockwise as seen on screen, y down)
        a = math.radians(AMP_ROT)
        rx = dx * math.cos(a) + dy * math.sin(a)
        ry = -dx * math.sin(a) + dy * math.cos(a)
        put(f, ax + rx, ay + ry, (rot + AMP_ROT) % 360)

    P(0, 0, u)

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
        # BST sits on the far side of OUT for P legs and the near side for M
        # legs, so the caps face opposite ways and their traces never cross
        for leg, x, rot in (("P", 6.4, 270), ("M", 8.3, 90)):
            P(x, BOOT_Y[(ch, leg)], one(amp, "1uF", [f"BST_{ch}{leg}"]), rot)
    small = find(amp, "100nF", ["+12V_PROT"], n=3)
    bulk = find(amp, "10uF", ["+12V_PROT"], n=3)
    P(5.6, -10.9, small[0])
    P(7.4, -13.2, bulk[0])
    # centre PVDD pins 42/43 are boxed in by boot caps: they drop to the
    # +12V_PROT plane through vias under the chip body. Their 100 nF stands
    # between channels 2 and 3; the 10 uF joins the bulk below the chip.
    P(13.4, -0.5, small[1], 0)
    put(bulk[1], ax - 14.0, ay + 7.6, 180)
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
    # PVDD bulk left of the coils, over the display-cable slot's end: the
    # corridor above the filters stays free for the speaker tracks
    put(one(amp, "470uF"), ax - 22.5, ay - 25.5, 180)


# --- harness, input protection, buck ------------------------------------------

J1_PIN1 = (104.0, 7.0)                      # along the top edge, pins 1..10 running right
PROT_Y = 21.0                               # battery path row
PROT_DX = -55.2                             # protection block shifted left from its drawn spot
BUCK_AT = (80.0, 60.0)                      # LM61460 centre, over the Pi next to its 5V pins


def place_harness(fps, ox, oy):
    """J1 sits along the top edge (the harness plug points at the firewall),
    speaker pins toward the amp's output filters."""
    j1 = fps["J1"]
    x, y = ox + J1_PIN1[0], oy + J1_PIN1[1]
    for rot in (0, 90, 180, 270):
        put_pad(j1, 1, x, y, rot)
        p2, p11 = pad_xy(j1, 2), pad_xy(j1, 11)
        if abs(p2[1] - y) < 0.05 and p2[0] > x and p11[1] > y:
            return
    raise SystemExit("J1: no rotation found")


def place_protection(fps, ox, oy):
    """Battery enters top-right and runs left: TVS, input cap, Q1 (reverse
    battery, source toward the battery), Q2 (load disconnect), output cap.
    The drain tabs face each other so VMID is a short fat node."""
    g = section(fps, "protection")
    y = oy + PROT_Y
    X = lambda v: ox + v + PROT_DX
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
    # turned so each pin row faces its parts: battery side (A, DGATE, SW,
    # OV) toward Q1 and the divider, output side (C, VS, CAP, HGATE, OUT)
    # toward Q2, C4 and C5
    put(one(g, "LM74800-Q1"), X(139.5), y - 9.0, 180)
    put(one(g, "100R"), X(129.6), y + 5.0, 90)
    put(one(g, "22nF"), X(129.6), y + 8.6, 90)
    # U1's output-side pins run GND, HGATE, OUT, VS, CAP, C at 0.5 mm: VS
    # runs straight out to C5 (CAP-VS, standing) and C4 (VS-GND) on its line
    put(one(g, "220nF"), X(133.2), y - 7.95, 270)
    put(one(g, "100nF", ["VMID"]), X(130.5), y - 8.725, 180)
    # divider rows in U1's pin order (OV_SET above SW): 3.65k OV-GND on top,
    # 5.11k turned so its OV end faces U1, 95.3k SW-BATT_MON at the bottom
    for i, (v, rot) in enumerate((("3.65k", 0), ("5.11k", 180), ("95.3k", 0))):
        put(one(g, v), X(144.2), y - 11.6 + 1.6 * i, rot)


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

    # RTC and coin cell in the top-left corner, ID EEPROM beside them
    rtc = section(fps, "rtc")
    put(one(rtc, "CR2032"), X(6.0), Y(15.0))
    put(one(rtc, "DS3231SN"), X(40.5), Y(9.0))
    put(one(rtc, "CAT24C32"), X(40.5), Y(22.5))
    pack(find(rtc, n=0), X(48.5), Y(3.3), X(66.0))

    # key / lights / reverse sensing next to J1's control pins (top right)
    hold = section(fps, "hold")
    y = Y(3.3)
    for net in ("ACC_ON", "LIGHTS_ON", "REVERSE"):
        base = next(f for f in find(hold, "MMBT3904", n=0) if has(f, net))
        parts = [one(hold, "47k", [f"Net-({base.GetReference()}-B)"]),
                 one(hold, "10k", [f"Net-({base.GetReference()}-B)"]),
                 one(hold, "100nF", [f"Net-({base.GetReference()}-B)"]), base,
                 one(hold, "10k", [net])]
        pack(parts, X(137.0), y, X(164.5))
        y += 3.9
    # power-hold network over the Pi, on the way to the LM74800's EN pin
    pack(find(hold, n=0), X(95.0), Y(37.0), X(113.5))

    # steering wheel + battery ADC over the Pi
    swc = section(fps, "swc")
    put(one(swc, "ADS1115IDGS"), X(88.0), Y(47.0))
    pack(find(swc, n=0), X(63.0), Y(37.0), X(93.0))

    # audio clocks bottom right, between the amp's clock pins and the Pi's I2S pins
    clk = section(fps, "clock")
    pack(find(clk, n=0), X(123.0), Y(84.5), X(159.5))

    # fans along the bottom-left edge so their cables come off the board edge
    fans = section(fps, "fans")
    # tach pull-ups sit by the Pi header, under their GPIO pins, where +3V3
    # is close: out in the fan strip nothing can reach them with +3V3
    j2 = fps["J2"]
    for net in ("FAN1_TACH", "FAN2_TACH"):
        pu = next(f for f in find(fans, n=0) if has(f, "+3V3") and has(f, net))
        pin = next(p for p in j2.Pads() if net in p.GetNetname())
        px = pcbnew.ToMM(pin.GetPosition().x)
        put(pu, px, Y(88.6))
    for i, net in enumerate(("FAN1", "FAN2")):
        hdr = next(f for f in find(fans, n=0) if f.GetValue() == net)
        put(hdr, X(4.0 + 24.0 * i), Y(98.5))
        rest = [f for f in find(fans, n=0) if any(net in n for n in nets_of(f)) or
                has(f, f"Net-({hdr.GetReference()}-PWM)")]
        pack(rest, X(3.3 + 24.0 * i), Y(89.3), X(25.3 + 24.0 * i))

    # debug UART (not fitted) on the bottom edge
    put(fps["J3"], X(52.0), Y(92.5))

    # mic jack on the right edge beside the PCM1808 (plug enters from the
    # side), its bias/filter parts in the strip between them
    mic = section(fps, "mic")
    put(one(mic, "MIC"), X(154.5), Y(95.4), 180)
    pack(find(mic, n=0), X(126.0), Y(93.6), X(147.5))

    # status LEDs next to the debug header: 12V, 5V, PI HOLD, left to right
    leds = section(fps, "leds")
    for i, net in enumerate(("+12V_PROT", "+5V", "PI_HOLD")):
        r = next(f for f in find(leds, n=0) if f.GetValue() != "RED" and has(f, net))
        mid = nets_of(r) - {net}
        d = next(f for f in find(leds, n=0) if f.GetValue() == "RED" and nets_of(f) & mid)
        put(r, X(57.5 + 4.0 * i), Y(92.8), 90)
        put(d, X(57.5 + 4.0 * i), Y(96.0), 90)


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
    hw, hl = (20.7, 10.0) if AMP_ROT % 180 else (10.0, 20.7)
    for layer in (pcbnew.Dwgs_User, pcbnew.F_Fab):
        r = pcbnew.PCB_SHAPE(board)
        r.SetShape(pcbnew.SHAPE_T_RECT)
        r.SetStart(pcbnew.VECTOR2I(mm(ax - hw), mm(ay - hl)))
        r.SetEnd(pcbnew.VECTOR2I(mm(ax + hw), mm(ay + hl)))
        r.SetLayer(layer)
        r.SetWidth(mm(0.15))
        board.Add(r)
    t = pcbnew.PCB_TEXT(board)
    t.SetText("HEATSINK 20x41.4 (mech/heatsink.step): parts under it < 2.2 mm")
    t.SetLayer(pcbnew.Dwgs_User)
    t.SetPosition(pcbnew.VECTOR2I(mm(ax), mm(ay + hl + 1.5)))
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
