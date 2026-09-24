#!/usr/bin/env python3
"""Route the signals route.py leaves open, with Freerouting.

    flatpak run --command=python3 org.kicad.KiCad tools/autoroute.py export
    java -jar ~/.local/share/freerouting/freerouting-2.4.1.jar -de out/route/carrier.dsn \\
         -do out/route/carrier.ses -mp 40 --gui.enabled=false
    flatpak run --command=python3 org.kicad.KiCad tools/autoroute.py import

(tools/build_board.sh runs the whole chain.) The hand-routed tracks, vias
and pours from route.py are locked, so Freerouting treats them as fixed.
"""
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
PCB = os.path.join(ROOT, "carrier.kicad_pcb")
OUT = os.path.join(ROOT, "out", "route")
DSN = os.path.join(OUT, "carrier.dsn")
SES = os.path.join(OUT, "carrier.ses")


def guard_pours(b, inset=0.6):
    """Freerouting treats an outer-layer pour as copper of its own net but
    will still drop other nets' vias and tracks through it, splitting it.
    Cover each hand-made pour with a keepout set `inset` mm inside its edge:
    other nets stay out, while the pour's own net can still reach the edge
    band. Pours too narrow to shrink are left alone. Only for the export;
    the board is not saved afterwards."""
    n = 0
    for z in list(b.Zones()):
        if z.GetIsRuleArea() or z.GetAssignedPriority() == 0 or z.GetLayer() not in (pcbnew.F_Cu, pcbnew.B_Cu):
            continue
        # narrow pours (the SW node) get a thin guard rather than none
        for d in (inset, 0.15):
            poly = pcbnew.SHAPE_POLY_SET(z.Outline())
            poly.Inflate(-pcbnew.FromMM(d), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, pcbnew.FromMM(0.01))
            if poly.OutlineCount() and min(poly.BBox().GetWidth(), poly.BBox().GetHeight()) >= pcbnew.FromMM(0.5):
                break
        else:
            continue
        # built point by point with a layer set, like route.py's keepouts: a
        # rule area given a SHAPE_POLY_SET directly crashes the DSN exporter
        k = pcbnew.ZONE(b)
        k.SetIsRuleArea(True)
        ls = pcbnew.LSET()
        ls.AddLayer(z.GetLayer())
        k.SetLayerSet(ls)
        ol = k.Outline()
        for i in range(poly.OutlineCount()):
            chain = poly.Outline(i)
            ol.NewOutline()
            for j in range(chain.PointCount()):
                q = chain.CPoint(j)
                ol.Append(q.x, q.y)
        k.SetZoneName(f"guard {z.GetZoneName()}")
        k.SetDoNotAllowTracks(True)
        k.SetDoNotAllowVias(True)
        k.SetDoNotAllowZoneFills(False)
        k.SetDoNotAllowPads(False)
        k.SetDoNotAllowFootprints(False)
        b.Add(k)
        n += 1
    return n


def main():
    os.makedirs(OUT, exist_ok=True)
    b = pcbnew.LoadBoard(PCB)
    if sys.argv[1] == "export":
        # a board that was routed before carries the outer GND pours; to the
        # router they would read as solid copper over both routing layers
        for z in list(b.Zones()):
            if z.GetZoneName() in ("GND top", "GND bottom"):
                b.Remove(z)
        n = guard_pours(b)
        if not pcbnew.ExportSpecctraDSN(b, DSN):
            raise SystemExit("DSN export failed")
        print(f"{os.path.relpath(DSN)}: {n} outer-layer pours guarded")      # board not saved
    elif sys.argv[1] == "import":
        if not pcbnew.ImportSpecctraSES(b, SES):
            raise SystemExit("SES import failed")
        sys.path.insert(0, HERE)
        import route
        if not any(z.GetZoneName() == "GND top" for z in b.Zones()):
            route.outer_gnd(b)
        b.BuildConnectivity()
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
        b.Save(PCB)
        print(f"imported {os.path.relpath(SES)}: {len(b.GetTracks())} tracks/vias")


if __name__ == "__main__":
    main()
