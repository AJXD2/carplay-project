#!/bin/sh
# JLCPCB order files -> fab/: Gerbers + drill (zip), BOM, CPL (placement).
set -e
cd "$(dirname "$0")/.."
rm -rf out/jlc && mkdir -p out/jlc/gerber fab
kicad-cli pcb export gerbers --layers F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts \
    --subtract-soldermask -o out/jlc/gerber/ carrier.kicad_pcb > /dev/null
kicad-cli pcb export drill --format excellon --excellon-separate-th --excellon-units mm -o out/jlc/gerber/ carrier.kicad_pcb > /dev/null
kicad-cli sch export bom --fields 'Value,Reference,Footprint,LCSC,MPN,Manufacturer,${QUANTITY},${DNP}' \
    --labels 'Comment,Designator,Footprint,LCSC,MPN,Manufacturer,Qty,DNP' --group-by 'Value,Footprint,LCSC,${DNP}' \
    --exclude-dnp --ref-range-delimiter "" -o fab/carrier_bom.csv carrier.kicad_sch > /dev/null
kicad-cli pcb export pos --format csv --units mm --side both --exclude-dnp -o out/jlc/pos_raw.csv carrier.kicad_pcb > /dev/null
flatpak run --command=python3 org.kicad.KiCad tools/jlc_cpl.py 2>&1 | grep -v "Warn\|leak" || true
python3 - <<'PY'
import csv, os, zipfile
with zipfile.ZipFile("fab/carrier_gerbers.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(os.listdir("out/jlc/gerber")):
        z.write(os.path.join("out/jlc/gerber", f), f)
# one line per LCSC part: JLC confirms only the first of two lines that
# share a part number (the fan headers FAN1/FAN2 are the same part)
lines = list(csv.DictReader(open("fab/carrier_bom.csv")))
merged = {}
for x in lines:
    k = x["LCSC"]
    if k in merged:
        m = merged[k]
        m["Designator"] += "," + x["Designator"]
        m["Qty"] = str(int(m["Qty"]) + int(x["Qty"]))
        if x["Comment"] not in m["Comment"].split("/"):
            m["Comment"] += "/" + x["Comment"]
    else:
        merged[k] = dict(x)
with open("fab/carrier_bom.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(lines[0].keys()), quoting=csv.QUOTE_ALL)
    w.writeheader()
    w.writerows(merged.values())
rows = list(csv.DictReader(open("out/jlc/pos_raw.csv")))
centre = {r["Ref"]: r for r in csv.DictReader(open("out/jlc/centres.csv"))}
moved = []
for r in rows:           # part centres, not KiCad origins (pin 1 on through-hole parts)
    c = centre[r["Ref"]]
    if abs(float(c["X"]) - float(r["PosX"])) + abs(float(c["Y"]) - float(r["PosY"])) > 0.01:
        moved.append(r["Ref"])
    r["PosX"], r["PosY"] = c["X"], c["Y"]
print("centred:", ", ".join(sorted(moved)))
bom = {r.strip() for x in csv.DictReader(open("fab/carrier_bom.csv")) for r in x["Designator"].split(",")}
with open("fab/carrier_cpl.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for r in rows:
        if r["Ref"] in bom:
            w.writerow([r["Ref"], f'{float(r["PosX"]):.4f}mm', f'{float(r["PosY"]):.4f}mm', "Top" if r["Side"] == "top" else "Bottom", r["Rot"]])
missing = bom - {r["Ref"] for r in rows}
print(f"fab/: {len(bom)} parts in BOM and CPL" + (f", MISSING from CPL: {sorted(missing)}" if missing else ""))
PY
