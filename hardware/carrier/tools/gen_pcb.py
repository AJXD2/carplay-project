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
# The current-carrying paths are copper pours and hand-placed tracks
# (tools/route.py); these widths are for the autorouter's leftovers on those
# nets (sense pins, bias pins, 1 nF snubbers), sized to fit the pin pitch.
NETCLASSES = [
    # name, track, clearance, via dia, via drill, patterns
    ("Default", 0.2, 0.15, 0.6, 0.3, []),
    ("Battery", 0.25, 0.2, 0.6, 0.3, ["/+12V_BATT", "/VMID", "+12V_PROT"]),
    ("Rail5V", 0.4, 0.2, 0.6, 0.3, ["+5V"]),
    ("Speaker", 0.4, 0.2, 0.8, 0.4, ["/SPK_*", "/AMP_FL*", "/AMP_FR*", "/AMP_RL*", "/AMP_RR*"]),
    ("Switch", 0.4, 0.2, 0.6, 0.3, ["/SW_5V"]),
    ("Rail3V3", 0.3, 0.15, 0.6, 0.3, ["+3V3"]),
]


def mm(v):
    return pcbnew.FromMM(v)


def export_netlist():
    os.makedirs(os.path.dirname(NETLIST), exist_ok=True)
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadxml",
                    "-o", NETLIST, SCH], check=True, capture_output=True)
    return ET.parse(NETLIST)


# KiCad ships no model for these: STEP from LCSC/EasyEDA (easyeda2kicad), in
# lib/3d, placed on KiCad's footprint origin (offset mm, 3D axes: y up)
MODELS = {
    "Connector_Molex:Molex_Micro-Fit_3.0_43045-2012_2x10_P3.00mm_Vertical":
        ("CONN-TH_20P-P3.00_430452012.step", (13.5, -1.505, 0.0), 180.0),
    "Battery:BatteryHolder_MYOUNG_BS-07-A1BJ001_CR2032":
        ("BAT-TH_BS-07-A1BJ001.step", (14.23, 0.0, 0.0), 0.0),
}


def set_model(fp, fpid):
    if fpid not in MODELS:
        return
    name, off, rot = MODELS[fpid]
    fp.Models().clear()
    m = pcbnew.FP_3DMODEL()
    m.m_Filename = "${KIPRJMOD}/lib/3d/easyeda.3dshapes/" + name
    m.m_Offset = pcbnew.VECTOR3D(*off)
    m.m_Rotation = pcbnew.VECTOR3D(0, 0, rot)
    fp.Models().push_back(m)


CREDIT = ("@ajxd2  Anthony Kovach", (90.0, 96.3), 2.0)     # top silkscreen, bottom strip
# (text, (x, y) board mm, height mm, rotation, bottom side)
TEXTS = [
    CREDIT + (0, False),
    # name and revision up the clear strip between the port notch and the Pi's holes
    ("4RUNNER CARPLAY CARRIER  REV A", (58.3, 59.6), 1.4, 90, False),
    # facing the Pi, seen only with the board off
    ("NO FIDDLING WHILE DRIVING", (88.0, 50.0), 2.2, 0, True),
    ("2007 4RUNNER  /  PI 4  /  4 x 25 W CLASS D", (88.0, 55.0), 1.3, 0, True),
    ("REV A  2026-09", (88.0, 58.5), 1.3, 0, True),
    # status LED tags, under D-LEDs placed by place.py (x 57.5 / 61.5 / 65.5)
    ("12V", (57.5, 98.4), 0.8, 0, False),
    ("5V", (61.5, 98.4), 0.8, 0, False),
    ("PI", (65.5, 98.4), 0.8, 0, False),
    ("MIC", (154.5, 89.0), 1.0, 0, False),
]


def credit(board):
    for text, (x, y), size, rot, bottom in TEXTS:
        t = pcbnew.PCB_TEXT(board)
        t.SetText(text)
        t.SetLayer(pcbnew.B_SilkS if bottom else pcbnew.F_SilkS)
        t.SetMirrored(bottom)
        t.SetTextAngleDegrees(rot)
        t.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(ORIGIN[0] + x), pcbnew.FromMM(ORIGIN[1] + y)))
        t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
        t.SetTextThickness(pcbnew.FromMM(0.3 if size >= 2 else 0.22))
        board.Add(t)


def load_fp(fpid):
    lib, name = fpid.split(":")
    path = LOCAL_FP.get(lib, os.path.join(STOCK_FP, f"{lib}.pretty"))
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise SystemExit(f"footprint not found: {fpid}")
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    set_model(fp, fpid)
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
        "min_clearance": 0.127, "min_track_width": 0.15, "min_via_diameter": 0.45,
        "min_through_hole_diameter": 0.3, "min_via_annular_width": 0.1, "min_hole_clearance": 0.25,
        "min_hole_to_hole": 0.25, "min_copper_edge_clearance": 0.4, "min_silk_clearance": 0.0,
        "min_text_height": 0.8, "min_text_thickness": 0.12, "max_error": 0.005,
        "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1, "min_resolved_spokes": 1,
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
    # inner layers are planes (In1 GND, In2 split +12V_PROT / +5V): marking
    # them as power layers keeps the autorouter off them
    for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
        board.SetLayerType(layer, pcbnew.LT_POWER)
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
    credit(board)
    place.place_all(board, fps, ORIGIN, (BOARD_W, BOARD_H))
    board.Save(PCB)
    write_project()             # after Save, which writes the project file with defaults
    unplaced = [r for r, f in fps.items() if not place.is_placed(f)]
    print(f"wrote {os.path.relpath(PCB)}: {len(fps)} footprints, {len(nets)} nets, "
          f"{len(unplaced)} still in the parking area")


if __name__ == "__main__":
    main()
