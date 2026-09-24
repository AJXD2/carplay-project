#!/usr/bin/env python3
"""Planes, power pours and the hand-routed power/audio paths.

Runs on the board gen_pcb.py builds, before the autorouter (autoroute.py):

    flatpak run --command=python3 org.kicad.KiCad tools/route.py

Everything here is locked so Freerouting routes around it. Coordinates are
board mm from the top-left corner, like place.py.

Stack-up: F.Cu parts + signals | In1 solid GND | In2 split: +12V_PROT over
the protection, amp and buck input, +5V over the rest | B.Cu signals. Outer
layers get a GND pour last. Nothing copper within EDGE of the display
outline: if the Pi turns out to sit a little differently on the screen, the
outline moves and no copper has to.
"""
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
PCB = os.path.join(ROOT, "carrier.kicad_pcb")
sys.path.insert(0, HERE)
import place  # noqa: E402

OX, OY = 100.0, 100.0
W, H = 165.0, 103.0
EDGE = 3.0

F, B, IN1, IN2 = pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu

board = None
FPS = {}


def mm(v):
    return pcbnew.FromMM(v)


def V(x, y):
    return pcbnew.VECTOR2I(mm(OX + x), mm(OY + y))


def net(name):
    n = board.FindNet(name)
    if n is None:
        raise SystemExit(f"no net {name}")
    return n


def pad(ref, num):
    p = next(p for p in FPS[ref].Pads() if p.GetNumber() == str(num))
    q = p.GetPosition()
    return pcbnew.ToMM(q.x) - OX, pcbnew.ToMM(q.y) - OY


def pad_net(ref, num):
    return next(p for p in FPS[ref].Pads() if p.GetNumber() == str(num)).GetNetname()


def pads_on(ref, text):
    """(number, x, y) of the pads of `ref` whose net contains `text`."""
    return [(p.GetNumber(), *pad(ref, p.GetNumber())) for p in FPS[ref].Pads() if text in p.GetNetname()]


def ref_of(value, net_text):
    """The one footprint with this value that touches this net."""
    hits = [r for r, f in FPS.items() if f.GetValue() == value and
            any(net_text in p.GetNetname() for p in f.Pads())]
    if len(hits) != 1:
        raise SystemExit(f"ref_of({value}, {net_text}): {hits}")
    return hits[0]


# --- primitives --------------------------------------------------------------

def track(netname, layer, width, pts):
    n = net(netname)
    for a, b in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(*a))
        t.SetEnd(V(*b))
        t.SetWidth(mm(width))
        t.SetLayer(layer)
        t.SetNet(n)
        t.SetLocked(True)
        board.Add(t)


def via(netname, x, y, d=0.6, drill=0.3):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(V(x, y))
    v.SetWidth(mm(d))
    v.SetDrill(mm(drill))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetLayerPair(F, B)
    v.SetNet(net(netname))
    v.SetLocked(True)
    board.Add(v)


def vias(netname, pts, d=0.6, drill=0.3):
    for x, y in pts:
        via(netname, x, y, d, drill)


def pad_via(netname, p, v, width=0.6, d=0.6, drill=0.3):
    """A via beside a pad, tied to it with a short top-layer track (GND vias
    need no track: the top pour reaches them)."""
    via(netname, *v, d=d, drill=drill)
    if netname != "GND":
        track(netname, F, width, [p, v])


def _outline(z, pts):
    ol = z.Outline()
    ol.NewOutline()
    for x, y in pts:
        ol.Append(mm(OX + x), mm(OY + y))


def zone(netname, layer, pts, priority=1, thermal=False, clearance=0.25, min_width=0.25, name=""):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(net(netname))
    _outline(z, pts)
    z.SetAssignedPriority(priority)
    z.SetLocalClearance(mm(clearance))
    z.SetMinThickness(mm(min_width))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL if thermal else pcbnew.ZONE_CONNECTION_FULL)
    z.SetThermalReliefGap(mm(0.3))
    z.SetThermalReliefSpokeWidth(mm(0.5))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    z.SetIsFilled(False)
    z.SetLocked(True)
    if name:
        z.SetZoneName(name)
    board.Add(z)
    return z


def keepout(pts, name):
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    ls = pcbnew.LSET()
    for layer in (F, IN1, IN2, B):
        ls.AddLayer(layer)
    z.SetLayerSet(ls)
    _outline(z, pts)
    z.SetDoNotAllowTracks(True)
    z.SetDoNotAllowVias(True)
    z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    z.SetZoneName(name)
    z.SetLocked(True)
    board.Add(z)


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# --- board-wide ------------------------------------------------------------------

