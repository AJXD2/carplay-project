"""Footprint placement for the carrier board (used by gen_pcb.py).

Coordinates are millimetres on the KiCad sheet, board top-left at ORIGIN,
viewed from the TOP side (the side that faces the firewall). The Pi plugs
into J2 from the bottom side.

Anything not placed by a section function waits in a parking grid below the
board so it is easy to spot.
"""
import pcbnew

PLACED = set()
_bounds = [0, 0, 0, 0]


def mm(v):
    return pcbnew.FromMM(v)


def outline_points(x0, y0, w, h):
    """Board edge. Plain rectangle for now; the Pi port notch and ribbon slot
    get cut once the Pi's position on the display is measured."""
    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]


def put(fp, x, y, rot=0, bottom=False):
    if bottom and not fp.IsFlipped():
        fp.Flip(fp.GetPosition(), False)
    fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    fp.SetOrientationDegrees(rot)
    PLACED.add(fp.GetReference())


def is_placed(fp):
    return fp.GetReference() in PLACED


def park(fps, origin, size):
    """Grid below the board, grouped by reference prefix."""
    x0, y0 = origin
    x, y = x0, y0 + size[1] + 15
    row_h = 0
    for ref in sorted((r for r in fps if r not in PLACED),
                      key=lambda r: (r.rstrip("0123456789"), int(r[len(r.rstrip("0123456789")):] or 0))):
        fp = fps[ref]
        bb = fp.GetBoundingBox(False)
        w, h = pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight())
        if x + w > x0 + size[0] + 60:
            x, y = x0, y + row_h + 3
            row_h = 0
        fp.SetPosition(pcbnew.VECTOR2I(mm(x + w / 2), mm(y + h / 2)))
        x += w + 3
        row_h = max(row_h, h)


def place_all(board, fps, origin, size):
    park(fps, origin, size)
