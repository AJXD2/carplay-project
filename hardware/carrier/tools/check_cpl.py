#!/usr/bin/env python3
"""Check fab/carrier_cpl.csv against JLC's own (EasyEDA) footprints.

    flatpak run --command=python3 org.kicad.KiCad tools/check_cpl.py --dump   # board pads -> out/sim/fps.json
    .venv/bin/python tools/check_cpl.py                                       # compare, exit 1 on a mismatch

JLC places each LCSC part by its EasyEDA footprint's origin, turned by the
CPL rotation. For every BOM line this fetches that footprint (cached in
out/sim/easyeda/), finds the rotation phi that maps its pads onto our
footprint's pads by pad number, and checks the CPL has KiCad's rotation +
phi and JLC's origin as its centre. tools/jlc_cpl.py holds the resulting
corrections. Writes out/sim/cpl_check.json.
"""
import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "out", "sim")
MIL10 = 0.254


def dump():
    import pcbnew
    b = pcbnew.LoadBoard(os.path.join(ROOT, "carrier.kicad_pcb"))
    out = {}
    for fp in b.GetFootprints():
        pads, bpads = [], []
        for p in fp.Pads():
            lp, bp = p.GetFPRelativePosition(), p.GetPosition()
            pads.append([p.GetNumber(), pcbnew.ToMM(lp.x), pcbnew.ToMM(lp.y)])
            bpads.append([p.GetNumber(), pcbnew.ToMM(bp.x), pcbnew.ToMM(bp.y)])
        out[fp.GetReference()] = {"fpid": fp.GetFPIDAsString(), "rot": fp.GetOrientationDegrees(),
                                  "side": fp.GetLayerName(), "pads": pads, "bpads": bpads}
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(os.path.join(OUT, "fps.json"), "w"))


def easyeda(lcsc):
    from easyeda2kicad.easyeda.easyeda_api import EasyedaApi
    cache = os.path.join(OUT, "easyeda", lcsc + ".json")
    if os.path.exists(cache):
        return json.load(open(cache))
    d = EasyedaApi().get_cad_data_of_component(lcsc_id=lcsc)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    json.dump(d, open(cache, "w"))
    return d


def ee_pads(d):
    ds = d["packageDetail"]["dataStr"]
    ox, oy = ds["head"]["x"], ds["head"]["y"]
    pads = []
    for s in ds["shape"]:
        f = s.split("~")
        if f[0] == "PAD":
            pads.append([f[8], (float(f[2]) - ox) * MIL10, (float(f[3]) - oy) * MIL10])
    return d["packageDetail"]["title"], pads


def groups(pads):
    g = {}
    for n, x, y in pads:
        if n:
            g.setdefault(n, []).append((x, y))
    return {n: (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)) for n, v in g.items()}


def rot(p, deg):
    """visual counter-clockwise rotation in a y-down frame"""
    a = math.radians(deg)
    return (p[0] * math.cos(a) + p[1] * math.sin(a), -p[0] * math.sin(a) + p[1] * math.cos(a))


def fit(k, e):
    common = sorted(set(k) & set(e))
    if len(common) < 2:
        return None
    kc = [sum(k[n][i] for n in common) / len(common) for i in (0, 1)]
    best = None
    for phi in (0, 90, 180, 270):
        er = {n: rot(e[n], phi) for n in common}
        ec = [sum(er[n][i] for n in common) / len(common) for i in (0, 1)]
        res = math.sqrt(sum((k[n][0] - kc[0] - er[n][0] + ec[0]) ** 2 + (k[n][1] - kc[1] - er[n][1] + ec[1]) ** 2
                            for n in common) / len(common))
        off = (kc[0] - ec[0], kc[1] - ec[1])     # JLC's origin in KiCad's footprint frame
        if best is None or res < best[1] - 1e-6:
            best = (phi, res, off, tuple(ec), common)
    return best