def edge_keepouts():
    e = EDGE
    sx, sy = place.OUTLINE_SHIFT
    l, t, r, b = sx, sy, W + sx, H + sy
    keepout(rect(l - 1, t - 1, r + 1, t + e), "edge top")
    keepout(rect(l - 1, b - e, r + 1, b + 1), "edge bottom")
    keepout(rect(l - 1, t - 1, l + e, b + 1), "edge left")
    keepout(rect(r - e, t - 1, r + 1, b + 1), "edge right")
    # the autorouter does not keep its distance from inner cut-outs: a 0.5 mm
    # band around the display-cable slot and along the notch
    g = 0.5
    for x0, y0, x1, y1 in place.cutouts():
        keepout(rect(x0 - g, y0 - g, x1 + g, y1 + g), "slot band")
    nx0, ny0, nx1, ny1 = place.pi_rect(place.PORT_BLOCK)
    keepout(rect(-1, ny0 - g, nx1 + g, ny1 + g), "notch band")


# In2 split. +12V_PROT: a band under the protection and the harness side,
# the whole amp/filter block, and a leg down to the buck input. +5V: the
# rest, from the buck output to the Pi's 5V pins, the LDO, clocks and fans.
P12_IN2 = [(62.0, 9.5), (100.0, 9.5), (100.0, 13.5), (162.0, 13.5), (162.0, 84.0), (121.8, 84.0), (121.8, 31.0),
           (88.0, 31.0), (88.0, 68.0), (62.0, 68.0)]
P5_IN2 = [(89.5, 32.5), (120.3, 32.5), (120.3, 85.5), (162.0, 85.5), (162.0, 100.0),
          (3.0, 100.0), (3.0, 69.5), (89.5, 69.5)]


def planes():
    zone("GND", IN1, rect(0, 0, W, H), priority=0, thermal=True, name="GND plane")
    zone("+12V_PROT", IN2, P12_IN2, priority=1, thermal=True, name="+12V_PROT plane")
    zone("+5V", IN2, P5_IN2, priority=1, thermal=True, name="+5V plane")
    # whatever In2 area neither rail uses (the RTC corner) is GND
    zone("GND", IN2, rect(0, 0, W, H), priority=0, thermal=True, name="GND in2 rest")


def outer_gnd(b=None):
    """Lowest-priority GND pour on both outer layers. Added after the
    autorouter (autoroute.py import): exported to it, these would look like
    solid copper covering both routing layers."""
    global board
    if b is not None:
        board = b
    zone("GND", F, rect(0, 0, W, H), priority=0, thermal=True, clearance=0.3, min_width=0.3, name="GND top")
    zone("GND", B, rect(0, 0, W, H), priority=0, thermal=True, clearance=0.3, min_width=0.3, name="GND bottom")


# --- input protection --------------------------------------------------------------

def protection():
    """Battery in at J1 1/11 -> TVS D1 -> C1 -> Q1 source; Q1/Q2 drains share
    VMID; Q2 source -> C2 -> +12V_PROT plane through a via row."""
    bat = [(89.8, 19.9), (93.0, 19.9), (93.0, 15.8), (99.6, 15.8), (99.6, 5.6), (105.4, 5.6),
           (105.4, 19.3), (98.6, 19.3), (98.6, 24.0), (89.8, 24.0)]
    zone("/+12V_BATT", F, bat, priority=5, name="battery in")
    zone("/+12V_BATT", B, rect(99.6, 5.6, 105.4, 12.0), priority=5, name="battery pins bottom")
    zone("/VMID", F, rect(78.0, 18.4, 89.2, 23.6), priority=5, name="VMID")
    zone("+12V_PROT", F, [(69.8, 18.3), (77.3, 18.3), (77.3, 22.2), (74.8, 22.2), (74.8, 23.4), (69.8, 23.4)],
         priority=5, name="protected out")
    vias("+12V_PROT", [(70.6, 19.1), (70.6, 20.4), (70.6, 21.7), (70.6, 23.0), (71.9, 23.0), (73.2, 23.0)],
         d=0.8, drill=0.4)
    # GND for the TVS and caps
    x, y = pad("D1", 1)
    vias("GND", [(x - 0.7, y + 2.1), (x + 0.7, y + 2.1)], d=0.8, drill=0.4)
    for ref in ("C1", "C2"):
        x, y = pad(ref, 2)
        via("GND", x, y - 1.2)


# --- buck -------------------------------------------------------------------------------

SW_TAP = (83.6, 60.0)


