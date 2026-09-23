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
FP_C1210 = "Capacitor_SMD:C_1210_3225Metric"

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


# ------------------------------------------------------------ 5 V buck U2 ---

def buck(x, y):
    """LM61460-Q1 5 V / 6 A synchronous buck at 400 kHz. Component values are
    the 5 V / 400 kHz row of TI SNVSB70F table 10-2."""
    org, red = COLORS["power5"], COLORS["power12"]
    S.box(x, y, x + 210.82, y + 88.9, "5 V BUCK: Pi, display, fans, 3.3 V", org)
    rail = y + 17.78
    vx = x + 91.44
    u = S.part("carrier:LM61460-Q1", ref("U"), "LM61460-Q1", (0, 0),
               footprint="carrier:TI_RJR0014A_VQFN-HR-14_3.5x4mm")
    u.move_pin_to("8", (vx, rail + 7.62))
    u.place_prop("Reference", 12.7, 17.78, "left")
    u.place_prop("Value", 12.7, 20.32, "left")

    # input: +12V_PROT rail, bulk ceramics far, HF caps nearest the IC
    S.power((vx - 86.36, rail), "+12V_PROT")
    taps = [vx - 78.74, vx - 68.58, vx - 58.42, vx - 48.26, vx - 33.02]
    S.wire((vx - 86.36, rail), *[(t, rail) for t in taps], (vx, rail), u.pin("8"), color=red)
    for t, (val, fp) in zip(taps, [("10uF", FP_C1206), ("10uF", FP_C1206), ("100nF", FP_C), ("100nF", FP_C)]):
        shunt(C(val, fp=fp), (t, rail))
        S.junction((t, rail))

    # EN/SYNC: UVLO divider from the input rail
    en, rt, vcc = u.pin("7"), u.pin("6"), u.pin("2")
    c = taps[-1]
    S.junction((c, rail))
    rent = R("100k")
    rent.move_pin_to("1", (c, en[1] - 5.08))
    S.wire((c, rail), rent.pin("1"), color=red)
    renb = shunt(R("26.7k"), (c, en[1]))
    for r in (rent, renb):
        r.place_prop("Reference", -2.54, -1.27, "right")
        r.place_prop("Value", -2.54, 1.27, "right")
    S.wire(en, (c, en[1]))
    S.junction((c, en[1]))
    # RT sets 400 kHz; VCC is the internal LDO output (1 uF to AGND)
    a, b = vx - 25.4, vx - 15.24
    S.wire(rt, (a, rt[1]))
    shunt(R("33.2k"), (a, rt[1]))
    S.wire(vcc, (b, vcc[1]))
    shunt(C("1uF"), (b, vcc[1]))

    # BIAS from the output (lower LDO loss), optional 1 uF per table 7-1
    bias = u.pin("1")
    node = (bias[0], bias[1] - 5.08)
    S.wire(bias, node, (vx + 17.78, node[1]), color=org)
    S.power(node, "+5V")
    S.junction(node)
    shunt(C("1uF"), (vx + 17.78, node[1]))

    # switch node: boot cap SW->CBOOT, 0R boot resistor CBOOT->RBOOT
    sw, cb, rb, fb = u.pin("10"), u.pin("14"), u.pin("13"), u.pin("4")
    sx, sy = sw
    xr, xc = sx + 2.54, sx + 12.7
    rboot = R("0R")
    rboot.move_pin_to("1", (xr, cb[1]))
    rboot.place_prop("Reference", 2.54, 0, "left")
    rboot.place_prop("Value", 2.54, 2.54, "left")
    S.wire(cb, (xr, cb[1]))
    S.wire((xr, cb[1]), (xc, cb[1]))
    S.junction((xr, cb[1]))
    S.wire(rb, rboot.pin("2"))
    cboot = C("100nF", rot=90)
    cboot.move_pin_to("1", (xc, cb[1]))
    ct = (cboot.pin("2")[0], sy)
    S.wire(cboot.pin("2"), ct)
    S.junction(ct)
    ind = S.part("Device:L", ref("L"), "4.7uH", (0, 0), rot=90,
                 footprint="Inductor_SMD:L_Bourns_SRP1038C_10.0x10.0mm")
    ind.move_pin_to("1", (sx + 25.4, sy))
    S.wire(sw, ct, ind.pin("1"))

    # output rail: feedback divider, feed-forward, output caps
    xt, xf = sx + 38.1, sx + 50.8
    caps = [xf + 12.7, xf + 22.86, xf + 33.02]
    xe = xf + 43.18
    S.wire(ind.pin("2"), (xt, sy), (xf, sy), *[(t, sy) for t in caps], (xe, sy), color=org)
    for t in [xt, xf] + caps:
        S.junction((t, sy))
    rfbt = R("100k")
    rfbt.move_pin_to("2", (xt, fb[1]))
    S.wire((xt, sy), rfbt.pin("1"), color=org)
    shunt(R("24.9k"), (xt, fb[1]))
    S.wire(fb, (xt, fb[1]))
    S.junction((xt, fb[1]))
    rff = R("1k")
    rff.move_pin_to("1", (xf, sy))
    cff = C("22pF")
    cff.move_pin_to("1", rff.pin("2"))
    S.wire(cff.pin("2"), (xf, fb[1]), (xt, fb[1]))
    for t, val, fp in zip(caps, ["47uF", "47uF", "100nF"], [FP_C1210, FP_C1210, FP_C]):
        shunt(C(val, fp=fp), (t, sy))
    S.power((xe, sy), "+5V")
    S.pwr_flag((xe - 5.08, sy))
    S.junction((xe - 5.08, sy))
    S.no_connect(u.pin("5"))
    S.power(u.pin("3"), "GND")
    S.power(u.pin("9"), "GND")

    # 3.3 V LDO for the amp's DVDD, ADC, RTC and EEPROM (well under 100 mA).
    # TLV755 wants >= 1 uF in and out (SBVS320 8.1).
    lx, ly = x + 162.56, y + 63.5
    ldo = S.part("Regulator_Linear:TLV75533PDBV", ref("U"), "TLV75533PDBV", (0, 0),
                 footprint="Package_TO_SOT_SMD:SOT-23-5")
    ldo.move_pin_to("1", (lx + 15.24, ly))
    ldo.place_prop("Reference", 0, -10.16)
    ldo.place_prop("Value", 0, -7.62)
    S.power((lx, ly), "+5V")
    S.wire((lx, ly), (lx + 5.08, ly), (lx + 12.7, ly), ldo.pin("1"), color=org)
    cin = shunt(C("1uF"), (lx + 5.08, ly))
    cin.place_prop("Reference", -2.54, -1.27, "right")
    cin.place_prop("Value", -2.54, 1.27, "right")
    S.junction((lx + 5.08, ly))
    en3 = ldo.pin("3")
    S.wire(en3, (lx + 12.7, en3[1]), (lx + 12.7, ly), color=org)
    S.junction((lx + 12.7, ly))
    out = ldo.pin("5")
    S.wire(out, (out[0] + 5.08, ly), (out[0] + 12.7, ly), color=COLORS["power3"])
    shunt(C("1uF"), (out[0] + 5.08, ly))
    S.junction((out[0] + 5.08, ly))
    S.power((out[0] + 12.7, ly), "+3V3")
    S.no_connect(ldo.pin("4"))
    S.power(ldo.pin("2"), "GND")

    S.text(x + 2.54, y + 81.28, "fSW 400 kHz (RT 33.2k), FPWM + spread spectrum.   "
           "UVLO on 6.0 V / off 4.3 V (100k / 26.7k), rides through cranking dips.", size=1.27)
    S.text(x + 2.54, y + 83.82, "VOUT = 1.0 V x (1 + 100k / 24.9k) = 5.02 V.   Input ceramics 50 V X7R; "
           "the amp's PVDD bulk on +12V_PROT doubles as CIN-BLK.", size=1.27)
    S.text(x + 2.54, y + 86.36, "AGND ties to PGND at the IC only. Keep the VIN/PGND hot loop through the 100 nF caps tight "
           "(SNVSB70F 11.1).", size=1.27)
    return u


