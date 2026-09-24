#!/usr/bin/env python3
"""3D stack-up: Hosyond 7" DSI display, Raspberry Pi 4, carrier board,
amp heatsink. For designing the enclosure and checking clearances.

Frame: origin at the display's top-left corner seen from the BACK (the side
facing the firewall), x to the right, y up, z out of the back toward the
firewall. The glass faces -z.

Sources: display 165 x 103 mm (Hosyond drawing); Pi position from
place.PI (measured from Hosyond's back-view drawing); Pi 4 outline, holes
and connectors from the Raspberry Pi 4 mechanical drawing; board from
KiCad's STEP export; heatsink from tools/heatsink.py. Assumed, not
measured: display module 6.0 mm thick, Pi standoffs 6.0 mm. Change
DISPLAY_T / PI_STANDOFF when you can measure them.

    .venv/bin/python tools/assembly.py    ->  mech/assembly.step/.stl, out/3d/*.png
"""
import math
import os
import subprocess
import sys

import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)

# place.py imports pcbnew only for the helpers we do not use here
import types  # noqa: E402
sys.modules.setdefault("pcbnew", types.ModuleType("pcbnew"))
import heatsink  # noqa: E402
import place  # noqa: E402

DISPLAY_W, DISPLAY_H = 164.9, 102.0   # manufacturer drawing
DISPLAY_T = 8.25         # glass + LCD + backlight + PCB (drawing; 12.25 incl. rear parts)
PI_STANDOFF = 6.0        # display back to Pi underside (assumed)
PI_T = 1.6
HAT_GAP = 11.0           # Pi top to carrier underside: 2.5 mm header base + 8.5 mm socket
BOARD_T = 1.6
BOARD_ORIGIN = (100.0, 100.0)   # where gen_pcb puts the board's top-left corner

Z_PI = DISPLAY_T + PI_STANDOFF
Z_BOARD = Z_PI + PI_T + HAT_GAP


def to_asm(bx, by):
    """Board / display coordinates (mm, y down) -> assembly x, y."""
    return bx, -by


def box(x0, y0, x1, y1, z0, z1):
    return (cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False)
            .translate((x0, y0, z0)))


def display():
    body = box(0, -DISPLAY_H, DISPLAY_W, 0, 0, DISPLAY_T)
    glass = box(0, -DISPLAY_H, DISPLAY_W, 0, -0.01, 1.2)       # separate so it renders darker
    return body, glass


def pi4():
    """Raspberry Pi 4 in its own frame (header along the top edge, ports on
    the right, y down), then placed with place.PI."""
    parts = []

    def pbox(x0, y0, x1, y1, z0, z1):
        return box(x0, -y1, x1, -y0, z0, z1)

    pcb = (cq.Workplane("XY").rect(85, 56).extrude(PI_T).edges("|Z").fillet(3.0)
           .translate((42.5, -28, 0)))
    for hx, hy in place.PI_HOLES:
        pcb = pcb.cut(cq.Workplane("XY").circle(1.375).extrude(PI_T).translate((hx, -hy, 0)))
    parts.append(("pi_pcb", pcb))
    t = PI_T
    parts += [
        ("pi_eth", pbox(65.0, 2.0, 87.1, 18.0, t, t + 13.5)),         # RJ45, y centre 10.25
        ("pi_usb3", pbox(70.0, 22.4, 87.1, 35.6, t, t + 16.0)),       # USB 3 pair, y centre 29
        ("pi_usb2", pbox(70.0, 40.4, 87.1, 53.6, t, t + 16.0)),       # USB 2 pair, y centre 47
        ("pi_soc", pbox(22.0, 25.0, 37.0, 40.0, t, t + 2.4)),
        ("pi_header", pbox(32.5 - 25.4, 3.5 - 2.54, 32.5 + 25.4, 3.5 + 2.54, t, t + 2.5)),
        ("pi_pins", pbox(32.5 - 25.0, 3.5 - 2.2, 32.5 + 25.0, 3.5 + 2.2, t + 2.5, t + 8.5)),
        ("pi_usbc", pbox(7.5, 49.0, 16.5, 57.2, t, t + 3.2)),         # x centre 11.2
        ("pi_hdmi0", pbox(22.5, 50.0, 29.7, 57.2, t, t + 3.0)),       # 26.0
        ("pi_hdmi1", pbox(36.0, 50.0, 43.2, 57.2, t, t + 3.0)),       # 39.5
        ("pi_audio", pbox(50.5, 44.0, 57.5, 57.2, t, t + 6.0)),       # 54.0
        ("pi_dsi", pbox(0.8, 19.5, 5.2, 36.5, t, t + 5.5)),
        ("pi_csi", pbox(43.0, 39.0, 47.0, 56.0, t, t + 5.5)),
    ]
    # into board coordinates: rotate about the Pi centre, then move
    a = place.PI["rot"]
    out = []
    for name, s in parts:
        s = s.translate((-42.5, 28, 0)).rotate((0, 0, 0), (0, 0, 1), -a)
        cx, cy = place.pi_to_board(42.5, 28.0)
        s = s.translate((cx, -cy, Z_PI))
        out.append((name, s))
    return out