def buck():
    """LM61460: VIN/PGND pairs above and below the SW pin, each with its own
    100 nF + 10 uF (SNVSB70F 11.1); SW -> L1 as a short wide pour; output
    caps pour into the +5V plane."""
    u = "U5"
    vin = sorted(pads_on(u, "+12V_PROT"), key=lambda p: p[2])      # 12 (top), 8 (bottom)
    sw = pads_on(u, "SW_5V")[0]
    xv = vin[0][1]
    top, bot = vin[0][2], vin[1][2]
    # VIN columns
    # the columns stop short of the RBOOT/EN pins beside the VIN pins
    zone("+12V_PROT", F, rect(xv - 0.45, top - 5.3, xv + 0.48, top + 0.55), priority=6, name="buck vin top")
    zone("+12V_PROT", F, rect(xv - 0.45, bot - 0.55, xv + 0.48, bot + 5.3), priority=6, name="buck vin bottom")
    vias("+12V_PROT", [(xv - 0.8, top - 3.1), (xv + 0.1, top - 3.1), (xv - 0.8, bot + 3.05), (xv + 0.1, bot + 3.05)])
    # PGND columns and SW
    xg = xv + 1.35
    zone("GND", F, rect(xg - 0.55, top - 5.3, xg + 1.6, top + 0.55), priority=6, name="buck pgnd top")
    zone("GND", F, rect(xg - 0.55, bot - 0.55, xg + 1.6, bot + 5.3), priority=6, name="buck pgnd bottom")
    vias("GND", [(xg + 1.2, top - 1.4), (xg + 1.2, top - 3.0), (xg + 1.2, bot + 1.4), (xg + 1.2, bot + 3.0)])
    ly = pad("L1", 1)
    zone("/SW_5V", F, rect(sw[1] - 0.3, sw[2] - 0.62, ly[0] + 1.6, sw[2] + 0.62), priority=7, name="SW")
    # the boot cap's SW end lands here, mid-pour between the pin and L1
    via("/SW_5V", *SW_TAP)
    # output: L1 pad 2 -> C24/C25/C26 -> +5V plane
    l2 = pad("L1", 2)
    # notched bottom-right so C26's GND pad stays outside and gets its own via
    gx = pad("C26", 2)[0] - 0.7
    zone("+5V", F, [(l2[0] - 1.8, l2[1] - 2.4), (103.0, l2[1] - 2.4), (103.0, l2[1] + 2.0), (gx, l2[1] + 2.0),
                    (gx, l2[1] + 3.6), (l2[0] - 1.8, l2[1] + 3.6)], priority=6, name="buck out")
    vias("+5V", [(95.3, 62.9), (96.6, 62.9), (97.9, 62.9), (101.6, 61.2), (102.6, 61.2), (95.3, 61.6)],
         d=0.8, drill=0.4)
    for ref in ("C24", "C25"):
        x, y = pad(ref, 2)
        vias("GND", [(x - 0.8, y - 1.5), (x + 0.8, y - 1.5)])


# --- amplifier ---------------------------------------------------------------------------

CH_X = {}          # channel name -> coil column centre x


