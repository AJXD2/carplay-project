#!/usr/bin/env python3
"""Plot carrier.kicad_sch to SVG/PNG and crop regions for review.

usage: render.py [name x1 y1 x2 y2]...   (sheet millimetres)
Writes out/sch/full.png plus out/sch/<name>.png for each crop.
"""
import os
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
OUT = os.path.join(ROOT, "out", "sch")
PAPER_W = 594  # A2 landscape

Image.MAX_IMAGE_PIXELS = None
os.makedirs(OUT, exist_ok=True)
subprocess.run(["kicad-cli", "sch", "export", "svg", "-o", OUT, os.path.join(ROOT, "carrier.kicad_sch")],
               check=True, capture_output=True)
subprocess.run(["rsvg-convert", "-z", "1.6", "-b", "white", os.path.join(OUT, "carrier.svg"),
                "-o", os.path.join(OUT, "full.png")], check=True)
im = Image.open(os.path.join(OUT, "full.png"))
s = im.size[0] / PAPER_W
args = sys.argv[1:]
for i in range(0, len(args), 5):
    name, *box = args[i:i + 5]
    x1, y1, x2, y2 = (float(v) * s for v in box)
    im.crop((int(x1), int(y1), int(x2), int(y2))).save(os.path.join(OUT, f"{name}.png"))
    print(os.path.join("out", "sch", f"{name}.png"))
