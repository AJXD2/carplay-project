#!/usr/bin/env python3
"""Part centres and rotations for the JLCPCB placement file (run by jlc_export.sh).

JLC places each part by the origin of its own (EasyEDA) footprint, turned by
the CPL rotation. KiCad puts a through-hole footprint's origin on pin 1; SMD
footprints are already centred. Position: JLC_ORIGIN where JLC's origin is
known to differ, else the origin of JLC's model where we know it (the same
offsets gen_pcb.MODELS uses to line those models up), else the centre of the
pads. Rotation: JLC_ROT is added where JLC's footprint is drawn turned
relative to KiCad's. Both tables were fitted pad by pad against JLC's
footprints by tools/check_cpl.py, which also re-checks fab/carrier_cpl.csv.
Writes out/jlc/centres.csv: Ref, x, y (mm, same frame as `kicad-cli pcb
export pos`: y up), dRot (degrees to add to KiCad's rotation).
"""
import csv
import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_pcb  # noqa: E402

# Degrees JLC's footprint is turned from KiCad's (pin 1 elsewhere). Without
# these, JLC would fit the SOT-23s, ICs and FETs rotated, the CR2032 holder
# reversed and the harness and fan connectors with their latch/ramp on the
# wrong side. LEDs (JLC calls pad 1 the anode, but the pins land right), every
# R/C/L and the symmetric Pi socket (bottom, aligned to its holes) need none.
JLC_ROT = {
    "Package_TO_SOT_SMD:SOT-23": 180,
    "Package_TO_SOT_SMD:SOT-23-5": 180,
    "Package_TO_SOT_SMD:LFPAK56": 180,
    "Package_SO:TSSOP-10_3x3mm_P0.5mm": 270,
    "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm": 270,
    "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm": 270,
    "Package_SO:SSOP-56_7.5x18.5mm_P0.635mm": 270,
    "Connector_Molex:Molex_Micro-Fit_3.0_43045-2012_2x10_P3.00mm_Vertical": 180,
    "Connector:FanPinHeader_1x04_P2.54mm_Vertical": 180,
    "Battery:BatteryHolder_MYOUNG_BS-07-A1BJ001_CR2032": 180,
}
# JLC's footprint origin in KiCad's footprint frame (mm, y down), where it is
# neither KiCad's origin, the 3D model's origin nor the pad centre.
JLC_ORIGIN = {
    # midway between the two pins, not the 3D model's origin 14.23 mm from pin 1
    "Battery:BatteryHolder_MYOUNG_BS-07-A1BJ001_CR2032": (10.4, 0.0),
    # locating-peg holes at -5.7 / +1.3 in JLC's, -4.775 / +2.225 in KiCad's
    "Connector_Audio:Jack_3.5mm_PJ320D_Horizontal": (0.925, 0.0),
}


def moved(x, y, lx, ly, deg):
    """(x, y) plus the footprint-frame offset (lx, ly), all y down."""
    a = math.radians(deg)
    return x + lx * math.cos(a) + ly * math.sin(a), y - lx * math.sin(a) + ly * math.cos(a)


b = pcbnew.LoadBoard(os.path.join(HERE, "..", "carrier.kicad_pcb"))
rows = []
for fp in b.GetFootprints():
    pos = fp.GetPosition()
    x, y = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
    fpid = f"{fp.GetFPID().GetLibNickname()}:{fp.GetFPID().GetLibItemName()}"
    tht = any(p.GetDrillSizeX() and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for p in fp.Pads())
    if fpid in JLC_ORIGIN:
        x, y = moved(x, y, *JLC_ORIGIN[fpid], fp.GetOrientationDegrees())
    elif fpid in gen_pcb.MODELS:
        ox, oy, _ = gen_pcb.MODELS[fpid][1]
        x, y = moved(x, y, ox, -oy, fp.GetOrientationDegrees())     # model offsets are y-up
    elif tht:
        pads = [p.GetPosition() for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
        x = pcbnew.ToMM(min(p.x for p in pads) + max(p.x for p in pads)) / 2
        y = pcbnew.ToMM(min(p.y for p in pads) + max(p.y for p in pads)) / 2
    rows.append((fp.GetReference(), round(x, 4), round(-y, 4), JLC_ROT.get(fpid, 0)))
with open(os.path.join(HERE, "..", "out", "jlc", "centres.csv"), "w", newline="") as f:
    csv.writer(f).writerows([("Ref", "X", "Y", "dRot")] + rows)
