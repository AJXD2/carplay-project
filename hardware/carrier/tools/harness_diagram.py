"""Harness plug diagram for J1 (Molex Micro-Fit 3.0, 2x10): which truck wire goes
in which cavity. Writes out/harness.png.

View: the WIRE side of the plug while it is plugged in, looking down at the
board's component side with J1 along the top edge (as in the assembly
drawing). Pin 1 is top left; pins 1-10 run left to right along the row
nearest the board edge, 11-20 below them. Speaker pins checked on board 2
(BRINGUP.md stage 7). Wires come from the Klintotour Toyota adapter's
16-pin Android end (cut off), which uses the usual Android colour code:
the EIA power and speaker colours plus brown / brown-white for the wheel.

    .venv/bin/python tools/harness_diagram.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Polygon, Rectangle

OUT = Path(__file__).resolve().parent.parent / "out" / "harness.png"

C = {"yellow": "#f2d600", "black": "#222222", "red": "#d62828", "orange": "#f77f00",
     "white": "#f4f4f4", "gray": "#9a9a9a", "purple": "#7b2cbf", "green": "#2b9348",
     "pink": "#ff8fab", "none": "#d9d9d9", "brown": "#7f4f24"}

# pin: (signal, short label, wire colour, stripe colour or None, where it comes from)
PINS = {
    1: ("+12 V constant", "+12V", "yellow", None, "Yellow (split: one lead to 1, one to 11)"),
    2: ("Ground", "GND", "black", None, "Black (split to 2, 12, 19)"),
    3: ("Front right +", "FR+", "gray", None, "Gray"),
    4: ("Front left +", "FL+", "white", None, "White"),
    5: ("Rear right +", "RR+", "purple", None, "Purple"),
    6: ("Rear left +", "RL+", "green", None, "Green"),
    7: ("Key / ACC", "ACC", "red", None, "Red"),
    8: ("Steering wheel 1 (seek, volume)", "KEY1", "brown", None, "Brown (Toyota 20-pin #7, SW1)"),
    9: ("Steering wheel ground", "(SWC GND)", "none", None, "Leave empty: the adapter ties the wheel ground (20-pin #6) to black"),
    10: ("Reverse (+12 V in reverse)", "REV", "pink", None, "Pink loose lead tagged BACK, spliced to the reverse light feed"),
    11: ("+12 V constant", "+12V", "yellow", None, "Yellow (second lead)"),
    12: ("Ground", "GND", "black", None, "Black (second lead)"),
    13: ("Front right -", "FR-", "gray", "black", "Gray/black"),
    14: ("Front left -", "FL-", "white", "black", "White/black"),
    15: ("Rear right -", "RR-", "purple", "black", "Purple/black"),
    16: ("Rear left -", "RL-", "green", "black", "Green/black"),
    17: ("Headlights / illumination", "ILLUM", "orange", None, "Orange"),
    18: ("Steering wheel 2 (mode)", "KEY2", "brown", "white", "Brown/white (Toyota 20-pin #8, SW2)"),
    19: ("Ground", "GND", "black", None, "Black (third lead)"),
    20: ("Not used", "-", "none", None, "Leave empty"),
}


def cavity(ax, x, y, pin):
    sig, short, col, stripe, _ = PINS[pin]
    ax.add_patch(FancyBboxPatch((x, y), 1, 1, boxstyle="round,pad=0,rounding_size=0.12",
                                fc=C[col], ec="#333333", lw=1.5))
    if stripe:                                   # tracer stripe: bands down both sides
        for sx in (x + 0.06, x + 0.82):
            ax.add_patch(Rectangle((sx, y + 0.1), 0.12, 0.8, fc=C[stripe], ec="none"))
    dark = col in ("black", "purple", "green", "red", "brown")
    tc = "white" if dark else "black"
    ax.text(x + 0.5, y + 0.68, str(pin), ha="center", va="center", fontsize=13, weight="bold", color=tc)
    ax.text(x + 0.5, y + 0.3, short, ha="center", va="center", fontsize=7.5, color=tc)


def main():
    fig = plt.figure(figsize=(13, 10.4), dpi=150)
    ax = fig.add_axes([0.03, 0.58, 0.94, 0.4])
    ax.set_xlim(-0.6, 13.2)
    ax.set_ylim(-1.3, 3.6)
    ax.set_aspect("equal")
    ax.axis("off")
    # Housing outline with its notches: a large one in the middle of the side
    # toward the board, two small ones set in from the ends on the board-edge
    # side. Sizes are drawn to show where they are, not to scale.
    x0, x1, y0, y1, d = -0.35, 12.1, -0.3, 2.65, 0.22
    big, small_w = (5.9, 2.4), 0.7
    smalls = (1.8, 10.0)                          # between pins 2/3 and 8/9
    pts = [(x0, y0), (big[0] - big[1] / 2, y0), (big[0] - big[1] / 2, y0 + d),
           (big[0] + big[1] / 2, y0 + d), (big[0] + big[1] / 2, y0), (x1, y0), (x1, y1)]
    for cx in sorted(smalls, reverse=True):
        pts += [(cx + small_w / 2, y1), (cx + small_w / 2, y1 - d), (cx - small_w / 2, y1 - d),
                (cx - small_w / 2, y1)]
    pts += [(x0, y1)]
    ax.add_patch(Polygon(pts, closed=True, fc="#efefef", ec="#555555", lw=2, joinstyle="round"))
    ax.text(big[0], y0 - 0.25, "large notch (board side)", fontsize=9, ha="center", va="top")
    for cx in smalls:
        ax.text(cx, y1 + 0.12, "small notch", fontsize=9, ha="center", va="bottom")
    for i in range(10):
        cavity(ax, i * 1.2, 1.35, i + 1)          # pins 1-10, nearest the board edge
        cavity(ax, i * 1.2, 0.0, i + 11)          # pins 11-20
    ax.annotate("", xy=(12.6, 2.75), xytext=(12.6, 1.2), arrowprops=dict(arrowstyle="->", lw=1.5))
    ax.text(12.75, 1.9, "board\nedge", fontsize=9, ha="left", va="center")
    ax.text(-0.3, 3.25, "J1 harness plug: WIRE side, plugged in, board viewed from above (J1 along the top edge)",
            fontsize=12, weight="bold")
    ax.text(-0.3, -1.05, "Pin 1 = top left. Check against the numbers moulded on the Molex housing before "
            "pushing pins in. The plug is keyed, so it only mates one way.", fontsize=9.5)

    tx = fig.add_axes([0.03, 0.1, 0.94, 0.46])
    tx.axis("off")
    rows = [[str(p), s[0], s[4]] for p, s in PINS.items()]
    tab = tx.table(cellText=rows, colLabels=["Pin", "Signal", "Adapter wire (16-pin Android end, plug cut off)"], loc="upper left",
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
            cell.set_text_props(color="white" if col in ("black", "purple", "green", "red", "brown") else "black",
                                weight="bold")
    fig.text(0.04, 0.075, "Not used: blue (antenna / amp remote) and anything else on the 16-pin. Cap them. "
            "Colours, not positions in the 16-pin shell,\nidentify the wires; check KEY1/KEY2 with a meter "
            "(resistance to black changes with the wheel buttons).\nUse 18 AWG pre-crimped Micro-Fit leads "
            "(Molex 2147611124); solder and heat-shrink each joint. Before plugging in: no continuity "
            "between +12 V (1, 11) and ground (2, 12, 19).", fontsize=9, va="top")
    OUT.parent.mkdir(exist_ok=True)
    fig.savefig(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
