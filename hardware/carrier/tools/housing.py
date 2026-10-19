#!/usr/bin/env python3
"""3D-printed PETG housing: a shell that screws to the screen's four corner
pillars and surrounds the Pi + carrier board, and a lid that carries the two
Noctua NF-A4x10 fans (both blowing in) and closes the back.

    .venv/bin/python tools/housing.py
        ->  mech/housing_shell.step/.stl, mech/housing_lid.step/.stl,
            mech/housing_fit_ring.stl, then a clearance check (exit 1 on a clash)

Frame: the same as tools/assembly.py (x right, y up, z from the glass front
toward the firewall, display top-left corner seen from the back at x 0, y 0).
Everything is drawn in board coordinates (place.py: mm, y down) and mirrored
into that frame at the end. The STEP files are in the assembly frame (for
importing into other CAD); the STL files are turned to their print
orientation:

  shell     screen side down (the skirt's rim on the bed), supports under the
            four corner tabs only
  lid       outer face down, no supports
  fit ring  the bottom 17 mm of the shell: skirt + corner tabs, to check the
            fit on the screen before printing the rest

Heights (z, mm from the glass front):
  0 .. 8.25     display module (Hosyond drawing)
  8.25 .. 12.25 the module's rear parts and its M2.5 pillars, corner and Pi
                (drawing: 12.25 total)
  12.25         Pi underside, on the pillars; carrier underside 13 mm above
                the Pi's top (11 mm HAT standoffs + 1 mm nylon spacer + 1 mm
                washer), see assembly.Z_BOARD
  ~41           tallest board parts: stock heatsink, 470 uF cap, J1 plug
  44 .. 54      fans, hanging under the lid
  54 .. 56.4    lid
"""
import math
import os
import re
import sys
import types

import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
sys.modules.setdefault("pcbnew", types.ModuleType("pcbnew"))   # place.py only needs it for placing
import assembly  # noqa: E402
import place  # noqa: E402

# ---- the stack (assembly.py owns these) ----
PILLAR_TOP = assembly.DISPLAY_T + assembly.PI_STANDOFF        # 12.25
BOARD_Z0 = assembly.Z_BOARD                                   # carrier underside, 26.85
BOARD_Z1 = BOARD_Z0 + assembly.BOARD_T                        # carrier top, 28.45
HEATSINK_TOP = BOARD_Z1 + assembly.AMP_PAD_Z + assembly.HS_TAPE + assembly.HS_H

# ---- outline (board coordinates, y down) ----
SX, SY = place.OUTLINE_SHIFT
W, H = 164.9, 102.0                       # display = board outline
CLR = 0.5                                 # display / board edge to the inner wall
WALL = 2.4
CORNER_R = 3.0                            # outside corners
# the dash opening is 6.60 mm wider than the plain shell (fit ring): the
# driver side wall (board x high, the mic jack side) takes all of it
SIDE_FILL = 6.6
IX0, IY0 = SX - CLR, SY - CLR             # inner wall faces
IX1, IY1 = SX + W + CLR, SY + H + CLR
OX0, OY0, OX1, OY1 = IX0 - WALL, IY0 - WALL, IX1 + WALL + SIDE_FILL, IY1 + WALL

SKIRT_Z = 0.0                             # shell's front rim: flush with the glass front (2.0 left the glass edge and FPC showing)
# shell's back rim = lid underside: 52 for the bare HAT stack, raised by the
# Pi spacer and board washer so fan 1 keeps its 3 mm over the heatsink
TOP_Z = 52.0 + assembly.PI_SPACER + assembly.BOARD_WASHER
LID_T = 2.4
LIP_H, LIP_W, LIP_CLR = 1.5, 1.6, 0.3     # lid's locating lip inside the shell rim

# ---- screen corner pillars: 154.9 x 92.0 mm, 5 mm in from each edge ----
PILLARS = [(SX + 5.0 + dx, SY + 5.0 + dy) for dx in (0.0, 154.9) for dy in (0.0, 92.0)]
TAB = 10.0                                # corner tab size, from the inner walls
TAB_T = 3.0
PILLAR_HOLE = 2.9                         # M2.5 clearance (M2.5 x 6 screws)

