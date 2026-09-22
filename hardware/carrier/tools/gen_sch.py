#!/usr/bin/env python3
"""Generate carrier.kicad_sch: the Pi 4 car carrier board.

Each subcircuit is a function that places its parts relative to one anchor
point, so a section can be moved by changing that anchor. Passives are wired
directly to the pins they serve; everything else connects through net
labels. Values come from the datasheet reference designs noted in each
section; see ../datasheets/.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schlib import COLORS, Schematic  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "carrier.kicad_sch")

S = Schematic("carrier", "Pi 4 car carrier board (2007 4Runner)", paper="A2")

FP_R = "Resistor_SMD:R_0603_1608Metric"
FP_C = "Capacitor_SMD:C_0603_1608Metric"
FP_C0805 = "Capacitor_SMD:C_0805_2012Metric"
FP_C1206 = "Capacitor_SMD:C_1206_3216Metric"

_counts = {}


def ref(prefix):
    _counts[prefix] = _counts.get(prefix, 0) + 1
    return f"{prefix}{_counts[prefix]}"


def _small(p):
    # value/ref beside a vertical 2-pin passive
    p.place_prop("Reference", 2.54, -1.27, "left")
    p.place_prop("Value", 2.54, 1.27, "left")
    return p


def R(val, at=(0, 0), rot=0, fp=FP_R, **kw):
    p = S.part("Device:R_Small_US", ref("R"), val, at, rot=rot, footprint=fp, **kw)
    return _small(p) if rot in (0, 180) else p


def C(val, at=(0, 0), rot=0, fp=FP_C, polarized=False, **kw):
    lib = "Device:C_Polarized" if polarized else "Device:C"
    p = S.part(lib, ref("C"), val, at, rot=rot, footprint=fp, **kw)
    if rot in (0, 180):
        p.place_prop("Reference", 2.54, -1.27, "left")
        p.place_prop("Value", 2.54, 1.27, "left")
    else:
        p.place_prop("Reference", 0, -2.54)
        p.place_prop("Value", 0, 2.54)
    return p


def shunt(part, top, net="GND"):
    """Hang a vertical 2-pin part from `top` (pin 1) to a power symbol."""
    part.move_pin_to("1", top)
    S.power(part.pin("2"), net)
    return part


def lbl(part, pin, net, color=None, stub=2.54):
    return S.label(part.pin(pin), net, part.pin_dir(pin), color=COLORS.get(color), stub=stub)


# ------------------------------------------------------------ harness J1 ---

def harness(x, y):
    S.box(x, y, x + 62, y + 76.2, "HARNESS (Metra adapter)", (90, 90, 90))
    j = S.part("carrier:Harness_4Runner", ref("J"), "Harness_4Runner", (x + 34.29, y + 38.1),
               footprint="Connector_Molex:Molex_Micro-Fit_3.0_43045-2000_2x10_P3.00mm_Horizontal")
    j.place_prop("Reference", -13.97, -20.32, "left")
    j.place_prop("Value", -13.97, -17.78, "left")
    for pin, net, col in [("+12V_BATT", "+12V_BATT", "power12"), ("ACC", "ACC_IN", "ctl"),
                          ("ILLUM", "ILLUM_IN", "ctl"), ("SWC1", "SWC1_IN", "swc"),
                          ("SWC2", "SWC2_IN", "swc"), ("SWC_GND", "SWC_GND", "swc")]:
        lbl(j, pin, net, col)
    for ch in ("FL", "FR", "RL", "RR"):
        for pol in "+-":
            lbl(j, f"SPK_{ch}{pol}", f"SPK_{ch}{pol}", "spk")
    S.power(j.pin("GND"), "GND")
    S.no_connect(j.pin("NC"))
    S.text(x + 2.54, y + 73.66, "Molex Micro-Fit 3.0, 8.5 A/contact. Pin n sits above n+10.", size=1.27)
    return j


# --------------------------------------------------- input protection U1 ---

def input_protection(x, y):
    """LM74800-Q1 back-to-back N-FET front end, after TI SNOSD95C fig 10-1:
    reverse battery (Q1), overvoltage/load-dump cutoff at 35 V and inrush
    slew limit (Q2). One enable (SYS_EN) switches the whole board off."""
    red, ctl = COLORS["power12"], COLORS["ctl"]
    S.box(x, y, x + 160.02, y + 116.84, "INPUT PROTECTION: reverse battery, 35 V load-dump cutoff, inrush limit", red)
    rail = y + 17.78
    # battery rail: TVS + input cap
    S.label((x + 7.62, rail), "+12V_BATT", (-1, 0), color=red, stub=0)
    tvs = S.part("Device:D_TVS", ref("D"), "SMBJ33CA", (0, 0), rot=90, footprint="Diode_SMD:D_SMB")
    tvs.move_pin_to("2", (x + 17.78, rail))
    tvs.place_prop("Reference", 2.54, -1.27, "left", rot=0)
    tvs.place_prop("Value", 2.54, 1.27, "left", rot=0)
    S.power(tvs.pin("1"), "GND")
    cin = shunt(C("100nF", fp=FP_C0805), (x + 30.48, rail))
    # Q1 ideal diode (source on the battery side), Q2 load disconnect
    q1 = S.part("Transistor_FET:Q_NMOS_SSSGD_AvalancheRated", ref("Q"), "BUK7Y4R8-60E", (0, 0),
                rot=90, mirror="y", footprint="Package_TO_SOT_SMD:LFPAK56")
    q1.move_pin_to("1", (x + 45.72, rail))
    q2 = S.part("Transistor_FET:Q_NMOS_SSSGD_AvalancheRated", ref("Q"), "BUK7Y4R8-60E", (0, 0),
                rot=90, footprint="Package_TO_SOT_SMD:LFPAK56")
    q2.move_pin_to("5", (q1.pin("5")[0] + 25.4, rail))
    for q in (q1, q2):
        c = ((q.pin("1")[0] + q.pin("5")[0]) / 2, rail)
        q.place_prop("Reference", c[0] - q.x - 3.81, -8.89, "left")
        q.place_prop("Value", c[0] - q.x - 3.81, -6.35, "left")
    S.wire((x + 7.62, rail), q1.pin("1"), color=red)
    S.wire(q1.pin("5"), q2.pin("5"), color=red)
    S.junction(tvs.pin("2"))
    S.junction(cin.pin("1"))
    mid = (q1.pin("5")[0] + 12.7, rail)
    S.junction(mid)
    S.label(mid, "VMID", (0, -1), color=red)
    out_x = q2.pin("1")[0] + 30.48
    S.wire(q2.pin("1"), (out_x, rail), color=red)
    cout = shunt(C("100nF", fp=FP_C0805), (q2.pin("1")[0] + 20.32, rail))
    S.junction(cout.pin("1"))
    S.power((out_x, rail), "+12V_PROT")
    # gates: DGATE straight to Q1; Q2 gate gets the R4 + C dv/dt network beside it
    lbl(q1, "4", "DGATE", "ctl")
    g = q2.pin("4")
    S.label(g, "HGATE", (-1, 0), color=ctl)
    r4 = R("100R")
    r4.move_pin_to("1", (g[0] + 7.62, g[1]))
    S.wire(g, r4.pin("1"), color=ctl)
    shunt(C("22nF", fp=FP_C0805), r4.pin("2"))

    # controller
    u = S.part("carrier:LM74800-Q1", ref("U"), "LM74800-Q1", (x + 95.25, y + 80.01),
               footprint="Package_SON:WSON-12-1EP_3x3mm_P0.5mm_EP1.5x2.5mm")
    for pin, net, col in [("A", "+12V_BATT", "power12"), ("VSNS", "+12V_BATT", "power12"),
                          ("C", "VMID", "power12"), ("DGATE", "DGATE", "ctl"),
                          ("HGATE", "HGATE", "ctl"), ("OUT", "+12V_PROT", "power12"),
                          ("EN/UVLO", "SYS_EN", "ctl"), ("OV", "OV_SET", "ctl")]:
        lbl(u, pin, net, col)
    # VS: from the common-drain node with 100 nF to GND; CAP: 220 nF to VS
    vs, cap = u.pin("VS"), u.pin("CAP")
    node = (vs[0], vs[1] - 10.16)
    S.wire(vs, node)
    S.label(node, "VMID", (0, -1), color=red)
    cvs = C("100nF")
    cvs.move_pin_to("1", (vs[0] - 10.16, node[1]))
    S.wire(node, cvs.pin("1"))
    S.junction(node)
    S.power(cvs.pin("2"), "GND")
    ccap = C("220nF")
    ccap.move_pin_to("2", cap)
    ccap.place_prop("Reference", 2.54, -1.27, "left")
    ccap.place_prop("Value", 2.54, 1.27, "left")
    tap = (vs[0], ccap.pin("1")[1])
    S.wire(ccap.pin("1"), tap)
    S.junction(tap)
    # SW -> R1 -> BATT_MON -> R2 -> OV_SET -> R3 -> GND
    sw = u.pin("SW")
    dx = sw[0] - 25.4
    r1 = R("95.3k")
    r1.move_pin_to("1", (dx, sw[1]))
    S.wire(sw, r1.pin("1"))
    r2 = R("5.11k")
    r2.move_pin_to("1", r1.pin("2"))
    r3 = R("3.65k")
    r3.move_pin_to("1", r2.pin("2"))
    S.power(r3.pin("2"), "GND")
    S.label(r1.pin("2"), "BATT_MON", (-1, 0), color=COLORS["swc"])
    S.label(r2.pin("2"), "OV_SET", (-1, 0), color=ctl)
    S.power(u.pin("GND"), "GND")
    S.no_connect(u.pin("RTN"))
    S.text(u.pin("RTN")[0] + 2.54, u.pin("RTN")[1] + 5.08, "EP (RTN) floats: keep it off the GND pour", size=1.27)
    S.text(x + 2.54, y + 111.76, "OV cutoff = 1.23 V x (R1+R2+R3)/R3 = 35.1 V.   BATT_MON = VBAT / 11.9 (to ADS1115 AIN2).", size=1.27)
    S.text(x + 2.54, y + 114.3, "Inrush slew from the 100R + 22 nF on Q2's gate: ~2.5 V/ms (TAS6424 limit 75 V/ms). "
           "VCAP >= 10 x (Ciss Q1 + Ciss Q2) = 110 nF -> 220 nF.", size=1.27)
    return u


def main():
    harness(10.16, 15.24)
    input_protection(76.2, 15.24)
    S.write(OUT)
    print("wrote", os.path.relpath(OUT))


if __name__ == "__main__":
    main()