# -------------------------------------------------- power hold + key sense ---

def _sense(x, y, net_in, net_out):
    """12 V input -> MMBT3904 inverter -> active-low 3.3 V GPIO. 47k/10k keeps
    base current under 1 mA at a 40 V load dump; 100 nF eats ignition noise."""
    ctl = COLORS["ctl"]
    S.label((x, y), net_in, (-1, 0), color=ctl, stub=0)
    rs = R("47k", rot=90)
    rs.move_pin_to("1", (x + 2.54, y))
    rs.place_prop("Reference", 0, -2.54)
    rs.place_prop("Value", 0, 2.54)
    q = S.part("Transistor_BJT:MMBT3904", ref("Q"), "MMBT3904", (0, 0),
               footprint="Package_TO_SOT_SMD:SOT-23")
    q.move_pin_to("1", (x + 35.56, y))
    q.place_prop("Reference", 5.08, -1.27, "left")
    q.place_prop("Value", 5.08, 1.27, "left")
    S.wire((x, y), rs.pin("1"), color=ctl)
    S.wire(rs.pin("2"), (x + 12.7, y), (x + 25.4, y), q.pin("1"))
    for t, part in [(x + 12.7, R("10k")), (x + 25.4, C("100nF"))]:
        shunt(part, (t, y))
        S.junction((t, y))
    c = q.pin("3")
    pu = R("10k")
    pu.move_pin_to("2", c)
    pu.place_prop("Reference", -2.54, -1.27, "right")
    pu.place_prop("Value", -2.54, 1.27, "right")
    S.power(pu.pin("1"), "+3V3")
    S.junction(c)
    S.label(c, net_out, (1, 0), color=ctl, stub=7.62)
    S.power(q.pin("2"), "GND")


