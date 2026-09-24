#!/usr/bin/env python3
"""2D drawing of the amp heatsink for the CNC order (thread callout, finish).

    .venv/bin/python tools/heatsink_drawing.py   ->  mech/heatsink_drawing.pdf

Dimensions come from heatsink.py so the drawing and the STEP always agree.
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, Rectangle  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import heatsink as hs  # noqa: E402

OUT = os.path.join(HERE, "..", "mech", "heatsink_drawing.pdf")
THREAD_DEPTH = 4.0
LW, THIN = 0.9, 0.45


def dim(ax, a, b, text, off, vertical=False, size=7):
    """Dimension line between points a and b, offset `off` mm."""
    (x0, y0), (x1, y1) = a, b
    if vertical:
        x = max(x0, x1) + off
        ax.annotate("", (x, y0), (x, y1), arrowprops=dict(arrowstyle="<->", lw=THIN))
        ax.plot([x0, x], [y0, y0], lw=0.3, color="k")
        ax.plot([x1, x], [y1, y1], lw=0.3, color="k")
        ax.text(x + 0.8, (y0 + y1) / 2, text, fontsize=size, va="center", rotation=90)
    else:
        y = min(y0, y1) - off
        ax.annotate("", (x0, y), (x1, y), arrowprops=dict(arrowstyle="<->", lw=THIN))
        ax.plot([x0, x0], [y0, y], lw=0.3, color="k")
        ax.plot([x1, x1], [y1, y], lw=0.3, color="k")
        ax.text((x0 + x1) / 2, y - 1.8, text, fontsize=size, ha="center", va="top")


def main():
    fig = plt.figure(figsize=(11.69, 8.27))                 # A4 landscape
    fig.text(0.05, 0.94, "AMP HEATSINK  (TAS6424 carrier board)", fontsize=15, weight="bold")
    fig.text(0.05, 0.905, "All dimensions in mm. Model: heatsink.step (this drawing governs threads and finish).",
             fontsize=9)

    # bottom view: 20 x 41.4 footprint, two feet with tapped holes
    ax = fig.add_axes([0.05, 0.12, 0.38, 0.72])
    ax.set_title("BOTTOM VIEW (feet side)", fontsize=10, loc="left")
    W, L = hs.W, hs.L
    ax.add_patch(Rectangle((-W / 2, -L / 2), W, L, fill=False, lw=LW))
    for s in (1, -1):
        y = s * hs.FOOT_Y
        ax.add_patch(Circle((0, y), hs.FOOT_D / 2, fill=False, lw=LW))
        ax.add_patch(Circle((0, y), 3.0 / 2, fill=False, lw=THIN, ls="--"))    # M3 major dia
        ax.add_patch(Circle((0, y), hs.TAP_D / 2, fill=False, lw=LW))
        ax.plot([-4.5, 4.5], [y, y], lw=0.3, color="k", ls="-.")
    ax.plot([0, 0], [-L / 2 - 3, L / 2 + 3], lw=0.3, color="k", ls="-.")
    dim(ax, (-W / 2, -L / 2), (W / 2, -L / 2), f"{W:g}", 4)
    dim(ax, (W / 2, -L / 2), (W / 2, L / 2), f"{L:g}", 4, vertical=True)
    dim(ax, (0, -hs.FOOT_Y), (0, hs.FOOT_Y), f"{2 * hs.FOOT_Y:g}", 20, vertical=True)
    ax.text(0, -L / 2 - 9, "holes on the centreline", fontsize=7, ha="center")
    ax.annotate(f"2x  M3 x 0.5 - 6H\nthread depth {THREAD_DEPTH:g} min\n"
                f"tap drill {hs.TAP_D:g} x {hs.TAP_DEPTH:g} deep\nfrom the foot faces",
                xy=(0.9, hs.FOOT_Y + 0.9), xytext=(-W / 2 - 17, hs.FOOT_Y + 8), fontsize=8,
                arrowprops=dict(arrowstyle="->", lw=THIN))
    ax.annotate(f"2x foot  {hs.FOOT_D:g} dia", xy=(-hs.FOOT_D / 2 * 0.7, -hs.FOOT_Y - 2.3),
                xytext=(-W / 2 - 17, -hs.FOOT_Y - 8), fontsize=8, arrowprops=dict(arrowstyle="->", lw=THIN))
    ax.set_xlim(-32, 30)
    ax.set_ylim(-L / 2 - 12, L / 2 + 12)
    ax.set_aspect("equal")
    ax.axis("off")

    # side view along the long side: feet, base, fins
    bx = fig.add_axes([0.47, 0.42, 0.48, 0.44])
    bx.set_title("SIDE VIEW (fins up; feet sit on the board)", fontsize=10, loc="left")
    fh, base, fin = hs.FOOT_H, hs.BASE, hs.FIN_H
    bx.add_patch(Rectangle((-L / 2, fh), L, base, fill=False, lw=LW))
    bx.add_patch(Rectangle((-L / 2, fh + base), L, fin, fill=False, lw=LW))
    for s in (1, -1):
        y = s * hs.FOOT_Y
        bx.add_patch(Rectangle((y - hs.FOOT_D / 2, 0), hs.FOOT_D, fh, fill=False, lw=LW))
        bx.add_patch(Rectangle((y - hs.TAP_D / 2, 0), hs.TAP_D, hs.TAP_DEPTH, fill=False, lw=THIN, ls="--"))
    dim(bx, (-L / 2, 0), (L / 2, 0), f"{L:g}", 4)
    dim(bx, (L / 2, 0), (L / 2, fh), f"{fh:.2f} +/-0.05", 3, vertical=True, size=7)
    dim(bx, (L / 2, fh), (L / 2, fh + base), f"{base:g}", 10, vertical=True)
    dim(bx, (L / 2, 0), (L / 2, fh + base + fin), f"{fh + base + fin:.1f}", 17, vertical=True)
    bx.text(0, fh + base + fin / 2, f"{hs.FINS} fins, {hs.FIN_T:g} thick, {hs.FIN_GAP:g} gaps, "
            f"{fin:g} tall\n(see STEP)", ha="center", va="center", fontsize=8)
    bx.set_xlim(-L / 2 - 6, L / 2 + 26)
    bx.set_ylim(-9, fh + base + fin + 3)
    bx.set_aspect("equal")
    bx.axis("off")

    # notes / title block
    notes = [
        "Material: aluminium 6061-T6.",
        "Finish: NONE (bare metal). No anodising: the heatsink is grounded",
        "  through its feet and screws.",
        "Threads: 2x M3 x 0.5-6H, 4 mm full thread min, in the two feet.",
        f"Foot height {fh:.2f} +/-0.05 (critical: sets the clamp on the chip).",
        "Base underside flat within 0.05 over the chip area (centre 20 x 12).",
        "Other tolerances: ISO 2768-m. Break sharp edges.",
        "Quantity: 2.",
    ]
    fig.text(0.47, 0.34, "NOTES", fontsize=10, weight="bold")
    for i, n in enumerate(notes):
        fig.text(0.47, 0.31 - i * 0.028, n, fontsize=9)
    fig.patches.append(Rectangle((0.46, 0.06), 0.5, 0.31, transform=fig.transFigure, fill=False, lw=0.6))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fig.savefig(OUT)
    fig.savefig(OUT.replace(".pdf", ".png"), dpi=110)
    print(os.path.relpath(OUT))


if __name__ == "__main__":
    main()
