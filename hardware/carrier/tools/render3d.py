#!/usr/bin/env python3
"""Shaded PNG views of the 3D assembly (tools/assembly.py) for review.

    .venv/bin/python tools/render3d.py   ->  out/3d/{iso,back,side,top}.png
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import assembly  # noqa: E402

OUT = os.path.join(HERE, "..", "out", "3d")
LIGHT = np.array([0.4, -0.5, 0.8])
LIGHT /= np.linalg.norm(LIGHT)
VIEWS = {"iso": (28, -55), "iso2": (28, -125), "back": (90, -90), "side": (0, 0), "top": (0, -90)}


def meshes():
    asm = assembly.build()
    out = []
    for name, node in asm.traverse():
        if node.obj is None:
            continue
        col = node.color.toTuple()[:3] if node.color else (0.35, 0.55, 0.35)
        shapes = node.obj.vals() if hasattr(node.obj, "vals") else [node.obj]
        loc = node.loc
        for sh in shapes:
            sh = sh.moved(loc) if loc else sh
            verts, tris = sh.tessellate(0.3, 0.5)
            if not tris:
                continue
            v = np.array([(p.x, p.y, p.z) for p in verts])
            out.append((name, col, v[np.array(tris)]))
    return out


def shade(tris, col):
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    k = 0.35 + 0.65 * np.abs(n @ LIGHT)
    return np.clip(np.outer(k, col), 0, 1)


def main():
    os.makedirs(OUT, exist_ok=True)
    ms = meshes()
    allv = np.concatenate([t.reshape(-1, 3) for _, _, t in ms])
    lo, hi = allv.min(0), allv.max(0)
    for view, (elev, azim) in VIEWS.items():
        fig = plt.figure(figsize=(13, 9), dpi=110)
        ax = fig.add_subplot(111, projection="3d", computed_zorder=True)
        # one collection, so matplotlib depth-sorts every triangle together
        tris = np.concatenate([t for _, _, t in ms])
        cols = np.concatenate([shade(t, np.array(col)) for _, col, t in ms])
        ax.add_collection3d(Poly3DCollection(tris, facecolors=cols, edgecolors="none"))
        ax.set_xlim(lo[0], hi[0])
        ax.set_ylim(lo[1], hi[1])
        ax.set_zlim(lo[2], hi[2])
        ax.set_box_aspect(hi - lo)
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        fig.tight_layout()
        p = os.path.join(OUT, f"{view}.png")
        fig.savefig(p, facecolor="white")
        plt.close(fig)
        print(os.path.relpath(p))


if __name__ == "__main__":
    main()