def power_hold(x, y):
    """SYS_EN (LM74800 EN/UVLO) is an OR of the key (ACC) and the Pi's own
    hold line, so the Pi decides when the board turns off."""
    ctl = COLORS["ctl"]
    S.box(x, y, x + 152.4, y + 83.82, "POWER HOLD + KEY / LIGHTS SENSE", ctl)
    y1, y2 = y + 15.24, y + 25.4
    # ACC -> D -> 47k -> SYS_EN
    S.label((x + 10.16, y1), "ACC_IN", (-1, 0), color=ctl, stub=0)
    d1 = S.part("Device:D", ref("D"), "1N4148W", (0, 0), rot=180, footprint="Diode_SMD:D_SOD-123")
    d1.move_pin_to("2", (x + 15.24, y1))
    r1 = R("47k", rot=90)
    r1.move_pin_to("1", (x + 27.94, y1))
    # PI_HOLD -> 1k -> D -> SYS_EN
    S.label((x + 10.16, y2), "PI_HOLD", (-1, 0), color=ctl, stub=0)
    r2 = R("1k", rot=90)
    r2.move_pin_to("1", (x + 15.24, y2))
    d2 = S.part("Device:D", ref("D"), "1N4148W", (0, 0), rot=180, footprint="Diode_SMD:D_SOD-123")
    d2.move_pin_to("2", (x + 25.4, y2))
    for p in (r1, r2):
        p.place_prop("Reference", 0, -2.54)
        p.place_prop("Value", 0, 2.54)
    for d in (d1, d2):
        d.place_prop("Reference", 0, -3.81)
        d.place_prop("Value", 0, 3.81)
    xn = x + 40.64
    S.wire((x + 10.16, y1), d1.pin("2"), color=ctl)
    S.wire(d1.pin("1"), r1.pin("1"), color=ctl)
    S.wire((x + 10.16, y2), r2.pin("1"), color=ctl)
    S.wire(r2.pin("2"), d2.pin("2"), color=ctl)
    S.wire(d2.pin("1"), (xn, y2), (xn, y1), color=ctl)
    # hold node: bleed R, hold C, 15 V clamp
    xa, xb, xz, xe = xn + 7.62, xn + 17.78, xn + 27.94, xn + 35.56
    S.wire(r1.pin("2"), (xn, y1), (xa, y1), (xb, y1), (xz, y1), (xe, y1), color=ctl)
    for t in (xn, xa, xb, xz):
        S.junction((t, y1))
    shunt(R("100k"), (xa, y1))
    shunt(C("47uF", fp=FP_C1210), (xb, y1))
    dz = S.part("Device:D_Zener", ref("D"), "BZT52C15", (0, 0), rot=270, footprint="Diode_SMD:D_SOD-123")
    dz.move_pin_to("1", (xz, y1))
    dz.place_prop("Reference", 2.54, -1.27, "left", rot=0)
    dz.place_prop("Value", 2.54, 1.27, "left", rot=0)
    S.power(dz.pin("2"), "GND")
    S.label((xe, y1), "SYS_EN", (1, 0), color=ctl, stub=0)

    _sense(x + 10.16, y + 55.88, "ACC_IN", "~{ACC_ON}")
    _sense(x + 83.82, y + 55.88, "ILLUM_IN", "~{LIGHTS_ON}")

    S.text(x + 2.54, y + 71.12, "PI_HOLD (GPIO26): config.txt gpio=26=op,dh raises it ~1 s after power-up; "
           "dtoverlay=gpio-poweroff drops it once the Pi halts.", size=1.27)
    S.text(x + 2.54, y + 73.66, "Key off: the Pi syncs and halts, SYS_EN decays under 1.13 V ~2 s later and the "
           "LM74800 cuts everything (3 uA standby).", size=1.27)
    S.text(x + 2.54, y + 76.2, "ACC alone holds SYS_EN ~5 s (100k x 47 uF) so a crank before the Pi boots doesn't "
           "drop power. BZT52C15 limits load dump on the cap.", size=1.27)
    S.text(x + 2.54, y + 78.74, "Hung Pi: the BCM watchdog resets it, GPIO26 floats low (100k bleed), and the board "
           "powers off if the key is off.", size=1.27)


