#!/usr/bin/env python3
"""Move vias off SMD pads (PCBWay flags via-in-pad: solder wicks down the
barrel unless the via is filled and capped, which costs extra).

Each via whose copper touches an SMD pad moves to the nearest free spot just
clear of that pad, joined by a top-layer stub from the pad centre. The tracks
that met it on the other layers stay where they are and get a short jog from
the old spot to the new one on the bottom layer. Every new piece of copper is
checked against other nets with CLR to spare.

    flatpak run --command=python3 org.kicad.KiCad tools/via_off_pad.py          # fix
    flatpak run --command=python3 org.kicad.KiCad tools/via_off_pad.py check    # list only, exit 1 if any
"""
import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import maze  # noqa: E402
import route  # noqa: E402

F, B = pcbnew.F_Cu, pcbnew.B_Cu
CLR = 0.2           # to other nets (net classes use 0.15-0.2)
HOLE_GAP = 0.15     # a via hole closer than this to an SMD pad gets moved
GAP = 0.05          # ... until its copper clears the pad by this (hole by 0.2)
MARGIN = 8.0       # maze fallback search box around the pad (mm)
mm, to = pcbnew.FromMM, pcbnew.ToMM


def P(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def smd_pads(board):
    return [p for fp in board.GetFootprints() for p in fp.Pads()
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]


def offenders(board):
    """(via, pad) for every via whose hole is within HOLE_GAP of an SMD pad:
    inside it, or so close that no solder mask is left between them."""
    pads = smd_pads(board)
    out = []
    for v in board.GetTracks():
        if v.Type() != pcbnew.PCB_VIA_T:
            continue
        r = v.GetDrillValue() // 2 + mm(HOLE_GAP)
        for p in pads:
            lay = F if p.IsOnLayer(F) else B
            if p.GetEffectivePolygon(lay, pcbnew.ERROR_INSIDE).Collide(v.GetPosition(), r):
                out.append((v, p))
                break
    return out


def free(board, net, pt, r, layers, skip=()):
    """True if a circle of radius r (mm) at pt clears all copper of other nets
    on `layers` by CLR, plus every hole and keepout."""
    c = P(*pt)
    reach = mm(r + CLR)
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetDrillSizeX() and (p.GetPosition() - c).EuclideanNorm() < p.GetDrillSizeX() // 2 + mm(r + 0.25):
                if p.GetNetname() != net or not p.IsOnLayer(F):
                    return False
            if p.GetNetname() == net:
                continue
            for lay in layers:
                if p.IsOnLayer(lay) and p.GetEffectivePolygon(lay, pcbnew.ERROR_INSIDE).Collide(c, reach):
                    return False
    for t in board.GetTracks():
        if t.m_Uuid.AsString() in skip:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            # hole to hole for every via, copper clearance for other nets
            gap = t.GetWidth(F) // 2 + reach if t.GetNetname() != net else t.GetDrillValue() // 2 + mm(r + 0.25)
            if (t.GetPosition() - c).EuclideanNorm() < gap:
                return False
        elif t.GetNetname() != net and t.GetLayer() in layers and t.HitTest(c, reach):
            return False
    for z in board.Zones():
        if z.GetIsRuleArea():
            if (z.GetDoNotAllowVias() or z.GetDoNotAllowTracks()) and z.Outline().Collide(c, reach):
                return False
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts and d.HitTest(c, mm(r + 0.5)):
            return False
    return True


def seg_free(board, net, a, b, w, layer, skip=()):
    n = max(2, int(math.dist(a, b) / 0.05))
    return all(free(board, net, (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n), w / 2, (layer,), skip)
               for i in range(n + 1))


def width_at(board, v, layer):
    """Widest track on `layer` ending at via v, or None if none does."""
    ws = [t.GetWidth() for t in board.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T and t.GetLayer() == layer and
          v.GetPosition() in (t.GetStart(), t.GetEnd())]
    return to(max(ws)) if ws else None


def move(board, v, p):
    net = v.GetNetname()
    ox, oy = to(v.GetPosition().x), to(v.GetPosition().y)
    px, py = to(p.GetPosition().x), to(p.GetPosition().y)
    lay = F if p.IsOnLayer(F) else B
    other = B if lay == F else F
    poly = p.GetEffectivePolygon(lay, pcbnew.ERROR_INSIDE)
    vr = to(v.GetWidth(F)) / 2
    wf = width_at(board, v, lay) or 0.25
    wb = width_at(board, v, other)      # None: nothing meets it there (pours only), no jog needed
    fp = p.GetParentFootprint()
    cx, cy = to(fp.GetPosition().x), to(fp.GetPosition().y)
    away = math.atan2(py - cy, px - cx) if (px, py) != (cx, cy) else 0.0
    dirs = sorted(range(16), key=lambda k: abs(math.remainder(k * math.pi / 8 - away, 2 * math.pi)))
    best = None
    for k in dirs:
        a = k * math.pi / 8
        ux, uy = math.cos(a), math.sin(a)
        # step out until the via copper clears the pad by GAP
        d = 0.0
        while poly.Collide(P(px + ux * d, py + uy * d), mm(vr + GAP)):
            d += 0.025
        for extra in (0.0, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0):
            q = (px + ux * (d + extra), py + uy * (d + extra))
            if not free(board, net, q, vr, (F, B), skip=(v.m_Uuid.AsString(),)):
                continue
            if not seg_free(board, net, (px, py), q, wf, lay, skip=(v.m_Uuid.AsString(),)):
                continue
            if wb and not seg_free(board, net, (ox, oy), q, wb, other, skip=(v.m_Uuid.AsString(),)):
                continue
            cost = math.dist((px, py), q) + math.dist((ox, oy), q)
            if best is None or cost < best[0]:
                best = (cost, q)
            break
    if best is None:
        return reroute(board, v, (px, py), (ox, oy), lay, other, wb or wf)
    q = best[1]
    nv = v.Duplicate()
    nv.SetPosition(P(*q))
    board.Remove(v)
    board.Add(nv)
    route.board = board
    for (a, b, w, layer) in (((px, py), q, wf, lay), ((ox, oy), q, wb, other)):
        if not w:
            continue
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(P(*a))
        t.SetEnd(P(*b))
        t.SetWidth(mm(w))
        t.SetLayer(layer)
        t.SetNet(nv.GetNet())
        t.SetLocked(True)
        board.Add(t)
    return (ox, oy), q


def reroute(board, v, pad_xy, old_xy, lay, other, w):
    """No straight spot: drop the via and let the maze router (which keeps
    vias off pads) join the pad to where the via's other-layer tracks met."""
    net = v.GetNetname()
    uid = v.m_Uuid.AsString()
    board.Remove(v)
    rel = lambda p: (p[0] - route.OX, p[1] - route.OY)  # noqa: E731
    path = maze.route(board, net, rel(pad_xy), rel(old_xy), route.OX, route.OY, width=w, margin=MARGIN,
                      start_layers=(lay,), end_layers=(other,))
    if not path:
        board.Add(v)
        return None
    path = maze.simplify(path)
    pts = [(*rel(pad_xy), path[0][2])] + path + [(*rel(old_xy), path[-1][2])]
    route.board = board
    placed = None
    for (xa, ya, la), (xb, yb, lb) in zip(pts, pts[1:]):
        if la != lb:
            placed = (xa + route.OX, ya + route.OY)
            if not any(t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == net and
                       (t.GetPosition() - P(*placed)).EuclideanNorm() < mm(0.3) for t in board.GetTracks()):
                route.via(net, xa, ya, d=to(v.GetWidth(F)), drill=to(v.GetDrillValue()))
        elif (xa, ya) != (xb, yb):
            route.track(net, la, w, [(xa, ya), (xb, yb)])
    print(f"  (maze route, old via {uid[:8]} removed)")
    return old_xy, placed


def main():
    board = pcbnew.LoadBoard(route.PCB)
    found = offenders(board)
    for v, p in found:
        fp = p.GetParentFootprint()
        print(f"via-in-pad: {fp.GetReference()} pad {p.GetNumber()} {v.GetNetname()} "
              f"at ({to(v.GetPosition().x) - route.OX:.2f}, {to(v.GetPosition().y) - route.OY:.2f})")
    if sys.argv[1:] == ["check"]:
        sys.exit(1 if found else 0)
    moved = 0
    for v, p in found:
        fp = p.GetParentFootprint()
        r = move(board, v, p)
        if r is None:
            print(f"  {fp.GetReference()} pad {p.GetNumber()}: no free spot, left in place")
            continue
        (ox, oy), (qx, qy) = r
        print(f"  {fp.GetReference()} pad {p.GetNumber()}: moved {math.dist((ox, oy), (qx, qy)):.2f} mm "
              f"to ({qx - route.OX:.2f}, {qy - route.OY:.2f})")
        moved += 1
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(route.PCB)
    print(f"via_off_pad: moved {moved} of {len(found)}")


if __name__ == "__main__":
    main()