def amp_power():
    """PVDD: end groups (55/56, 29/30) pour to their caps on top; the centre
    pair (42/43) and the bottom pair (2/3) drop to the In2 plane through vias
    under the chip body. GND pins join the top pour under the body plus
    vias to In1."""
    u = "U7"
    top = {n: (x, y) for n, x, y in pads_on(u, "") if y < place.AMP_AT[1]}
    bot = {n: (x, y) for n, x, y in pads_on(u, "") if y > place.AMP_AT[1]}
    ty = next(iter(top.values()))[1]
    by = next(iter(bot.values()))[1]
    x55, x56 = top["55"][0], top["56"][0]
    x29, x30 = top["29"][0], top["30"][0]
    # left end: 55/56 + C29/C30
    zone("+12V_PROT", F, [(128.7, ty - 2.0), (133.9, ty - 2.0), (133.9, ty - 0.7), (x55 + 0.3, ty - 0.7),
                          (x55 + 0.3, ty + 0.7), (128.7, ty + 0.7)], priority=6, name="pvdd left")
    vias("+12V_PROT", [(128.9, ty + 0.2), (133.2, ty + 0.2)])
    # right end: 29/30 + C33/C34
    zone("+12V_PROT", F, [(x30 - 0.3, ty - 0.7), (152.1, ty - 0.7), (152.1, ty - 2.0), (157.3, ty - 2.0),
                          (157.3, ty + 0.7), (x30 - 0.3, ty + 0.7)], priority=6, name="pvdd right")
    vias("+12V_PROT", [(152.8, ty + 0.2), (157.1, ty + 0.2)])
    # centre pair and bottom pair: under-body pours with via columns
    xc = (top["42"][0] + top["43"][0]) / 2
    zone("+12V_PROT", F, rect(xc - 0.6, ty - 0.6, xc + 0.6, ty + 4.4), priority=6, name="pvdd centre")
    vias("+12V_PROT", [(xc, ty + 1.35), (xc, ty + 2.35), (xc, ty + 3.35)])
    xb = (bot["2"][0] + bot["3"][0]) / 2
    zone("+12V_PROT", F, rect(xb - 0.6, by - 4.4, xb + 0.6, by + 0.6), priority=6, name="pvdd bottom")
    vias("+12V_PROT", [(xb, by - 1.35), (xb, by - 2.35), (xb, by - 3.35)])
    # GND under the body (the outer GND pour fills in around these)
    gx = [top[n][0] for n in ("33", "36", "39", "46", "49", "52")]
    vias("GND", [(x, ty + 1.35) for x in gx])
    bx = [bot[n][0] for n in ("1", "11", "28")] + [(bot["17"][0] + bot["18"][0]) / 2,
                                                   (bot["22"][0] + bot["23"][0]) / 2]
    vias("GND", [(x, by - 1.35) for x in bx])
    vias("GND", [(x, place.AMP_AT[1]) for x in (137.0, 139.5, 146.5, 149.0)])
    # decoupling caps: +12V_PROT and GND vias beside each
    c31 = [r for r, f in FPS.items() if f.GetValue() == "100nF" and abs(pad(r, 1)[0] - 142.5) < 0.3 and
           abs(pad(r, 1)[1] - 57.4) < 1.0][0]
    x, y = pad(c31, 1)
    pad_via("+12V_PROT", (x, y), (x, y + 1.25))
    x, y = pad(c31, 2)
    via("GND", x, y - 1.25)
    for ref in (r for r, f in FPS.items() if f.GetFieldText("Section") == "amp"):
        f = FPS[ref]
        if f.GetValue() not in ("10uF", "100nF", "470uF") or ref == c31:
            continue
        for p in f.Pads():
            x, y = pad(ref, p.GetNumber())
            n = p.GetNetname()
            if n not in ("GND", "+12V_PROT"):
                continue
            # step away from the chip / heatsink side
            if f.GetValue() == "470uF":
                for vx in (x - 1.4, x, x + 1.4):
                    for vy in (y - 2.0, y + 2.0):
                        pad_via(n, (vx, y), (vx, vy), width=1.0, d=0.8, drill=0.4)
            else:
                v = (x, y - 1.3) if y < place.AMP_AT[1] else (x, y + 1.3)
                # a via that would land on the cap's other pad is not needed:
                # those caps sit in the PVDD pours, which have their own vias
                others = [pad(ref, q.GetNumber()) for q in f.Pads() if q.GetNumber() != p.GetNumber()]
                if all(abs(v[0] - ox) + abs(v[1] - oy) > 1.0 for ox, oy in others):
                    pad_via(n, (x, y), v)


def amp_outputs():
    """Per channel: OUT_P -> boot cap -> P coil on top; OUT_M -> boot cap ->
    two vias -> bottom layer -> two vias -> M coil. The P escape runs up
    between the M caps of neighbouring channels."""
    u = "U7"
    for ch in ("FR", "FL", "RR", "RL"):
        (_, opx, opy), = pads_on(u, f"AMP_{ch}+")
        (_, omx, omy), = pads_on(u, f"AMP_{ch}-")
        cp = ref_of("1uF", f"AMP_{ch}+")            # P boot cap
        cm = ref_of("1uF", f"AMP_{ch}-")            # M boot cap
        lp = ref_of("3.3uH", f"AMP_{ch}+")
        lm = ref_of("3.3uH", f"AMP_{ch}-")
        pp = [pad(cp, n) for n in ("1", "2") if f"AMP_{ch}" in pad_net(cp, n)][0]
        pm = [pad(cm, n) for n in ("1", "2") if f"AMP_{ch}" in pad_net(cm, n)][0]
        x0 = pad(lp, 1)[0]
        CH_X[ch] = x0
        lp1 = pad(lp, 1)
        lm1 = pad(lm, 1)
        # P: pin -> cap pad (narrow between pins), escape up-left, then wide
        track(f"/AMP_{ch}+", F, 0.3, [(opx, opy), (opx, opy - 0.9), pp])
        ex = pp[0] - 0.785
        track(f"/AMP_{ch}+", F, 0.4, [pp, (ex, pp[1] - 1.0), (ex, pp[1] - 2.2)])
        yd = 57.5 if x0 < ex else 58.0
        dx = abs(x0 - ex)
        # 45 degrees into the coil column, then straight into pad 1
        track(f"/AMP_{ch}+", F, 0.8, [(ex, pp[1] - 2.2), (ex, yd), (x0, yd - dx), (x0, lp1[1])])
        # M: pin -> cap pad, then vias above the cap
        track(f"/AMP_{ch}-", F, 0.3, [(omx, omy), (omx, pm[1] + 0.7), pm])
        v1, v2 = (pm[0], pm[1] - 1.35), (pm[0], pm[1] - 2.55)
        track(f"/AMP_{ch}-", F, 0.8, [pm, v2])
        vias(f"/AMP_{ch}-", [v1, v2], d=0.8, drill=0.4)
        track(f"/AMP_{ch}-", B, 1.0, [v1, v2])
        # bottom layer to the M coil, landing right of the column centre
        tx = x0 + 2.0
        yv = lm1[1] + 2.7
        dx = abs(tx - v2[0])
        track(f"/AMP_{ch}-", B, 1.0, [v2, (v2[0], v2[1] - 1.0), (tx, v2[1] - 1.0 - dx), (tx, yv)])
        track(f"/AMP_{ch}-", B, 1.0, [(x0 + 0.8, yv), (x0 + 2.0, yv)])
        vias(f"/AMP_{ch}-", [(x0 + 0.8, yv), (x0 + 2.0, yv)], d=0.8, drill=0.4)
        track(f"/AMP_{ch}-", F, 1.0, [(x0 + 2.0, yv), (x0 + 0.8, yv), (x0 + 0.8, lm1[1])])