def standoffs():
    out = []
    for hx, hy in place.PI_HOLES:
        bx, by = place.pi_to_board(hx, hy)
        x, y = to_asm(bx, by)
        low = (cq.Workplane("XY").polygon(6, 5.0).extrude(PI_STANDOFF)
               .translate((x, y, DISPLAY_T)))
        high = (cq.Workplane("XY").polygon(6, 5.0).extrude(HAT_GAP)
                .translate((x, y, Z_PI + PI_T)))
        out += [(f"standoff_low_{hx}_{hy}", low), (f"standoff_high_{hx}_{hy}", high)]
    return out


def carrier():
    step = os.path.join(ROOT, "mech", "carrier_board.step")
    b = cq.importers.importStep(step)
    return b.translate((-BOARD_ORIGIN[0], BOARD_ORIGIN[1], Z_BOARD))


def coin_cell_stand_in():
    """BT1 has no KiCad 3D model: 20 mm cell + holder, 5.5 mm tall."""
    x, y = to_asm(6.0 + 10.85, 15.0)
    return cq.Workplane("XY").circle(11.0).extrude(5.5).translate((x, y, Z_BOARD + BOARD_T))


def heatsink_placed():
    hs = heatsink.build()
    if place.AMP_ROT % 180:
        hs = hs.rotate((0, 0, 0), (0, 0, 1), 90)
    x, y = to_asm(*place.AMP_AT)
    return hs.translate((x, y, Z_BOARD + BOARD_T + 2.33))    # base on the chip's top pad


def build():
    body, glass = display()
    asm = cq.Assembly(name="carplay_head_unit")
    asm.add(body, name="display", color=cq.Color(0.10, 0.25, 0.55))
    asm.add(glass, name="display_glass", color=cq.Color(0.05, 0.05, 0.05))
    for name, s in standoffs():
        asm.add(s, name=name, color=cq.Color(0.8, 0.6, 0.2))
    for name, s in pi4():
        col = cq.Color(0.1, 0.5, 0.2) if name == "pi_pcb" else cq.Color(0.75, 0.75, 0.78)
        asm.add(s, name=name, color=col)
    asm.add(carrier(), name="carrier_board")
    asm.add(coin_cell_stand_in(), name="coin_cell", color=cq.Color(0.7, 0.7, 0.7))
    asm.add(heatsink_placed(), name="heatsink", color=cq.Color(0.15, 0.15, 0.15))
    return asm


def main():
    os.makedirs(os.path.join(ROOT, "mech"), exist_ok=True)
    asm = build()
    step = os.path.join(ROOT, "mech", "assembly.step")
    asm.save(step)
    comp = asm.toCompound()
    cq.exporters.export(cq.Workplane().add(comp), os.path.join(ROOT, "mech", "assembly.stl"),
                        tolerance=0.05, angularTolerance=0.2)
    bb = comp.BoundingBox()
    print(f"assembly {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm "
          f"(z {bb.zmin:.1f} .. {bb.zmax:.1f}); board underside at z {Z_BOARD:.1f}")


if __name__ == "__main__":
    main()
