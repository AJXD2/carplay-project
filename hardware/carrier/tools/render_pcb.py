#!/usr/bin/env python3
"""Plot carrier.kicad_pcb to PNG for review: out/pcb/<name>.png.

usage: render_pcb.py [layers] [name x1 y1 x2 y2]...   (board mm, from board origin)
"""
import os
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
OUT = os.path.join(ROOT, "out", "pcb")
os.makedirs(OUT, exist_ok=True)
layers = sys.argv[1] if len(sys.argv) > 1 else "Edge.Cuts,F.Cu,F.Silkscreen,F.Courtyard,B.Courtyard,F.Fab"
svg = os.path.join(OUT, "board.svg")
subprocess.run(["kicad-cli", "pcb", "export", "svg", "--mode-single", "--page-size-mode", "2", "--layers", layers,
                "--exclude-drawing-sheet", "-o", svg, os.path.join(ROOT, "carrier.kicad_pcb")],
               check=True, capture_output=True)
png = os.path.join(OUT, "board.png")
subprocess.run(["rsvg-convert", "-d", "300", "-p", "300", "-b", "white", svg, "-o", png], check=True)
print(os.path.relpath(png), Image.open(png).size)