# Speaker lanes: nested so no two tracks cross. Minus legs on top, plus legs
# on the bottom, each channel on its own lane y, turning up into J1.
LANE_Y = {"FR": 22.5, "FL": 20.5, "RR": 18.5, "RL": 16.5}


def _lane(netname, layer, x_from, y_from, lane_y, x_to, y_pin, jog=0.0, ch=1.5):
    """Up from (x_from, y_from) to the lane, left to x_to, up to the pin
    (with a final 45-degree jog of `jog` mm onto the pin's x)."""
    pts = [(x_from, y_from), (x_from, lane_y + ch), (x_from - ch, lane_y),
           (x_to + ch, lane_y), (x_to, lane_y - ch)]
    if jog:
        pts += [(x_to, y_pin + jog), (x_to - jog, y_pin)]
    else:
        pts += [(x_to, y_pin)]
    track(netname, layer, 1.0, pts)


def speakers():
    for ch in ("FR", "FL", "RR", "RL"):
        x0 = CH_X[ch]
        # minus leg (top): M coil pad 2 -> 1 uF -> lane -> J1 row B
        lm = ref_of("3.3uH", f"AMP_{ch}-")
        c1 = ref_of("1uF", f"SPK_{ch}-")
        cx, cy = [pad(c1, n) for n in ("1", "2") if f"SPK_{ch}" in pad_net(c1, n)][0]
        pin = [pad("J1", n) for n in range(11, 21) if f"SPK_{ch}-" in pad_net("J1", n)][0]
        track(f"/SPK_{ch}-", F, 1.0, [(cx, pad(lm, 2)[1]), (cx, cy)])
        _lane(f"/SPK_{ch}-", F, cx, cy, LANE_Y[ch], pin[0], pin[1])
        # plus leg: P coil pad 2 -> 1 uF -> two vias -> bottom lane -> J1 row A,
        # passing between the row B pins
        lp = ref_of("3.3uH", f"AMP_{ch}+")
        c1 = ref_of("1uF", f"SPK_{ch}+")
        cx, cy = [pad(c1, n) for n in ("1", "2") if f"SPK_{ch}" in pad_net(c1, n)][0]
        pin = [pad("J1", n) for n in range(1, 11) if f"SPK_{ch}+" in pad_net("J1", n)][0]
        yv = cy - 2.5
        vx = x0 - 1.9
        track(f"/SPK_{ch}+", F, 1.0, [(cx, pad(lp, 2)[1]), (cx, cy), (cx, yv + 0.65), (cx - 0.65, yv)])
        track(f"/SPK_{ch}+", F, 1.0, [(x0 - 1.3, yv), (x0 - 2.5, yv)])
        vias(f"/SPK_{ch}+", [(x0 - 1.3, yv), (x0 - 2.5, yv)], d=0.8, drill=0.4)
        track(f"/SPK_{ch}+", B, 1.0, [(x0 - 1.3, yv), (x0 - 2.5, yv)])
        _lane(f"/SPK_{ch}+", B, vx, yv, LANE_Y[ch], pin[0] + 1.5, pin[1], jog=1.5)
        # 1 nF snubber pads to their coil pad, both legs
        for pol in "+-":
            c = ref_of("1nF", f"SPK_{ch}{pol}")
            nx, ny = [pad(c, n) for n in ("1", "2") if f"SPK_{ch}" in pad_net(c, n)][0]
            track(f"/SPK_{ch}{pol}", F, 0.3, [(nx, ny), (nx, ny + 0.8), (x0 + 1.6, ny + 2.0)])
        # filter cap grounds: 1 uF beside its GND pad (the lanes run above it),
        # 1 nF above its GND pad (away from the coil)
        for ref in (ref_of("1uF", f"SPK_{ch}+"), ref_of("1uF", f"SPK_{ch}-")):
            gx, gy = [pad(ref, n) for n in ("1", "2") if pad_net(ref, n) == "GND"][0]
            via("GND", gx - 1.0, gy)
        for ref in (ref_of("1nF", f"SPK_{ch}+"), ref_of("1nF", f"SPK_{ch}-")):
            gx, gy = [pad(ref, n) for n in ("1", "2") if pad_net(ref, n) == "GND"][0]
            via("GND", gx - 0.3, gy - 1.2)


