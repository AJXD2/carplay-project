#!/usr/bin/env python3
"""Build carrier.kicad_pcb from the schematic netlist.

Runs inside the KiCad Flatpak (it needs the pcbnew module):

    flatpak run --command=python3 org.kicad.KiCad tools/gen_pcb.py

Footprints are linked to their schematic symbols by UUID path, so KiCad's
"Update PCB from Schematic" keeps working on the generated board. Placement
lives in place.py; this file only builds the board, rules and net classes.
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SCH = os.path.join(ROOT, "carrier.kicad_sch")
PCB = os.path.join(ROOT, "carrier.kicad_pcb")
PRO = os.path.join(ROOT, "carrier.kicad_pro")
NETLIST = os.path.join(ROOT, "out", "carrier.xml")
STOCK_FP = "/app/extensions/Library/footprints"
LOCAL_FP = {"carrier": os.path.join(ROOT, "lib", "carrier.pretty")}

sys.path.insert(0, HERE)
import place  # noqa: E402

BOARD_W, BOARD_H = 165.0, 103.0      # Hosyond 7" DSI display outline
ORIGIN = (100.0, 100.0)               # top-left corner of the board on the sheet

# Net classes (mm). JLC 4-layer standard process: 0.09 mm min track/space,
# 0.2 mm min drill; we stay well above it.
NETCLASSES = [
    # name, track, clearance, via dia, via drill, patterns
    ("Default", 0.2, 0.15, 0.6, 0.3, []),
    ("Battery", 2.0, 0.3, 0.8, 0.4, ["+12V_BATT", "VMID", "+12V_PROT"]),
    ("Rail5V", 1.5, 0.2, 0.8, 0.4, ["+5V"]),
    ("Speaker", 1.0, 0.25, 0.8, 0.4, ["/SPK_*", "/AMP_FL*", "/AMP_FR*", "/AMP_RL*", "/AMP_RR*"]),
    ("Switch", 1.0, 0.2, 0.6, 0.3, ["/SW_5V"]),
    ("Rail3V3", 0.4, 0.15, 0.6, 0.3, ["+3V3"]),
]


def mm(v):
    return pcbnew.FromMM(v)


def export_netlist():
    os.makedirs(os.path.dirname(NETLIST), exist_ok=True)
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadxml",
                    "-o", NETLIST, SCH], check=True, capture_output=True)
    return ET.parse(NETLIST)


def load_fp(fpid):
    lib, name = fpid.split(":")
    path = LOCAL_FP.get(lib, os.path.join(STOCK_FP, f"{lib}.pretty"))
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise SystemExit(f"footprint not found: {fpid}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def write_project():
    """Net classes, patterns and board rules into carrier.kicad_pro."""
    pro = json.load(open(PRO)) if os.path.exists(PRO) else {"meta": {"filename": "carrier.kicad_pro", "version": 3}}
    classes, patterns = [], []
    for i, (name, tw, cl, vd, vdr, pats) in enumerate(NETCLASSES):
        classes.append({
            "name": name, "track_width": tw, "clearance": cl, "via_diameter": vd, "via_drill": vdr,
            "microvia_diameter": 0.3, "microvia_drill": 0.1, "diff_pair_width": 0.2, "diff_pair_gap": 0.25,
            "diff_pair_via_gap": 0.25, "bus_width": 12, "wire_width": 6, "line_style": 0,
            "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
            "priority": 2147483647 if name == "Default" else i, "tuning_profile": ""})
        patterns += [{"netclass": name, "pattern": p} for p in pats]
    pro["net_settings"] = {"classes": classes, "meta": {"version": 5}, "net_colors": None,
                           "netclass_assignments": None, "netclass_patterns": patterns}
    pro.setdefault("board", {}).setdefault("design_settings", {})["rules"] = {
        "min_clearance": 0.127, "min_track_width": 0.127, "min_via_diameter": 0.45,
        "min_through_hole_diameter": 0.3, "min_via_annular_width": 0.1, "min_hole_clearance": 0.25,
        "min_hole_to_hole": 0.25, "min_copper_edge_clearance": 0.4, "min_silk_clearance": 0.0,
        "min_text_height": 0.8, "min_text_thickness": 0.12, "max_error": 0.005,
        "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1, "min_resolved_spokes": 2,
        "min_groove_width": 0.0, "min_connection": 0.0, "solder_mask_to_copper_clearance": 0.0,
        "use_height_for_length_calcs": True}
    with open(PRO, "w") as f:
        json.dump(pro, f, indent=2)


def outline(board):
    x0, y0 = ORIGIN
    loops = [place.outline_points(x0, y0, BOARD_W, BOARD_H)]
    for cx0, cy0, cx1, cy1 in place.cutouts():
        loops.append([(x0 + cx0, y0 + cy0), (x0 + cx1, y0 + cy0), (x0 + cx1, y0 + cy1), (x0 + cx0, y0 + cy1)])
    for pts in loops:
        _loop(board, pts)


def _loop(board, pts):
    for a, b in zip(pts, pts[1:] + pts[:1]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(mm(a[0]), mm(a[1])))
        seg.SetEnd(pcbnew.VECTOR2I(mm(b[0]), mm(b[1])))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(mm(0.1))
        board.Add(seg)


def main():
    tree = export_netlist()
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    ds = board.GetDesignSettings()
    ds.SetBoardThickness(mm(1.6))

    nets = {}
    for n in tree.iter("net"):
        name = n.get("name")
        if name.startswith("Net-("):          # KiCad escapes '/' inside derived names
            name = "Net-(" + name[5:-1].replace("/", "{slash}") + ")"
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        nets[n.get("name")] = (ni, [(x.get("ref"), x.get("pin")) for x in n.iter("node")])

    fps = {}
    for c in tree.iter("comp"):
        ref, fpid = c.get("ref"), c.findtext("footprint")
        if not fpid:
            raise SystemExit(f"{ref} has no footprint")
        fp = load_fp(fpid)
        fp.SetReference(ref)
        fp.SetValue(c.findtext("value"))
        sheet = c.find("sheetpath").get("tstamps")
        fp.SetPath(pcbnew.KIID_PATH(sheet + c.findtext("tstamps")))
        props = {p.get("name"): p.get("value") for p in c.iter("property")}
        for k in ("LCSC", "MPN", "Manufacturer", "Section"):
            if k in props:
                fp.SetField(k, props[k])
        for fld in fp.GetFields():
            if fld.GetName() in ("LCSC", "MPN", "Manufacturer", "Section"):
                fld.SetVisible(False)
        if "dnp" in props:
            fp.SetDNP(True)
        if "exclude_from_bom" in props:
            fp.SetExcludedFromBOM(True)
        board.Add(fp)
        fps[ref] = fp

    for ni, nodes in nets.values():
        for ref, pin in nodes:
            fp = fps[ref]
            for pad in fp.Pads():
                if pad.GetNumber() == pin:
                    pad.SetNet(ni)

    outline(board)
    place.place_all(board, fps, ORIGIN, (BOARD_W, BOARD_H))
    write_project()
    board.Save(PCB)
    unplaced = [r for r, f in fps.items() if not place.is_placed(f)]
    print(f"wrote {os.path.relpath(PCB)}: {len(fps)} footprints, {len(nets)} nets, "
          f"{len(unplaced)} still in the parking area")


if __name__ == "__main__":
    main()
