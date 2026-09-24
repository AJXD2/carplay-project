#!/usr/bin/env python3
"""Part centres for the JLCPCB placement file (run by jlc_export.sh).

KiCad puts a through-hole footprint's origin on pin 1; JLC places every part
by its centre. SMD footprints are already centred. For through-hole parts:
the origin of JLC's own (EasyEDA) model where we know it (the same offsets
gen_pcb.MODELS uses to line those models up), else the centre of the pads.
Writes out/jlc/centres.csv: Ref, x, y (mm, same frame as `kicad-cli pcb
export pos`: y up).
"""
import csv
import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_pcb  # noqa: E402

b = pcbnew.LoadBoard(os.path.join(HERE, "..", "carrier.kicad_pcb"))
rows = []
for fp in b.GetFootprints():
    pos = fp.GetPosition()
    x, y = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
    fpid = f"{fp.GetFPID().GetLibNickname()}:{fp.GetFPID().GetLibItemName()}"
    tht = any(p.GetDrillSizeX() and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for p in fp.Pads())
    if fpid in gen_pcb.MODELS:
        ox, oy, _ = gen_pcb.MODELS[fpid][1]
        lx, ly = ox, -oy                           # model offsets are y-up
        a = math.radians(fp.GetOrientationDegrees())
        x += lx * math.cos(a) + ly * math.sin(a)
        y += -lx * math.sin(a) + ly * math.cos(a)
    elif tht:
        pads = [p.GetPosition() for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
        x = pcbnew.ToMM(min(p.x for p in pads) + max(p.x for p in pads)) / 2
        y = pcbnew.ToMM(min(p.y for p in pads) + max(p.y for p in pads)) / 2
    rows.append((fp.GetReference(), round(x, 4), round(-y, 4)))
with open(os.path.join(HERE, "..", "out", "jlc", "centres.csv"), "w", newline="") as f:
    csv.writer(f).writerows([("Ref", "X", "Y")] + rows)