# By-number fits that are not real rotations:
#   D8-D10  JLC's LED footprint calls pad 1 the anode (KiCad: cathode), so the
#           180 by number is 0 by pin name.
#   L2-L9   non-polar; the 180 by number doesn't matter.
#   J2      2x20 socket on the bottom, symmetric; JLC aligns it to the holes.
NO_ROT = {"D8", "D9", "D10", "J2"} | {f"L{i}" for i in range(2, 10)}
# JLC's pad pattern differs from KiCad's (LFPAK56 pins 0.5-0.8 mm further
# in), so its origin can't be fitted from the pads: check it in JLC's preview.
REVIEW_POS = {"Q1", "Q2"}
# Pad patterns differ a little between libraries (J4's pad rows are 6.5 mm
# apart in KiCad's, 7.0 in JLC's, which moves the pad centre 0.125 mm while
# the locating-peg holes line up), so a centre within this counts as right.
POS_TOL = 0.15
# KiCad pad name -> JLC pad number, where the footprints number pads differently.
PAD_MAP = {"Connector_Audio:Jack_3.5mm_PJ320D_Horizontal": {"T": "4", "R1": "3", "R2": "2", "S": "1"}}


def main():
    fps = json.load(open(os.path.join(OUT, "fps.json")))
    cpl = {r["Designator"]: r for r in csv.DictReader(open(os.path.join(ROOT, "fab", "carrier_cpl.csv")))}
    rows, fails, reviews = [], [], []
    for line in csv.DictReader(open(os.path.join(ROOT, "fab", "carrier_bom.csv"))):
        refs = [r.strip() for r in line["Designator"].split(",")]
        lcsc = line["LCSC"]
        try:
            d = easyeda(lcsc)
            title, epads = ee_pads(d)
        except Exception as ex:  # noqa: BLE001
            reviews.append(f"{','.join(refs)}: no JLC footprint to compare ({lcsc}: {ex})")
            continue
        for ref in refs:
            f = fps[ref]
            pmap = PAD_MAP.get(f["fpid"], {})
            k = groups([[pmap.get(n, n), x, y] for n, x, y in f["pads"]])
            kb = groups([[pmap.get(n, n), x, y] for n, x, y in f["bpads"]])
            r = fit(k, groups(epads))
            if r is None:
                reviews.append(f"{ref}: no pad numbers in common with JLC's {title}")
                continue
            phi, res, off, ec, common = r
            want_rot = (f["rot"] + (0 if ref in NO_ROT else phi)) % 360
            # JLC's origin on the board: pad centre on the board minus JLC's own
            # pad centre, turned into the board frame (y down)
            cb = [sum(kb[n][i] for n in common) / len(common) for i in (0, 1)]
            if f["side"].startswith("B") and math.hypot(*ec) > 0.05:
                want_xy = None
            else:
                e = rot(ec, f["rot"])
                want_xy = (cb[0] - e[0], -(cb[1] - e[1]))           # CPL is y up
            c = cpl.get(ref)
            got_rot = float(c["Rotation"]) % 360
            got_xy = (float(c["Mid X"][:-2]), float(c["Mid Y"][:-2]))
            row = {"ref": ref, "lcsc": lcsc, "ee": title, "phi": phi, "fit": res,
                   "rot_want": want_rot, "rot_cpl": got_rot, "xy_want": want_xy, "xy_cpl": got_xy}
            rows.append(row)
            if abs((got_rot - want_rot + 180) % 360 - 180) > 0.5:
                fails.append(f"{ref}: CPL rotation {got_rot:g}, JLC's footprint needs {want_rot:g} ({title})")
            if ref in REVIEW_POS:
                reviews.append(f"{ref}: JLC's {title} pads differ from ours; check it sits centred in the preview")
            elif want_xy is None:
                reviews.append(f"{ref}: bottom-side part with an off-centre JLC origin; check in the preview")
            elif math.hypot(got_xy[0] - want_xy[0], got_xy[1] - want_xy[1]) > POS_TOL:
                fails.append(f"{ref}: CPL centre ({got_xy[0]:.3f}, {got_xy[1]:.3f}), JLC's origin is at "
                             f"({want_xy[0]:.3f}, {want_xy[1]:.3f}) ({title})")
    json.dump(rows, open(os.path.join(OUT, "cpl_check.json"), "w"), indent=1)
    print(f"checked {len(rows)} placements against JLC's footprints")
    for m in reviews:
        print("  review: " + m)
    for m in fails:
        print("  FAIL:   " + m)
    print(f"{len(fails)} fail, {len(reviews)} to review in JLC's preview")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(dump() if "--dump" in sys.argv else main())
