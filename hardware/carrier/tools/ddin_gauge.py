#!/usr/bin/env python3
"""Step gauges for the Metra 95-8210 trim panel's double DIN opening.
Metra publishes no dimensions, so measure the opening with these instead of
calipers: each gauge is a flat plate whose size grows in 0.5 mm steps,
labelled. Push it straight into the opening (trim panel on the bench) until
it stops, mark the plate at the panel's face, pull it out: the step just
in front of the mark is the biggest that fits, so the opening is between
that and the next label.

  height gauge  99.0 .. 108.0 mm, pushed in vertically (edge up)
  width gauge  175.0 .. 184.0 mm, pushed in flat

Print flat, PETG or PLA, no supports. Check one step with a ruler first: the
labels are only true if the printer is.

    .venv/bin/python tools/ddin_gauge.py  ->  mech/ddin_gauge_height.step/.stl, mech/ddin_gauge_width.step/.stl
"""
import os

import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "mech")
T = 3.0          # plate thickness
STEP_D = 6.0     # how deep each step is
STEP = 0.5       # size increase per step
TEXT_H = 3.2


def gauge(start, stop):
    """Staircase plate: across x the size, along y the depth. Step i (from
    the front edge y = 0) is start + i * STEP wide, centred on x = 0."""
    n = int(round((stop - start) / STEP)) + 1
    body = None
    for i in range(n):
        w = start + i * STEP
        s = cq.Workplane("XY").box(w, STEP_D, T, centered=(True, False, False)).translate((0, i * STEP_D, 0))
        body = s if body is None else body.union(s)
    # engraved on top, centred on each step
    for i in range(n):
        label = (cq.Workplane("XY").workplane(offset=T - 0.6)
                 .center(0, i * STEP_D + STEP_D / 2)
                 .text(f"{start + i * STEP:.1f}", TEXT_H, 1.0, halign="center", valign="center"))
        body = body.cut(label)
    # a handle at the back
    body = body.union(cq.Workplane("XY").box(40, 20, T, centered=(True, False, False))
                      .translate((0, n * STEP_D, 0)))
    return body


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, (a, b) in (("height", (99.0, 108.0)), ("width", (175.0, 184.0))):
        g = gauge(a, b)
        cq.exporters.export(g, os.path.join(OUT, f"ddin_gauge_{name}.step"))
        p = os.path.join(OUT, f"ddin_gauge_{name}.stl")
        cq.exporters.export(g, p, tolerance=0.01, angularTolerance=0.1)
        bb = g.val().BoundingBox()
        print(f"{os.path.relpath(p)}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")


if __name__ == "__main__":
    main()
