#!/usr/bin/env python3
"""Plot out/pcb/dump.json (tools/dump_pcb.py) for review.

    .venv/bin/python tools/view_pcb.py NAME [x0 y0 x1 y1] [--layers F,In1,In2,B] [--nets TEXT,...] [--labels]

Board mm from the top-left corner. Colours: F.Cu red, B.Cu blue, In1 green,
In2 orange; ratsnest thin black; zone fills translucent.
"""
import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection, PolyCollection  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
COL = {"F.Cu": "#c83232", "B.Cu": "#3c64c8", "In1.Cu": "#2e9a4a", "In2.Cu": "#d98a1a"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("box", nargs="*", type=float)
    ap.add_argument("--layers", default="F,In1,In2,B")
    ap.add_argument("--nets", default="")
    ap.add_argument("--labels", action="store_true")
    ap.add_argument("--norats", action="store_true")
    a = ap.parse_args()
    layers = [f"{l}.Cu" for l in a.layers.split(",")]
    nets = [n for n in a.nets.split(",") if n]
    want = (lambda n: any(t in n for t in nets)) if nets else (lambda n: True)
    d = json.load(open(os.path.join(ROOT, "out", "pcb", "dump.json")))
    x0, y0, x1, y1 = a.box if a.box else (-2, -2, 167, 105)
    scale = 1400 / max(x1 - x0, y1 - y0)
    fig = plt.figure(figsize=((x1 - x0) * scale / 100, (y1 - y0) * scale / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.add_collection(LineCollection([e for e in d["edges"]], colors="#888", linewidths=1))
    # draw inner layers first, then B, then F on top
    order = [l for l in ("In1.Cu", "In2.Cu", "B.Cu", "F.Cu") if l in layers]
    for layer in order:
        for z in d["zones"]:
            if z["layer"] != layer:
                continue
            if z["keepout"]:
                ax.add_collection(PolyCollection(z["outline"], facecolors="none", edgecolors="#aa00aa",
                                                 linestyles="dashed", linewidths=0.8))
                continue
            if not want(z["net"]):
                continue
            ax.add_collection(PolyCollection(z["fill"] or z["outline"], facecolors=COL[layer],
                                             alpha=0.18 if z["fill"] else 0.05, edgecolors=COL[layer],
                                             linewidths=0.3))
        segs = [(t["a"], t["b"]) for t in d["tracks"] if t["layer"] == layer and want(t["net"])]
        ws = [t["w"] * scale * 0.72 for t in d["tracks"] if t["layer"] == layer and want(t["net"])]
        ax.add_collection(LineCollection(segs, colors=COL[layer], linewidths=ws, capstyle="round", alpha=0.85))
        pads = [p for p in d["pads"] if layer in p["layers"] and layer in ("F.Cu", "B.Cu")
                and (len(p["layers"]) == 1 or layer == "F.Cu")]
        ax.add_collection(PolyCollection([o for p in pads for o in p["poly"]],
                                         facecolors=[COL[layer] if want(p["net"]) or not nets else "#ddd"
                                                     for p in pads for _ in p["poly"]],
                                         edgecolors="none", alpha=0.9))
    for p in d["pads"]:
        if p["drill"] > 0:
            ax.add_patch(plt.Circle(p["pos"], p["drill"] / 2, color="white", zorder=5))
    for v in d["vias"]:
        if want(v["net"]):
            ax.add_patch(plt.Circle(v["pos"], v["d"] / 2, color="#777", zorder=6))
            ax.add_patch(plt.Circle(v["pos"], v["d"] / 4, color="white", zorder=7))
    if not a.norats:
        rats = [(r["a"], r["b"]) for r in d["rats"] if want(r["net"])]
        ax.add_collection(LineCollection(rats, colors="black", linewidths=0.5, zorder=8))
    if a.labels:
        for f in d["fps"]:
            if x0 <= f["pos"][0] <= x1 and y0 <= f["pos"][1] <= y1:
                ax.text(*f["pos"], f["ref"], fontsize=7, ha="center", va="center", zorder=9,
                        color="#003" if not f["bottom"] else "#630")
        if a.box:
            for p in d["pads"]:
                if x0 <= p["pos"][0] <= x1 and y0 <= p["pos"][1] <= y1 and p["net"]:
                    ax.text(*p["pos"], p["net"].lstrip("/")[:10], fontsize=4.5, ha="center", va="center",
                            zorder=9, color="#050")
    out = os.path.join(ROOT, "out", "pcb", f"{a.name}.png")
    fig.savefig(out, facecolor="white")
    print(os.path.relpath(out))


if __name__ == "__main__":
    main()