def pi_power():
    """J2 pins 2/4 feed the Pi and, through its pogo pins, the display
    (~3 A): a solid top pour around both pins with a via row to the +5V
    plane, rather than thermal spokes into it."""
    (x2, y2), (x4, y4) = pad("J2", 2), pad("J2", 4)
    x0, x1 = min(x2, x4) - 1.2, max(x2, x4) + 1.2
    zone("+5V", F, rect(x0, y2 - 1.1, x1, y2 + 2.6), priority=6, name="pi 5v")
    vias("+5V", [(x, y2 + 1.95) for x in (x0 + 0.6, (x0 + x1) / 2, x1 - 0.6)], d=0.8, drill=0.4)


def u1_fanout():
    """LM74800 output-side pins (top to bottom GND, HGATE, OUT, VS, CAP, C)
    at 0.5 mm: HGATE and OUT peel off at 45 degrees to their own vias (GND
    is left to the fanout), VS runs straight out to C5 and C4, CAP to C5's
    other pad, C drops into the VMID pour."""
    w = 0.25
    p = {n: pad("U1", n) for n in ("8", "9", "10", "11", "12")}
    xo = p["8"][0] - 0.44                       # outer end of the pads
    # HGATE: out, 45 degrees up, via; bottom layer to Q2's gate; up again,
    # to the gate pad and on to R1
    y8 = p["8"][1]
    hv = (79.6, y8 - 1.0)
    track("/HGATE", F, w, [p["8"], (80.6, y8), (hv[0] + 0.25, hv[1] + 0.25), hv])
    via("/HGATE", *hv)
    g = pad("Q2", 4)
    gv = (g[0], g[1] + 1.4)
    track("/HGATE", B, w, [hv, (hv[0], 21.0), gv])
    via("/HGATE", *gv)
    r1 = pad("R1", 1)
    track("/HGATE", F, w, [g, gv, (r1[0], gv[1] + (gv[0] - r1[0])), r1])
    # OUT (+12V_PROT sense): out, 45 degrees up, via into the In2 plane
    y9 = p["9"][1]
    ov = (78.1, y9 - 1.0)
    track("+12V_PROT", F, w, [p["9"], (79.1, y9), (ov[0] + 0.25, ov[1] + 0.25), ov])
    via("+12V_PROT", *ov)
    # VS: straight out through C5's VS pad to C4, then down into the VMID pour
    c5v, c5c = pad("C5", 1), pad("C5", 2)
    c4v = pad("C4", 1)
    track("/VMID", F, w, [p["10"], c5v, c4v])
    track("/VMID", F, 0.4, [c4v, (c4v[0], 17.0), (c4v[0] + 0.95, 17.95), (78.8, 17.95), (78.8, 18.8)])
    # CAP: out and down to C5's other pad
    y11 = p["11"][1]
    track("Net-(U1-CAP)", F, w, [p["11"], (79.3, y11), (c5c[0] + 0.45, c5c[1] - 0.2), c5c])
    # C: out a little, then straight down into the VMID pour
    x12 = xo - 0.35
    y12 = p["12"][1]
    track("/VMID", F, w, [p["12"], (x12, y12), (x12, y12 + 0.6)])
    track("/VMID", F, 0.4, [(x12, y12 + 0.6), (x12, 18.8)])


# --- GND fanout --------------------------------------------------------------------------

CLR = 0.2


