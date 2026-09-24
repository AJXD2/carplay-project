#!/usr/bin/env python3
"""Dump carrier.kicad_pcb geometry to out/pcb/dump.json for view_pcb.py.

    flatpak run --command=python3 org.kicad.KiCad tools/dump_pcb.py
"""
import json
import os

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
ORIGIN = (100.0, 100.0)
LAYERS = {pcbnew.F_Cu: "F.Cu", pcbnew.In1_Cu: "In1.Cu", pcbnew.In2_Cu: "In2.Cu", pcbnew.B_Cu: "B.Cu"}


def xy(v):
    return [round(pcbnew.ToMM(v.x) - ORIGIN[0], 4), round(pcbnew.ToMM(v.y) - ORIGIN[1], 4)]


def poly(shape_poly):
    out = []
    for i in range(shape_poly.OutlineCount()):
        o = shape_poly.Outline(i)
        out.append([xy(o.CPoint(j)) for j in range(o.PointCount())])
    return out


def main():
    b = pcbnew.LoadBoard(os.path.join(ROOT, "carrier.kicad_pcb"))
    d = {"pads": [], "tracks": [], "vias": [], "zones": [], "rats": [], "edges": [], "fps": []}
    for fp in b.GetFootprints():
        d["fps"].append({"ref": fp.GetReference(), "pos": xy(fp.GetPosition()), "bottom": fp.IsFlipped()})
        for p in fp.Pads():
            layers = [n for k, n in LAYERS.items() if p.IsOnLayer(k)]
            sp = p.GetEffectivePolygon(pcbnew.F_Cu if "F.Cu" in layers else pcbnew.B_Cu, pcbnew.ERROR_INSIDE)
            d["pads"].append({"ref": fp.GetReference(), "num": p.GetNumber(), "net": p.GetNetname(),
                              "layers": layers, "poly": poly(sp), "pos": xy(p.GetPosition()),
                              "drill": pcbnew.ToMM(p.GetDrillSizeX())})
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            d["vias"].append({"pos": xy(t.GetPosition()), "d": pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)),
                              "net": t.GetNetname()})
        else:
            d["tracks"].append({"a": xy(t.GetStart()), "b": xy(t.GetEnd()), "w": pcbnew.ToMM(t.GetWidth()),
                                "layer": b.GetLayerName(t.GetLayer()), "net": t.GetNetname()})
    for z in b.Zones():
        for layer in z.GetLayerSet().Seq():
            if layer not in LAYERS:
                continue
            fill = z.GetFilledPolysList(layer) if z.IsFilled() else None
            d["zones"].append({"net": z.GetNetname(), "layer": LAYERS[layer], "keepout": z.GetIsRuleArea(),
                               "outline": poly(z.Outline()), "fill": poly(fill) if fill else []})
    for dr in b.GetDrawings():
        if dr.GetLayer() == pcbnew.Edge_Cuts:
            d["edges"].append([xy(dr.GetStart()), xy(dr.GetEnd())])
    # unrouted links come from DRC (the ratsnest API is not wrapped)
    rpt = os.path.join(ROOT, "out", "drc.json")
    if os.path.exists(rpt):
        for v in json.load(open(rpt)).get("unconnected_items", []):
            it = v["items"]
            if len(it) == 2:
                d["rats"].append({"a": [it[0]["pos"]["x"] - ORIGIN[0], it[0]["pos"]["y"] - ORIGIN[1]],
                                  "b": [it[1]["pos"]["x"] - ORIGIN[0], it[1]["pos"]["y"] - ORIGIN[1]],
                                  "net": it[0]["description"]})
    out = os.path.join(ROOT, "out", "pcb", "dump.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(d, open(out, "w"))
    print(f"{len(d['pads'])} pads, {len(d['tracks'])} tracks, {len(d['vias'])} vias, "
          f"{len(d['zones'])} zone layers, {len(d['rats'])} unrouted")


if __name__ == "__main__":
    main()
