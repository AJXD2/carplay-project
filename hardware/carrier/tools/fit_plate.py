#!/usr/bin/env python3
"""A printable fit-test plate: the carrier board's outline, notch, cable
slot and screw holes, from the same numbers as the real board (place.py).
Print it, screw it onto the Pi on the back of the screen, and check that
the edges line up with the display and the holes with the standoffs.

    .venv/bin/python tools/fit_plate.py   ->  mech/fit_plate.stl, mech/fit_plate.step

Print top side up (the engraved text reads correctly from the top, which is
the side that faces the firewall). The M2.5 holes are 2.9 mm and the M3
holes 3.4 mm, a little over size for printer shrinkage.
"""
import math
import os
import sys
import types

import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
sys.modules.setdefault("pcbnew", types.ModuleType("pcbnew"))   # place.py only needs it for placing
import place  # noqa: E402

W, H = 165.0, 103.0
T = 1.6                       # same thickness as the board
PI_HOLE, HS_HOLE = 2.9, 3.4
ENGRAVE = 0.6
HEADER = (2 * 2.54 + 1.4, 20 * 2.54 + 1.4)   # 2x20 header, 0.7 mm clearance each side


def xy(x, y):
    """Board mm (y down) -> CadQuery (y up)."""
    return x, -y


def main():
    pts = [xy(x, y) for x, y in place.outline_points(0, 0, W, H)]
    plate = cq.Workplane("XY").polyline(pts).close().extrude(T)
    # display cable slot
    for x0, y0, x1, y1 in place.cutouts():
        cx, cy = xy((x0 + x1) / 2, (y0 + y1) / 2)
        plate = plate.cut(cq.Workplane("XY").center(cx, cy).rect(x1 - x0, y1 - y0).extrude(T))
    # Pi screw holes
    for hx, hy in place.PI_HOLES:
        plate = plate.cut(cq.Workplane("XY").center(*xy(*place.pi_to_board(hx, hy))).circle(PI_HOLE / 2).extrude(T))
    # heatsink screws, either side of the amp along the block's turned axis
    a = math.radians(place.AMP_ROT)
    for s in (-1, 1):
        dy = s * place.HEATSINK_Y
        hx = place.AMP_AT[0] + dy * math.sin(a)
        hy = place.AMP_AT[1] + dy * math.cos(a)
        plate = plate.cut(cq.Workplane("XY").center(*xy(hx, hy)).circle(HS_HOLE / 2).extrude(T))
    # window for the Pi's 40-pin header (the socket sits under the real board)
    c = place.pi_to_board(32.5, 3.5)
    hw, hh = (HEADER[1], HEADER[0]) if place.PI["rot"] % 180 == 0 else (HEADER[0], HEADER[1])
    if place.PI["rot"] % 180 == 0:
        hw, hh = HEADER[1], HEADER[0]
    plate = plate.cut(cq.Workplane("XY").center(*xy(*c)).rect(hw, hh).extrude(T))
    # engraved labels on the top face
    labels = [("TOP (firewall side)", (W / 2 + 20, 97.0), 4.0),
              ("harness plug", (117.5, 14.0), 3.0),
              ("amp heatsink", (place.AMP_AT[0], place.AMP_AT[1] + 12.0), 3.0),
              ("Pi header", (c[0], c[1] - 5.0), 3.0)]
    for text, (x, y), size in labels:
        cut = (cq.Workplane("XY").workplane(offset=T - ENGRAVE).center(*xy(x, y))
               .text(text, size, ENGRAVE, combine=False, halign="center", valign="center"))
        plate = plate.cut(cut)
    # harness plug footprint, engraved outline (Micro-Fit 2x10 vertical body)
    jx0, jy0 = place.J1_PIN1[0] - 3.0, place.J1_PIN1[1] - 3.2
    ring = (cq.Workplane("XY").workplane(offset=T - ENGRAVE)
            .center(*xy(jx0 + 33.0 / 2, jy0 + 9.6 / 2)).rect(33.0, 9.6).rect(32.2, 8.8).extrude(ENGRAVE))
    plate = plate.cut(ring)

    os.makedirs(os.path.join(ROOT, "mech"), exist_ok=True)
    stl = os.path.join(ROOT, "mech", "fit_plate.stl")
    cq.exporters.export(plate, stl, tolerance=0.02, angularTolerance=0.1)
    cq.exporters.export(plate, os.path.join(ROOT, "mech", "fit_plate.step"))
    bb = plate.val().BoundingBox()
    print(f"{os.path.relpath(stl)}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")
    for hx, hy in place.PI_HOLES:
        bx, by = place.pi_to_board(hx, hy)
        sx, sy = place.OUTLINE_SHIFT
        print(f"  Pi hole at {bx - sx:.2f}, {by - sy:.2f} mm from the top-left corner (viewed from the top)")


def frame(rim=4.0, bar=3.0, boss=3.5):
    """Material-saving version: a rim along the exact outline (notch
    included), rings around the four Pi screw holes and bars tying them to
    the rim. The bars stay clear of the Pi header, so it still seats on the
    standoffs.  ->  mech/fit_frame.stl"""
    pts = [xy(x, y) for x, y in place.outline_points(0, 0, W, H)]
    def outline():
        return cq.Workplane("XY").polyline(pts).close()

    body = outline().extrude(T)
    body = body.cut(outline().offset2D(-rim).extrude(T))
    sx, sy = place.OUTLINE_SHIFT
    top, bottom, right = sy, H + sy, W + sx
    holes = [place.pi_to_board(hx, hy) for hx, hy in place.PI_HOLES]
    xl, xr = sorted({round(h[0], 3) for h in holes})
    yt, yb = sorted({round(h[1], 3) for h in holes})

    def bar_(x0, y0, x1, y1):
        cx, cy = xy((x0 + x1) / 2, (y0 + y1) / 2)
        w, h = (abs(x1 - x0) or bar), (abs(y1 - y0) or bar)
        return cq.Workplane("XY").center(cx, cy).rect(w, h).extrude(T)

    parts = [bar_(xl, yt, xr, yt),                 # between the upper holes
             bar_(xl, yt, xl, yb), bar_(xr, yt, xr, yb),   # down both sides
             bar_(xl, top, xl, yt), bar_(xr, top, xr, yt),  # up to the top rim
             bar_(xl, yb, xl, bottom), bar_(xr, yb, xr, bottom),  # down to the bottom rim
             bar_(xr, yt, right, yt), bar_(xr, yb, right, yb)]    # across to the right rim
    for hx, hy in holes:
        parts.append(cq.Workplane("XY").center(*xy(hx, hy)).circle(boss).extrude(T))
    for p in parts:
        body = body.union(p)
    for hx, hy in holes:
        body = body.cut(cq.Workplane("XY").center(*xy(hx, hy)).circle(PI_HOLE / 2).extrude(T))
    # clip anything that pokes outside the outline (bars into the notch)
    body = body.intersect(outline().extrude(T))
    out = os.path.join(ROOT, "mech", "fit_frame.stl")
    cq.exporters.export(body, out, tolerance=0.02, angularTolerance=0.1)
    full = outline().extrude(T).val().Volume()
    print(f"{os.path.relpath(out)}: {body.val().Volume() / 1000:.1f} cm3, "
          f"{100 * (1 - body.val().Volume() / full):.0f}% less than the solid plate")


if __name__ == "__main__":
    main()
    frame()