# --------------------------------------------------------- Pi 4 header J2 ---

PI_GPIO = {
    # pin: (net, colour)
    "27": ("ID_SDA", "i2c"), "28": ("ID_SCL", "i2c"),
    "3": ("I2C_SDA", "i2c"), "5": ("I2C_SCL", "i2c"),
    "7": ("FAN2_TACH", "fan"), "29": ("~{RTC_INT}", "ctl"), "31": ("~{ADC_ALERT}", "swc"),
    "32": ("FAN1_PWM", "fan"), "33": ("FAN2_PWM", "fan"),
    "8": ("UART_TX", "misc"), "10": ("UART_RX", "misc"), "36": ("FAN1_TACH", "fan"),
    "11": ("~{ACC_ON}", "ctl"), "12": ("I2S_BCLK", "i2s"), "35": ("I2S_FSYNC", "i2s"),
    "40": ("I2S_DOUT", "i2s"), "15": ("~{AMP_STBY}", "ctl"), "16": ("~{AMP_MUTE}", "ctl"),
    "18": ("~{AMP_FAULT}", "ctl"), "22": ("~{AMP_WARN}", "ctl"), "37": ("PI_HOLD", "ctl"),
    "13": ("~{LIGHTS_ON}", "ctl"),
}
PI_UNUSED = ["26", "24", "21", "19", "23", "38"]   # SPI0 (GPIO7-11), PCM DIN (GPIO20)


def pi_header(x, y):
    """The Pi mounts on this board through a 2x20 socket on the underside. The
    board feeds the Pi (and the display's pogo pins under it) through 5V pins
    2/4; the Pi's own 3V3 is left alone."""
    grey = (90, 90, 90)
    S.box(x, y, x + 93.98, y + 96.52, "RASPBERRY PI 4 (40-pin, board underside)", grey)
    j = S.part("carrier:RaspberryPi_GPIO_40", ref("J"), "Pi 4 GPIO", (x + 46.99, y + 45.72),
               footprint="Connector_PinSocket_2.54mm:PinSocket_2x20_P2.54mm_Vertical")
    j.place_prop("Reference", 16.51, -27.94, "left")
    j.place_prop("Value", 16.51, -25.4, "left")
    for pin, (net, col) in PI_GPIO.items():
        lbl(j, pin, net, col)
    for pin in PI_UNUSED:
        S.no_connect(j.pin(pin))
    S.power(j.pin("2"), "+5V")
    S.no_connect(j.pin("1"))
    for pin in ("6", "20", "34"):
        S.power(j.pin(pin), "GND")
    S.text(x + 2.54, y + 88.9, "5V pins 2/4 carry Pi + display (~3 A): wide pour to the buck output.", size=1.27)
    S.text(x + 2.54, y + 91.44, "Pi 3V3 (1/17) unused: the board makes its own +3V3.", size=1.27)
    S.text(x + 2.54, y + 93.98, "GPIO2/3 already have 1.8k pull-ups on the Pi.", size=1.27)
    return j


def main():
    harness(10.16, 15.24)
    input_protection(76.2, 15.24)
    buck(241.3, 15.24)
    power_hold(241.3, 109.22)
    pi_header(10.16, 137.16)
    S.write(OUT)
    print("wrote", os.path.relpath(OUT))


if __name__ == "__main__":
    main()