def _free(pt, r, skip_pad=None, layers=(F,)):
    """True if a circle of radius r (mm) at pt clears every pad, track, via,
    foreign pour, keepout and board edge by CLR."""
    P = V(*pt)
    reach = mm(r + CLR)
    for ref, fp in FPS.items():
        for p in fp.Pads():
            if (ref, p.GetNumber()) == skip_pad:
                continue
            for layer in (F, B):
                if p.IsOnLayer(layer) and p.GetEffectivePolygon(layer, pcbnew.ERROR_INSIDE).Collide(P, reach):
                    return False
            if p.GetDrillSizeX() and (p.GetPosition() - P).EuclideanNorm() < mm(pcbnew.ToMM(p.GetDrillSizeX()) / 2 + r + 0.3):
                return False
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            if (t.GetPosition() - P).EuclideanNorm() < mm(r + CLR) + t.GetWidth(F) // 2:
                return False
        elif t.GetLayer() in layers and t.HitTest(P, reach):
            return False
    for z in board.Zones():
        if z.GetIsRuleArea():
            if z.Outline().Collide(P, reach):
                return False
        elif z.GetNetname() != "GND" and z.GetLayer() in (F, B) and z.Outline().Collide(P, reach):
            return False
    for dr in board.GetDrawings():
        if dr.GetLayer() == pcbnew.Edge_Cuts and dr.HitTest(P, mm(r + 0.5)):
            return False
    return True


def _inside(pt, poly, margin=0.8):
    """Point in polygon (board mm), at least `margin` from its edges."""
    s = pcbnew.SHAPE_POLY_SET()
    s.NewOutline()
    for x, y in poly:
        s.Append(mm(OX + x), mm(OY + y))
    P = V(*pt)
    chain = s.Outline(0)
    k = chain.PointCount()
    return s.Contains(P) and all(pcbnew.SEG(chain.CPoint(i), chain.CPoint((i + 1) % k)).Distance(P) >= mm(margin)
                                 for i in range(k))


REGION = {"+5V": P5_IN2, "+12V_PROT": P12_IN2}


def gnd_fanout(netname="GND"):
    """Every SMD pad of `netname` gets its own via to its plane (GND: In1;
    +5V / +12V_PROT: their In2 region, only where the via lands inside it),
    beside the pad and away from its part's centre where possible, unless a
    via or pour of that net already serves it. What is left for the
    autorouter is signals."""
    import math
    region = REGION.get(netname)
    n = 0
    for ref, fp in FPS.items():
        c = fp.GetPosition()
        cx, cy = pcbnew.ToMM(c.x) - OX, pcbnew.ToMM(c.y) - OY
        for p in fp.Pads():
            if p.GetNetname() != netname or p.GetDrillSizeX() or not p.IsOnLayer(F):
                continue
            px, py = pad(ref, p.GetNumber())
            bb = p.GetBoundingBox()
            hw, hh = pcbnew.ToMM(bb.GetWidth()) / 2, pcbnew.ToMM(bb.GetHeight()) / 2
            P = V(px, py)
            if any(z.GetNetname() == netname and z.GetLayer() == F and z.GetAssignedPriority() > 0 and
                   z.Outline().Contains(P) for z in board.Zones()):
                continue
            if region and not _inside((px, py), region, 0.0):
                continue
            near = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() == netname and
                    (t.GetPosition() - P).EuclideanNorm() < mm(max(hw, hh) + 0.9)]
            if near:
                continue
            away = math.atan2(py - cy, px - cx) if (px, py) != (cx, cy) else 0.0
            dirs = sorted(range(8), key=lambda k: abs(math.remainder(k * math.pi / 4 - away, 2 * math.pi)))
            done = False
            for extra in (0.3, 0.55, 0.9, 1.4):
                for k in dirs:
                    a = k * math.pi / 4
                    ux, uy = math.cos(a), math.sin(a)
                    # distance from the pad centre to its edge along this direction
                    edge = min(hw / abs(ux) if abs(ux) > 1e-6 else 1e9, hh / abs(uy) if abs(uy) > 1e-6 else 1e9)
                    d = edge + 0.3 + extra
                    v = (px + ux * d, py + uy * d)
                    if region and not _inside(v, region):
                        continue
                    if not _free(v, 0.3, skip_pad=(ref, p.GetNumber()), layers=(F, B)):
                        continue
                    # the stub from the pad edge to the via must clear too
                    steps = [(px + ux * t, py + uy * t) for t in [edge + 0.1 + i * 0.15 for i in range(int((d - edge) / 0.15))]]
                    if not all(_free(q, 0.15, skip_pad=(ref, p.GetNumber())) for q in steps):
                        continue
                    via(netname, *v)
                    track(netname, F, 0.3, [(px, py), v])
                    n += 1
                    done = True
                    break
                if done:
                    break
            if not done:
                print(f"fanout: no room for a {netname} via at {ref} pad {p.GetNumber()}")
    print(f"fanout: {n} {netname} vias")


# --- the corners Freerouting cannot finish --------------------------------------------