# ---- J1 harness plug support ----
LEDGE_X = (90.0, 145.0)                   # under the board's top edge, either side of J1
LEDGE_Y1 = 5.0                            # stops 1 mm short of J1's pin-1 row pads (y 7, d 1.9)
SUPPORT_GAP = 0.2                         # ledge / lid ribs to the board faces
RIBS_X = [(91.0, 96.0), (139.0, 144.0)]   # lid ribs pressing the board's top edge strip
RIB_Y1 = SY + 2.0                         # 2 mm edge strip (copper stays 2.5 mm from the edge)
J1_OPENING = (98.0, 1.0, 137.0, 18.0)     # lid cut-out the harness plug passes through

# ---- lid screws: M3 heat-set inserts in blocks on the top and bottom walls ----
# Kept off the corners: the pillar screws sit there and need a screwdriver
# straight down from the open back.
LID_BOSSES = [(25.0, "top"), (150.0, "top"), (60.0, "bottom"), (130.0, "bottom")]
BOSS_W, BOSS_D, BOSS_H = 8.0, 7.0, 8.0    # along the wall, into the box, tall
BOSS_INSET = 3.0                          # insert axis from the inner wall
INSERT_HOLE, INSERT_DEPTH = 4.0, 6.5      # M3 x 5.7 heat-set insert
LID_SCREW, CSK = 3.4, 6.6                 # M3 countersunk


# ---- bracket points for later dash mounting: outside pads, M3 heat-set ----
BRACKET_Y = (25.0, 77.0)
BRACKET_Z = 34.0
PAD_W, PAD_H, PAD_P = 10.0, 10.0, 4.5     # along the wall, tall, proud
PAD_HOLE_DEPTH = 6.0

# ---- fans: Noctua NF-A4x10 5V PWM, 40 x 40 x 10, holes 32 mm apart ----
FAN, FAN_T, FAN_HOLES = 40.0, 10.0, 32.0
FAN_SCREW = 3.4
GRILLE_D, GRILLE_SLOT, GRILLE_PITCH = 37.0, 3.0, 5.0
FAN1 = (place.AMP_AT[0] - 2.0, place.AMP_AT[1])   # over the heatsink (2 mm left: clears the lid lip)
FAN2 = (24.0, 60.0)                               # over the Pi's port notch
FAN_Z1 = TOP_Z
FAN_Z0 = FAN_Z1 - FAN_T

# ---- vents: vertical slots ----
SLOT_W, SLOT_PITCH = 2.0, 4.0
LOW_Z = (14.5, 22.5)                      # between the screen and the board (Pi level)
HIGH_Z = (29.0, 40.0)                     # above the board


def pcb_at(ref):
    """(x, y, rot) of a footprint in board coordinates, read from carrier.kicad_pcb."""
    s = open(os.path.join(ROOT, "carrier.kicad_pcb")).read()
    i = s.index(f'(property "Reference" "{ref}"')
    blk = s[s.rindex("(footprint ", 0, i):i]
    x, y, *r = re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", blk).groups()
    return float(x) - assembly.BOARD_ORIGIN[0], float(y) - assembly.BOARD_ORIGIN[1], float(r[0] or 0)


# J4 (PJ-320D, rot 180): the plug enters through the right wall. Body 5 mm
# tall (LCSC C431535), plug axis 2.5 mm above the board.
J4 = pcb_at("J4")
MIC_HOLE = (J4[1], BOARD_Z1 + 2.5)        # (y, z) on the right wall
MIC_D = 8.0
MIC_CB = 12.0

# USB jacks face the left wall across the port notch: an opening for the
# cables (CarPlay dongle). Pi frame y 22.4 .. 53.6 -> board y.
USB_Y = sorted(place.pi_to_board(87.1, y)[1] for y in (22.4, 53.6))
USB_OPENING = (USB_Y[0] - 1.0, 14.0, USB_Y[1] + 1.0, 31.0)   # y0, z0, y1, z1


def box(x0, y0, z0, x1, y1, z1):
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    z0, z1 = sorted((z0, z1))
    return cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))


