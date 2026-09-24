#!/usr/bin/env python3
"""Finish what the autorouter left open: read the unconnected pairs from
out/drc.json and maze-route each one on the routed board (tools/maze.py),
then refill the pours.

    flatpak run --command=python3 org.kicad.KiCad tools/finish.py
"""
import json
import os
import re
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
import maze  # noqa: E402
import route  # noqa: E402

LAYER = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}


def ends(item):
    """(x, y) and the layers a route may start/end on for a DRC item."""
    d = item["description"]
    x, y = item["pos"]["x"] - route.OX, item["pos"]["y"] - route.OY
    if d.startswith("PTH pad") or d.startswith("Via"):
        return (x, y), (pcbnew.F_Cu, pcbnew.B_Cu)
    m = re.search(r" on ([FB]\.Cu)", d)
    return (x, y), (LAYER[m.group(1)],) if m else (pcbnew.F_Cu,)


BAD = ("shorting_items", "tracks_crossing", "clearance", "hole_clearance", "copper_edge_clearance")


def repair():
    """Delete autorouted (unlocked) tracks and vias that DRC flags as shorts
    or clearance errors; the next finishing pass routes those links again.
    Hand-placed copper is locked and never touched."""
    b = pcbnew.LoadBoard(route.PCB)
    d = json.load(open(os.path.join(ROOT, "out", "drc.json")))
    bad = {i["uuid"] for v in d["violations"] if v["type"] in BAD for i in v["items"]}
    gone = 0
    for t in list(b.GetTracks()):
        if t.m_Uuid.AsString() in bad and not t.IsLocked():
            b.Remove(t)
            gone += 1
    b.Save(route.PCB)
    print(f"finish: repair removed {gone} autorouted segments")


def main():
    if sys.argv[1:] == ["repair"]:
        return repair()
    b = pcbnew.LoadBoard(route.PCB)
    route.board = b
    route.FPS.update({f.GetReference(): f for f in b.GetFootprints()})
    d = json.load(open(os.path.join(ROOT, "out", "drc.json")))
    done = 0
    for u in d["unconnected_items"]:
        a, z = u["items"]
        if a["description"].startswith("Zone") or z["description"].startswith("Zone"):
            print("finish: skipped (pour):", a["description"][:40], "|", z["description"][:40])
            continue
        net = re.search(r"\[(.*?)\]", a["description"]).group(1)
        (pa, la), (pz, lz) = ends(a), ends(z)
        path = None
        for margin in (4.0, 10.0, 20.0):
            path = maze.route(b, net, pa, pz, route.OX, route.OY, width=0.2, margin=margin,
                              start_layers=la, end_layers=lz)
            if path:
                break
        if not path:
            import math
            # any other pad of the net will do, nearest first, skipping ones
            # close to the start (most likely on the same island)
            import math
            if net == "+3V3":                          # the island is far from the rest: aim at the LDO
                # start from whichever end is farther from the LDO (the island)
                ldo = route.pad("U6", next(p.GetNumber() for p in route.FPS["U6"].Pads() if p.GetNetname() == net))
                if math.dist(pa, ldo) < math.dist(pz, ldo):
                    pa, la = pz, lz
                alts = [(0.0, "U6", next(p for p in route.FPS["U6"].Pads() if p.GetNetname() == net))]
                for dist, r, p in alts:
                    q = route.pad(r, p.GetNumber())
                    path = maze.route(b, net, pa, q, route.OX, route.OY, width=0.2, margin=14.0,
                                      start_layers=la, end_layers=(pcbnew.F_Cu,))
                    if path:
                        pz = q
            alts = [] if path else sorted(((math.dist(pa, route.pad(r, p.GetNumber())), r, p) for r, f in route.FPS.items()
                           for p in f.Pads() if p.GetNetname() == net), key=lambda t: t[0])
            for dist, r, p in [t for t in alts if t[0] > 15.0][:6]:
                q = route.pad(r, p.GetNumber())
                ql = (pcbnew.F_Cu, pcbnew.B_Cu) if p.GetDrillSizeX() else (pcbnew.F_Cu,)
                path = maze.route(b, net, pa, q, route.OX, route.OY, width=0.2, margin=8.0,
                                  start_layers=la, end_layers=ql)
                if path:
                    pz = q
                    break
        if not path:
            print(f"finish: {net} {pa} -> {pz} not found", flush=True)
            continue
        path = maze.simplify(path)
        pts = [(pa[0], pa[1], path[0][2])] + path + [(pz[0], pz[1], path[-1][2])]
        for (xa, ya, la_), (xb, yb, lb) in zip(pts, pts[1:]):
            if la_ != lb:
                P = route.V(xa, ya)
                if not any(t.GetClass() == "PCB_VIA" and t.GetNetname() == net and
                           (t.GetPosition() - P).EuclideanNorm() < pcbnew.FromMM(0.7) for t in b.GetTracks()):
                    route.via(net, xa, ya)
            elif (xa, ya) != (xb, yb):
                route.track(net, la_, 0.2, [(xa, ya), (xb, yb)])
        done += 1
        print(f"finish: {net} routed ({len(path)} points)", flush=True)
    b.BuildConnectivity()
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(route.PCB)
    print(f"finish: {done} of {len(d['unconnected_items'])} links routed")


if __name__ == "__main__":
    main()