# Nets it left open, run after run: sense pins in the protection block, the
# fan lines through the bottom-left strip, the RTC interrupt and the first
# wheel input. Routed here first so the autorouter works around them.
# Whole nets, or (net, (ref, pad), (ref, pad)) for a single link. The LM74800
# (U1) goes first and whole: its 0.5 mm pins box each other in.
MAZE_NETS = [("+3V3", ("R36", "1"), ("U8", "4")),      # fan tach pull-ups by the Pi header: +3V3 has
             ("+3V3", ("R34", "1"), ("R36", "1")),     # no plane, so their feed is reserved first
             "Net-(U1-SW)", "/OV_SET", "/DGATE", "/+12V_BATT",
             ("/SW_5V", ("C22", "2"), SW_TAP), ("+5V", ("U5", "1"), ("U6", "3")),
             "/FAN1_PWM", "/FAN2_PWM", "/FAN1_TACH", "/~{RTC_INT}", "/SWC1_ADC"]


def maze_nets():
    import math
    import maze
    for item in MAZE_NETS:
        if isinstance(item, tuple):
            netname, u, v = item
            ends = []
            for end in (u, v):
                if isinstance(end[0], float):          # a point (a via placed above)
                    ends.append(("via", "", end, (F, B)))
                    continue
                ref, num = end
                p = next(q for q in FPS[ref].Pads() if q.GetNumber() == num)
                ls = (F, B) if p.GetDrillSizeX() else ((F,) if p.IsOnLayer(F) else (B,))
                ends.append((ref, num, pad(ref, num), ls))
            _maze_link(netname, *ends)
            continue
        netname = item
        pads = []
        for ref, fp in FPS.items():
            for p in fp.Pads():
                if p.GetNetname() == netname:
                    ls = (F, B) if p.GetDrillSizeX() else ((F,) if p.IsOnLayer(F) else (B,))
                    # pads already inside a pour of this net are served by it
                    P = p.GetPosition()
                    if any(z.GetNetname() == netname and z.GetAssignedPriority() > 0 and z.Outline().Contains(P)
                           for z in board.Zones()):
                        ls = ("pour",) + ls
                    pads.append((ref, p.GetNumber(), pad(ref, p.GetNumber()), ls))
        # the pour counts as one node: link only one of its pads
        poured = [q for q in pads if q[3][0] == "pour"]
        nodes = [q for q in pads if q[3][0] != "pour"] + poured[:1]
        nodes = [(r, n, xy, tuple(l for l in ls if l != "pour")) for r, n, xy, ls in nodes]
        # Prim's MST over pad distance
        done, todo, edges = [nodes[0]], nodes[1:], []
        while todo:
            best = min(((math.dist(u[2], v[2]), u, v) for u in done for v in todo), key=lambda e: e[0])
            edges.append(best[1:])
            done.append(best[2])
            todo.remove(best[2])
        for u, v in edges:
            _maze_link(netname, u, v)


def _maze_link(netname, u, v, w=0.25):
    import maze
    path = maze.route(board, netname, u[2], v[2], OX, OY, width=w, start_layers=u[3], end_layers=v[3])
    if path is None:
        print(f"maze: {netname} {u[0]}.{u[1]} -> {v[0]}.{v[1]} not found", flush=True)
        return
    path = maze.simplify(path)
    pts = [(u[2][0], u[2][1], path[0][2])] + path + [(v[2][0], v[2][1], path[-1][2])]
    for (xa, ya, la), (xb, yb, lb) in zip(pts, pts[1:]):
        if la != lb:
            # two links meeting at a pad can both change layer on one spot
            P = V(xa, ya)
            if not any(t.GetClass() == "PCB_VIA" and t.GetNetname() == netname and
                       (t.GetPosition() - P).EuclideanNorm() < mm(0.7) for t in board.GetTracks()):
                via(netname, xa, ya)
        elif (xa, ya) != (xb, yb):
            track(netname, la, w, [(xa, ya), (xb, yb)])
    print(f"maze: {netname} {u[0]}.{u[1]} -> {v[0]}.{v[1]}: {len(path)} points", flush=True)


def clear(b):
    for t in list(b.GetTracks()):
        b.Remove(t)
    for z in list(b.Zones()):
        b.Remove(z)


def main():
    global board
    board = pcbnew.LoadBoard(PCB)
    FPS.update({f.GetReference(): f for f in board.GetFootprints()})
    clear(board)
    edge_keepouts()
    planes()
    protection()
    buck()
    amp_power()
    amp_outputs()
    speakers()
    pi_power()
    u1_fanout()
    for n in ("GND", "+12V_PROT", "+5V"):
        gnd_fanout(n)
    maze_nets()
    board.BuildConnectivity()
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    board.Save(PCB)
    print(f"route: {len(board.GetTracks())} tracks/vias, {len(board.Zones())} zones")


if __name__ == "__main__":
    main()