def rounded_rect(x0, y0, x1, y1, z0, z1, r):
    return (cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False)
            .edges("|Z").fillet(r).translate((x0, y0, z0)))


def wedge(along, a0, a1, wall, d, z_top, inward):
    """45-degree support under a feature that sticks out of a wall.
    along: 'x' for the top/bottom walls, 'y' for the side walls; a0..a1 its
    extent along the wall; wall: the inner wall face; d: how far it reaches
    into the box; z_top: the underside it holds up; inward: +1 or -1."""
    pts = [(0, z_top), (d, z_top), (0, z_top - d)]
    s = inward
    # each plane's local y must come out as +z: yDir = normal x xDir
    if along == "x":
        pl = cq.Plane(origin=(a0 if s > 0 else a1, wall, 0), xDir=(0, s, 0), normal=(s, 0, 0))
    else:
        pl = cq.Plane(origin=(wall, a1 if s > 0 else a0, 0), xDir=(s, 0, 0), normal=(0, -s, 0))
    return cq.Workplane(pl).polyline(pts).close().extrude(a1 - a0)


def lid_boss_xy(x, side):
    """Insert axis of a lid boss (board coordinates)."""
    return (x, IY0 + BOSS_INSET) if side == "top" else (x, IY1 - BOSS_INSET)


