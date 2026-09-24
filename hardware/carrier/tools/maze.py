"""Small two-layer grid router for the few nets Freerouting cannot finish in
the crowded corners (used by route.py before the autorouter runs).

A* on a square grid over the connection's bounding box, top and bottom
layers, vias allowed at a cost. Obstacles are every pad, track, via, pour
and keepout that is not on the net being routed, grown by the track's half
width plus clearance. Results are locked tracks and vias like the rest of
route.py, so Freerouting routes around them.
"""
import heapq
import math

import pcbnew

GRID = 0.25
CLR = 0.2
VIA_D, VIA_DRILL = 0.6, 0.3
VIA_COST = 6.0


class Obstacles:
    def __init__(self, board, netname, ox, oy):
        self.ox, self.oy = ox, oy
        self.items = {pcbnew.F_Cu: [], pcbnew.B_Cu: []}
        self.drills, self.areas, self.edges = [], [], []
        for fp in board.GetFootprints():
            for p in fp.Pads():
                own = p.GetNetname() == netname
                for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                    if p.IsOnLayer(layer) and not own:
                        self.items[layer].append(("poly", p.GetEffectivePolygon(layer, pcbnew.ERROR_INSIDE)))
                if p.GetDrillSizeX() and not own:
                    self.drills.append((p.GetPosition(), p.GetDrillSizeX() // 2))
        for t in board.GetTracks():
            if t.GetNetname() == netname:
                continue
            if t.GetClass() == "PCB_VIA":
                for layer in self.items:
                    self.items[layer].append(("circle", (t.GetPosition(), t.GetWidth(pcbnew.F_Cu) // 2)))
            elif t.GetLayer() in self.items:
                self.items[t.GetLayer()].append(("track", t))
        for z in board.Zones():
            if z.GetIsRuleArea():
                self.areas.append(z.Outline())
            elif z.GetLayer() in self.items and z.GetNetname() != netname and z.GetAssignedPriority() > 0:
                self.items[z.GetLayer()].append(("poly", z.Outline()))
        for dr in board.GetDrawings():
            if dr.GetLayer() == pcbnew.Edge_Cuts:
                self.edges.append(dr)
        self.cache = {}

    def free(self, x, y, layer, r):
        key = (round(2 * x / GRID), round(2 * y / GRID), layer, r)     # half-grid: diagonal midpoints
        if key in self.cache:
            return self.cache[key]
        P = pcbnew.VECTOR2I(pcbnew.FromMM(self.ox + x), pcbnew.FromMM(self.oy + y))
        reach = pcbnew.FromMM(r + CLR)
        ok = True
        for kind, obj in self.items[layer]:
            if kind == "poly":
                hit = obj.Collide(P, reach)
            elif kind == "circle":
                hit = (obj[0] - P).EuclideanNorm() < reach + obj[1]
            else:
                hit = obj.HitTest(P, reach)
            if hit:
                ok = False
                break
        if ok:
            ok = not any(a.Collide(P, reach) for a in self.areas) and \
                not any(e.HitTest(P, pcbnew.FromMM(r + 0.5)) for e in self.edges) and \
                not any((c - P).EuclideanNorm() < rad + reach + pcbnew.FromMM(0.1) for c, rad in self.drills)
        self.cache[key] = ok
        return ok


def route(board, netname, a, b, ox, oy, width=0.25, margin=6.0, layers=(pcbnew.F_Cu, pcbnew.B_Cu),
          start_layers=None, end_layers=None):
    """Grid A* from a to b (board mm). Returns [(x, y, layer)] or None."""
    obs = Obstacles(board, netname, ox, oy)
    r = width / 2
    x0, x1 = min(a[0], b[0]) - margin, max(a[0], b[0]) + margin
    y0, y1 = min(a[1], b[1]) - margin, max(a[1], b[1]) + margin

    def cell(p):
        return round(p[0] / GRID), round(p[1] / GRID)

    sa, sb = cell(a), cell(b)
    starts = start_layers or layers
    ends = set(end_layers or layers)
    openq, came, cost = [], {}, {}
    for layer in starts:
        s = (sa[0], sa[1], layer)
        cost[s] = 0.0
        heapq.heappush(openq, (0.0, s))
    steps = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
    while openq:
        _, cur = heapq.heappop(openq)
        cx, cy, cl = cur
        if (cx, cy) == sb and cl in ends:
            path = [cur]
            while path[-1] in came:
                path.append(came[path[-1]])
            return [(x * GRID, y * GRID, layer) for x, y, layer in reversed(path)]
        base = cost[cur]
        near_end = abs(cx - sb[0]) + abs(cy - sb[1]) <= 3
        near_start = abs(cx - sa[0]) + abs(cy - sa[1]) <= 3
        moves = []
        for dx, dy in steps:
            moves.append(((cx + dx, cy + dy, cl), math.hypot(dx, dy)))
        for other in layers:
            if other != cl:
                moves.append(((cx, cy, other), VIA_COST))
        for nxt, step in moves:
            nx, ny, nl = nxt
            px, py = nx * GRID, ny * GRID
            if not (x0 <= px <= x1 and y0 <= py <= y1):
                continue
            if nl != cl:
                # no second layer change within 4 cells of the last one: the
                # two via holes would sit too close together
                back, recent = cur, False
                for _ in range(4):
                    prev = came.get(back)
                    if prev is None:
                        break
                    if prev[2] != back[2]:
                        recent = True
                        break
                    back = prev
                if recent:
                    continue
                if not (obs.free(px, py, pcbnew.F_Cu, VIA_D / 2) and obs.free(px, py, pcbnew.B_Cu, VIA_D / 2)):
                    continue
            elif not obs.free(px, py, nl, r) and not ((near_end and (nx, ny) == sb) or (near_start and (nx, ny) == sa)):
                continue
            elif nl == cl and nx != cx and ny != cy and not (near_end or near_start) and \
                    not obs.free((cx + nx) * GRID / 2, (cy + ny) * GRID / 2, nl, r):
                continue                        # a diagonal step must not clip a corner
            c = base + step
            if c < cost.get(nxt, 1e18):
                cost[nxt] = c
                came[nxt] = cur
                h = math.hypot(nx - sb[0], ny - sb[1])
                heapq.heappush(openq, (c + h, nxt))
    return None


def simplify(path):
    """Merge collinear grid steps into segments; returns [(x, y, layer)]."""
    if len(path) < 3:
        return path
    out = [path[0]]
    for prev, cur, nxt in zip(path, path[1:], path[2:]):
        d1 = (round((cur[0] - prev[0]) / GRID), round((cur[1] - prev[1]) / GRID), cur[2] == prev[2])
        d2 = (round((nxt[0] - cur[0]) / GRID), round((nxt[1] - cur[1]) / GRID), nxt[2] == cur[2])
        if d1 != d2 or cur[2] != nxt[2] or cur[2] != prev[2]:
            out.append(cur)
    out.append(path[-1])
    return out
