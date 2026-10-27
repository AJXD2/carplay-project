"""Harness plug diagram for J1 (Molex Micro-Fit 3.0, 2x10): which truck wire goes
in which cavity. Writes out/harness.png.

View: the WIRE side of the plug while it is plugged in, looking down at the
board's component side with J1 along the top edge (as in the assembly
drawing). Pin 1 is top left; pins 1-10 run left to right along the row
nearest the board edge, 11-20 below them. Speaker pins checked on board 2
(BRINGUP.md stage 7). Colours are the EIA colours on Metra harnesses.

    .venv/bin/python tools/harness_diagram.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

OUT = Path(__file__).resolve().parent.parent / "out" / "harness.png"

C = {"yellow": "#f2d600", "black": "#222222", "red": "#d62828", "orange": "#f77f00",
     "white": "#f4f4f4", "gray": "#9a9a9a", "purple": "#7b2cbf", "green": "#2b9348",
     "pink": "#ff8fab", "none": "#d9d9d9", "swc": "#4ea8de"}

# pin: (signal, short label, wire colour, stripe colour or None, where it comes from)
PINS = {
    1: ("+12 V constant", "+12V", "yellow", None, "Metra yellow (split: one lead to 1, one to 11)"),
    2: ("Ground", "GND", "black", None, "Metra black (split to 2, 12, 19)"),
    3: ("Front right +", "FR+", "gray", None, "Metra gray"),
    4: ("Front left +", "FL+", "white", None, "Metra white"),
    5: ("Rear right +", "RR+", "purple", None, "Metra purple"),
    6: ("Rear left +", "RL+", "green", None, "Metra green"),
    7: ("Key / ACC", "ACC", "red", None, "Metra red"),
    8: ("Steering wheel 1 (seek, volume)", "SWC1", "swc", None, "KEY1 from the white 20-pin plug (find with a meter)"),
    9: ("Steering wheel ground", "SWC GND", "swc", "black", "Wheel ground if the wheel has its own; else a short link to ground"),
    10: ("Reverse (+12 V in reverse)", "REV", "pink", None, "Adapter's pink BACK wire, or a Posi-Tap on the reverse light"),
    11: ("+12 V constant", "+12V", "yellow", None, "Metra yellow (second lead)"),
    12: ("Ground", "GND", "black", None, "Metra black (second lead)"),
    13: ("Front right -", "FR-", "gray", "black", "Metra gray/black"),
    14: ("Front left -", "FL-", "white", "black", "Metra white/black"),
    15: ("Rear right -", "RR-", "purple", "black", "Metra purple/black"),
    16: ("Rear left -", "RL-", "green", "black", "Metra green/black"),
    17: ("Headlights / illumination", "ILLUM", "orange", None, "Metra orange (or orange/white)"),
    18: ("Steering wheel 2 (mode)", "SWC2", "swc", None, "KEY2 from the white 20-pin plug (find with a meter)"),
    19: ("Ground", "GND", "black", None, "Metra black (third lead)"),
    20: ("Not used", "-", "none", None, "Leave empty"),
}


def cavity(ax, x, y, pin):
    sig, short, col, stripe, _ = PINS[pin]
    ax.add_patch(FancyBboxPatch((x, y), 1, 1, boxstyle="round,pad=0,rounding_size=0.12",
                                fc=C[col], ec="#333333", lw=1.5))
    if stripe:                                   # tracer stripe: bands down both sides
        for sx in (x + 0.06, x + 0.82):
            ax.add_patch(Rectangle((sx, y + 0.1), 0.12, 0.8, fc=C[stripe], ec="none"))
    dark = col in ("black", "purple", "green", "red")
    tc = "white" if dark else "black"
    ax.text(x + 0.5, y + 0.68, str(pin), ha="center", va="center", fontsize=13, weight="bold", color=tc)
    ax.text(x + 0.5, y + 0.3, short, ha="center", va="center", fontsize=7.5, color=tc)


def main():
    fig = plt.figure(figsize=(13, 9.6), dpi=150)
    ax = fig.add_axes([0.03, 0.55, 0.94, 0.42])
    ax.set_xlim(-0.6, 13.2)
    ax.set_ylim(-1.1, 3.6)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((-0.35, -0.3), 12.45, 2.95, boxstyle="round,pad=0.05,rounding_size=0.2",
                                fc="#efefef", ec="#555555", lw=2))
    for i in range(10):
        cavity(ax, i * 1.2, 1.35, i + 1)          # pins 1-10, nearest the board edge
        cavity(ax, i * 1.2, 0.0, i + 11)          # pins 11-20
    ax.annotate("", xy=(12.6, 2.75), xytext=(12.6, 1.2), arrowprops=dict(arrowstyle="->", lw=1.5))
    ax.text(12.75, 1.9, "board\nedge", fontsize=9, ha="left", va="center")
    ax.text(-0.3, 3.25, "J1 harness plug: WIRE side, plugged in, board viewed from above (J1 along the top edge)",
            fontsize=12, weight="bold")
    ax.text(-0.3, -0.8, "Pin 1 = top left. Check against the numbers moulded on the Molex housing before "
            "pushing pins in. The plug is keyed, so it only mates one way.", fontsize=9.5)

    tx = fig.add_axes([0.03, 0.02, 0.94, 0.5])
    tx.axis("off")
    rows = [[str(p), s[0], s[4]] for p, s in PINS.items()]
    tab = tx.table(cellText=rows, colLabels=["Pin", "Signal", "Wire"], loc="upper left",
                   colWidths=[0.05, 0.27, 0.68], cellLoc="left")
    tab.auto_set_font_size(False)
    tab.set_fontsize(9)
    tab.scale(1, 1.25)
    for (r, c), cell in tab.get_celld().items():
        cell.PAD = 0.01
        if r == 0:
            cell.set_text_props(weight="bold")
            cell.set_facecolor("#dddddd")
        elif c == 0:
            col = PINS[r][2]
            cell.set_facecolor(C[col])
            cell.set_text_props(color="white" if col in ("black", "purple", "green", "red") else "black",
                                weight="bold")
    tx.text(0, -0.04, "Not used from the Metra harness: blue (power antenna), blue/white (amp turn-on). "
            "Cap them. Use 18 AWG pre-crimped Micro-Fit leads (Molex 2147611124); solder and heat-shrink "
            "each joint.", fontsize=9, transform=tx.transAxes, va="top")
    OUT.parent.mkdir(exist_ok=True)
    fig.savefig(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