def slots(along, a0, a1, wall0, wall1, z0, z1, keep_out=()):
    """Vertical slots through a wall, every SLOT_PITCH from a0 to a1,
    skipping any slot within keep_out ranges."""
    out = []
    n = int((a1 - a0 - SLOT_W) // SLOT_PITCH) + 1
    start = a0 + (a1 - a0 - SLOT_W - (n - 1) * SLOT_PITCH) / 2
    for i in range(n):
        s0 = start + i * SLOT_PITCH
        if any(s0 + SLOT_W > k0 and s0 < k1 for k0, k1 in keep_out):
            continue
        if along == "x":
            out.append(box(s0, wall0, z0, s0 + SLOT_W, wall1, z1))
        else:
            out.append(box(wall0, s0, z0, wall1, s0 + SLOT_W, z1))
    return out


def vents():
    """All vent slots, as (wall, solid) pairs."""
    bosses_x = {side: [(x - BOSS_W / 2 - 3, x + BOSS_W / 2 + 3) for x, s in LID_BOSSES if s == side]
                for side in ("top", "bottom")}
    corners_y = [(IY0, IY0 + TAB + 4), (IY1 - TAB - 4, IY1)]
    pads = [(y - PAD_W / 2 - 2, y + PAD_W / 2 + 2) for y in BRACKET_Y]
    mic = [(MIC_HOLE[0] - MIC_D / 2 - 2, MIC_HOLE[0] + MIC_D / 2 + 2)]
    e = 0.1
    v = []
    # Pi level: fan 2 pushes air down the port notch, under the board, and out here
    v += slots("x", 15.0, 88.0, OY0 - e, IY0 + e, *LOW_Z)                        # top (ledge from 90)
    v += slots("x", 15.0, 147.0, IY1 - e, OY1 + e, *LOW_Z)                       # bottom
    v += slots("y", IY0, IY1, IX1 - e, OX1 + e, *LOW_Z, keep_out=corners_y + pads)  # right
    # above the board: fan 1's air off the heatsink
    v += slots("y", IY0, IY1, IX1 - e, OX1 + e, *HIGH_Z, keep_out=corners_y + pads + mic)  # right
    v += slots("x", 95.0, 146.0, IY1 - e, OY1 + e, *HIGH_Z, keep_out=bosses_x["bottom"])  # bottom
    v += slots("x", 35.0, 88.0, OY0 - e, IY0 + e, *HIGH_Z, keep_out=bosses_x["top"])     # top, clear of J1
    return v


def shell():
    body = rounded_rect(OX0, OY0, OX1, OY1, SKIRT_Z, TOP_Z, CORNER_R)
    body = body.cut(box(IX0, IY0, SKIRT_Z - 1, IX1, IY1, TOP_Z + 1))

    # corner tabs on the screen's pillars. Nothing can go under them (the
    # module's rear parts reach the pillar tops), so they are corner
    # overhangs held by two walls: print with supports under the four tabs.
    for px, py in PILLARS:
        left, top = px < W / 2, py < H / 2
        x0, x1 = (IX0, IX0 + TAB) if left else (IX1 - TAB, IX1)
        y0, y1 = (IY0, IY0 + TAB) if top else (IY1 - TAB, IY1)
        tab = box(x0, y0, PILLAR_TOP, x1, y1, PILLAR_TOP + TAB_T)
        tab = tab.cut(cq.Workplane("XY").workplane(offset=PILLAR_TOP - 3).center(px, py)
                      .circle(PILLAR_HOLE / 2).extrude(TAB_T + 6))
        body = body.union(tab)

    # J1 ledge: holds the board's top edge up when the harness is pushed in
    lz1 = BOARD_Z0 - SUPPORT_GAP
    d = LEDGE_Y1 - IY0
    body = body.union(box(LEDGE_X[0], IY0, lz1 - 2.0, LEDGE_X[1], LEDGE_Y1, lz1))
    body = body.union(wedge("x", *LEDGE_X, IY0, d, lz1 - 2.0, 1))

    # lid screw blocks (M3 heat-set from the back), 45-degree support under each
    for x, side in LID_BOSSES:
        inward = 1 if side == "top" else -1
        wall = IY0 if side == "top" else IY1
        z0 = TOP_Z - BOSS_H
        blk = box(x - BOSS_W / 2, wall, z0, x + BOSS_W / 2, wall + inward * BOSS_D, TOP_Z)
        blk = blk.union(wedge("x", x - BOSS_W / 2, x + BOSS_W / 2, wall, BOSS_D, z0, inward))
        hx, hy = lid_boss_xy(x, side)
        blk = blk.cut(cq.Workplane("XY").workplane(offset=TOP_Z - INSERT_DEPTH).center(hx, hy)
                      .circle(INSERT_HOLE / 2).extrude(INSERT_DEPTH + 1))
        body = body.union(blk)

    # bracket pads outside the side walls, 45-degree support under each
    for y in BRACKET_Y:
        for wall, out in ((OX0, -1), (OX1, 1)):
            z0 = BRACKET_Z - PAD_H / 2
            pad = box(wall, y - PAD_W / 2, z0, wall + out * PAD_P, y + PAD_W / 2, z0 + PAD_H)
            pad = pad.union(wedge("y", y - PAD_W / 2, y + PAD_W / 2, wall, PAD_P, z0, out))
            hole = (cq.Workplane("YZ").workplane(offset=wall + out * (PAD_P + 0.1))
                    .center(y, BRACKET_Z).circle(INSERT_HOLE / 2).extrude(-out * (PAD_HOLE_DEPTH + 0.1)))
            body = body.union(pad).cut(hole)

    # openings
    for v in vents():
        body = body.cut(v)
    y0, z0, y1, z1 = USB_OPENING
    body = body.cut(box(OX0 - 0.1, y0, z0, IX0 + 0.1, y1, z1))
    body = body.cut(cq.Workplane("YZ").workplane(offset=IX1 - 0.1).center(*MIC_HOLE)
                    .circle(MIC_D / 2).extrude(WALL + SIDE_FILL + 0.2))
    # counterbore through the side fill so the plug body reaches J4
    body = body.cut(cq.Workplane("YZ").workplane(offset=IX1 + WALL).center(*MIC_HOLE)
                    .circle(MIC_CB / 2).extrude(SIDE_FILL + 0.2))
    return body



def lid():
    plate = rounded_rect(OX0, OY0, OX1, OY1, TOP_Z, TOP_Z + LID_T, CORNER_R)
    # locating lip just inside the shell rim, notched around the screw blocks
    a, b = LIP_CLR, LIP_CLR + LIP_W
    lip = box(IX0 + a, IY0 + a, TOP_Z - LIP_H, IX1 - a, IY1 - a, TOP_Z)
    lip = lip.cut(box(IX0 + b, IY0 + b, TOP_Z - LIP_H - 1, IX1 - b, IY1 - b, TOP_Z + 1))
    for x, side in LID_BOSSES:
        wall = IY0 if side == "top" else IY1
        inward = 1 if side == "top" else -1
        lip = lip.cut(box(x - BOSS_W / 2 - 0.4, wall - inward, TOP_Z - LIP_H - 1,
                          x + BOSS_W / 2 + 0.4, wall + inward * (BOSS_D + 0.4), TOP_Z + 1))
    plate = plate.union(lip)

    # ribs that stop the board lifting when the harness is pulled out
    for x0, x1 in RIBS_X:
        plate = plate.union(box(x0, IY0 + LIP_CLR, BOARD_Z1 + SUPPORT_GAP, x1, RIB_Y1, TOP_Z))

    # fans: grille + 4 screw holes each
    for cx, cy in (FAN1, FAN2):
        disk = cq.Workplane("XY").workplane(offset=TOP_Z - 1).center(cx, cy).circle(GRILLE_D / 2).extrude(LID_T + 2)
        n = int(GRILLE_D // GRILLE_PITCH) + 1
        bars = None
        for i in range(n):
            y = cy - (n - 1) * GRILLE_PITCH / 2 + i * GRILLE_PITCH
            s = box(cx - GRILLE_D, y - GRILLE_SLOT / 2, TOP_Z - 1, cx + GRILLE_D, y + GRILLE_SLOT / 2, TOP_Z + LID_T + 1)
            bars = s if bars is None else bars.union(s)
        plate = plate.cut(bars.intersect(disk))
        for dx in (-1, 1):
            for dy in (-1, 1):
                plate = plate.cut(cq.Workplane("XY").workplane(offset=TOP_Z - 1)
                                  .center(cx + dx * FAN_HOLES / 2, cy + dy * FAN_HOLES / 2)
                                  .circle(FAN_SCREW / 2).extrude(LID_T + 2))

    # harness plug opening
    x0, y0, x1, y1 = J1_OPENING
    plate = plate.cut(rounded_rect(x0, y0, x1, y1, TOP_Z - 2, TOP_Z + LID_T + 1, 2.0))

    # countersunk M3 holes into the shell's inserts
    for x, side in LID_BOSSES:
        hx, hy = lid_boss_xy(x, side)
        plate = plate.cut(cq.Workplane("XY").workplane(offset=TOP_Z - 1).center(hx, hy)
                          .circle(LID_SCREW / 2).extrude(LID_T + 2))
        plate = plate.cut(cq.Workplane("XY").workplane(offset=TOP_Z + LID_T - (CSK - LID_SCREW) / 2)
                          .center(hx, hy).circle(LID_SCREW / 2)
                          .workplane(offset=(CSK - LID_SCREW) / 2 + 0.01).circle(CSK / 2).loft())
    return plate


def fans():
    return [box(cx - FAN / 2, cy - FAN / 2, FAN_Z0, cx + FAN / 2, cy + FAN / 2, FAN_Z1) for cx, cy in (FAN1, FAN2)]


def to_asm(wp):
    """Board coordinates (y down) -> assembly frame (y up)."""
    return wp.mirror("XZ")


def fit_ring(sh):
    return sh.intersect(box(-1e3, -1e3, 0, 1e3, 1e3, 17.0))


def obstacles():
    """Everything the housing must not touch, in the assembly frame."""
    out = [(f"board {i}", s) for i, s in enumerate(assembly.carrier().solids().vals())]
    out += [(n, s.val()) for n, s in assembly.pi4()]
    out.append(("heatsink", assembly.heatsink_placed().val()))
    body, _ = assembly.display()
    out.append(("display", body.val()))
    # the module's rear parts and pillars: anywhere inside the outline, up to the pillar tops
    out.append(("display rear", to_asm(box(SX, SY, assembly.DISPLAY_T, SX + W, SY + H, PILLAR_TOP)).val()))
    return out


def clashes(parts, others, tol=0.01):
    bad = []
    for pname, p in parts:
        pb = p.BoundingBox()
        for oname, o in others:
            ob = o.BoundingBox()
            if (ob.xmin > pb.xmax or ob.xmax < pb.xmin or ob.ymin > pb.ymax or ob.ymax < pb.ymin
                    or ob.zmin > pb.zmax or ob.zmax < pb.zmin):
                continue
            v = p.intersect(o).Volume()
            if v > tol:
                bad.append((pname, oname, v))
    return bad


def check(sh, li):
    obs = obstacles()
    fan_solids = [(f"fan{i + 1}", to_asm(f).val()) for i, f in enumerate(fans())]
    bad = clashes([("shell", sh.val()), ("lid", li.val())] + fan_solids, obs)
    bad += clashes([("shell", sh.val())], [("lid", li.val())] + fan_solids)
    for a, b, v in bad:
        print(f"  CLASH {a} / {b}: {v:.2f} mm3")
    print(f"clearance check: {len(bad)} clashes")
    j1 = pcb_at("J1")
    print(f"  fan 1 above the heatsink:  {FAN_Z0 - HEATSINK_TOP:.2f} mm")
    print(f"  ledge / ribs to the board: {SUPPORT_GAP:.2f} mm")
    print(f"  ledge edge to J1 row 1 pads: {j1[1] - 0.95 - LEDGE_Y1:.2f} mm")
    print(f"  mic hole centre {MIC_HOLE[1]:.2f} mm from the glass, jack nose "
          f"{IX1 - (J4[0] + 8.225):.2f} mm from the inner wall")
    return not bad


def vent_area():
    """Open area (mm2) of the wall slots, the USB opening, and one fan grille."""
    a = sum(SLOT_W * (LOW_Z[1] - LOW_Z[0]) if v.val().BoundingBox().zmin < 25 else SLOT_W * (HIGH_Z[1] - HIGH_Z[0])
            for v in vents())
    y0, z0, y1, z1 = USB_OPENING
    li = lid()
    grille = box(FAN1[0] - FAN / 2, FAN1[1] - FAN / 2, TOP_Z, FAN1[0] + FAN / 2, FAN1[1] + FAN / 2, TOP_Z + LID_T)
    solid = li.intersect(grille).val().Volume() / LID_T
    return a, (y1 - y0) * (z1 - z0), FAN * FAN - solid - 4 * math.pi * (FAN_SCREW / 2) ** 2


def main():
    mech = os.path.join(ROOT, "mech")
    os.makedirs(mech, exist_ok=True)
    sh = to_asm(shell())
    li = to_asm(lid())
    ring = fit_ring(sh)

    cq.exporters.export(sh, os.path.join(mech, "housing_shell.step"))
    cq.exporters.export(li, os.path.join(mech, "housing_lid.step"))
    # print orientation: shell on its front rim, lid flipped onto its outer face
    sh_p = sh.translate((0, 0, -SKIRT_Z))
    li_p = li.rotate((0, 0, 0), (1, 0, 0), 180).translate((0, 0, TOP_Z + LID_T))
    ring_p = ring.translate((0, 0, -SKIRT_Z))
    for name, s in (("housing_shell", sh_p), ("housing_lid", li_p), ("housing_fit_ring", ring_p)):
        p = os.path.join(mech, f"{name}.stl")
        cq.exporters.export(s, p, tolerance=0.02, angularTolerance=0.1)
        bb = s.val().BoundingBox()
        print(f"{os.path.relpath(p)}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm, "
              f"{s.val().Volume() / 1000:.0f} cm3")

    slots_a, usb_a, grille_a = vent_area()
    print(f"exhaust {slots_a:.0f} mm2 of slots + {usb_a:.0f} mm2 USB opening, "
          f"{(slots_a + usb_a) / (2 * grille_a):.1f}x the two grilles' {2 * grille_a:.0f} mm2")
    bb = sh.union(li).val().BoundingBox()
    print(f"housing {bb.xlen:.1f} x {bb.ylen:.1f} mm, back face {TOP_Z + LID_T:.1f} mm from the glass")
    if not check(sh, li):
        sys.exit(1)


if __name__ == "__main__":
    main()
