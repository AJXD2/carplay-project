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
    S.box(x, y, x + 93.98, y + 76.2, "HARNESS (Metra adapter)", (90, 90, 90))
    j = S.part("carrier:Harness_4Runner", ref("J"), "Harness_4Runner", (x + 44.45, y + 38.1),
               footprint="Connector_Molex:Molex_Micro-Fit_3.0_43045-2000_2x10_P3.00mm_Horizontal")
    j.place_prop("Reference", -13.97, -22.86, "left")
    j.place_prop("Value", -13.97, -20.32, "left")
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
    S.label((x + 15.24, rail), "+12V_BATT", (-1, 0), color=red, stub=0)
    tvs = S.part("Device:D_TVS", ref("D"), "SMBJ33CA", (0, 0), rot=90, footprint="Diode_SMD:D_SMB")
    tvs.move_pin_to("2", (x + 22.86, rail))
    tvs.place_prop("Reference", 2.54, -1.27, "left", rot=0)
    tvs.place_prop("Value", 2.54, 1.27, "left", rot=0)
    S.power(tvs.pin("1"), "GND")
    cin = shunt(C("100nF", fp=FP_C0805), (x + 33.02, rail))
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
    S.wire((x + 15.24, rail), q1.pin("1"), color=red)
    S.wire(q1.pin("5"), q2.pin("5"), color=red)
    S.junction(tvs.pin("2"))
    S.junction(cin.pin("1"))
    S.pwr_flag((x + 15.24, rail))                 # battery and ground enter here
    gf = (tvs.pin("1")[0] - 5.08, tvs.pin("1")[1])
    S.wire(tvs.pin("1"), gf)
    S.pwr_flag(gf)
    mid = (q1.pin("5")[0] + 12.7, rail)
    S.junction(mid)
    S.label(mid, "VMID", (0, -1), color=red)
    S.pwr_flag((mid[0] - 5.08, rail))
    S.junction((mid[0] - 5.08, rail))
    out_x = q2.pin("1")[0] + 30.48
    S.wire(q2.pin("1"), (out_x, rail), color=red)
    cout = shunt(C("100nF", fp=FP_C0805), (q2.pin("1")[0] + 20.32, rail))
    S.junction(cout.pin("1"))
    S.power((out_x, rail), "+12V_PROT")
    S.pwr_flag((out_x - 5.08, rail))
    S.junction((out_x - 5.08, rail))
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
    u.place_prop("Reference", 12.7, 7.62, "left")
    u.place_prop("Value", 12.7, 10.16, "left")
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
    S.text(x + 2.54, y + 111.76, "OV cutoff = 1.23 V x (95.3k + 5.11k + 3.65k) / 3.65k = 35.1 V.   BATT_MON = VBAT / 11.9 (to ADS1115 AIN2).", size=1.27)
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


# ----------------------------------------------------- amplifier U? (TAS6424) ---

CHANNELS = ["FL", "FR", "RL", "RR"]   # amp channel 1..4


def _hcap(p):
    # labels clear of the plates on a horizontal cap
    p.place_prop("Reference", 0, -3.81)
    p.place_prop("Value", 0, 3.81)
    return p


def amplifier(x, y):
    """TAS6424E-Q1 after SLOSE73A fig 10-2 (4-ch BTL head unit)."""
    red, i2s, ctl = COLORS["power12"], COLORS["i2s"], COLORS["ctl"]
    spk = COLORS["spk"]
    S.box(x, y, x + 170.18, y + 154.94, "AMPLIFIER: TAS6424E-Q1, 4 x BTL, TDM from the Pi", spk)
    ux, uy = x + 111.76, y + 78.74
    u = S.part("carrier:TAS6424E-Q1", ref("U"), "TAS6424E-Q1", (ux, uy),
               footprint="Package_SO:SSOP-56_7.5x18.5mm_P0.635mm")
    u.place_prop("Reference", -38.1, 48.26, "left")
    u.place_prop("Value", -38.1, 50.8, "left")

    # PVDD/VBAT bus with the per-pin-group bypass bank to its left
    yb = uy - 60.96
    pv = [u.pin(p) for p in ("2", "42", "55", "3")]
    bank = [ux - 27.94 - 10.16 * i for i in range(7)]
    S.power((ux - 96.52, yb), "+12V_PROT")
    S.wire((ux - 96.52, yb), *[(t, yb) for t in reversed(bank)], *[(p[0], yb) for p in pv], color=red)
    for p in pv:
        S.wire(p, (p[0], yb), color=red)
    for p in pv[:-1]:
        S.junction((p[0], yb))
    for t, (val, fp) in zip(bank, [("100nF", FP_C), ("10uF", FP_C1206)] * 3 + [("1uF", FP_C0805)]):
        shunt(C(val, fp=fp), (t, yb))
        S.junction((t, yb))
    vdd = u.pin("19")
    S.power(vdd, "+3V3")
    S.wire(vdd, (vdd[0] + 10.16, vdd[1]), color=COLORS["power3"])
    shunt(C("1uF"), (vdd[0] + 10.16, vdd[1]))

    # serial audio, control
    for pin, net, col in [("12", "AMP_MCLK", i2s), ("13", "I2S_BCLK", i2s), ("14", "I2S_FSYNC", i2s),
                          ("15", "I2S_DOUT", i2s), ("20", "I2C_SCL", COLORS["i2c"]),
                          ("21", "I2C_SDA", COLORS["i2c"]), ("24", "~{AMP_STBY}", ctl),
                          ("25", "~{AMP_MUTE}", ctl)]:
        S.label(u.pin(pin), net, (-1, 0), color=col)
    S.power(u.pin("16"), "GND")                       # SDIN2 unused in TDM
    a0, a1 = u.pin("22"), u.pin("23")                 # address 0x6A
    S.wire(a0, (a0[0] - 2.54, a0[1]), (a1[0] - 2.54, a1[1]), a1)
    S.junction((a1[0] - 2.54, a1[1]))
    S.power((a1[0] - 2.54, a1[1]), "GND")

    # analog bypass: VREG/VCOM -> AREF, AVDD -> AVSS (local returns), GVDD -> GND
    L = u.pin("5")[0]
    yv, yc, ya, yd, ys, yg = (u.pin(p)[1] for p in ("5", "6", "4", "8", "7", "9"))
    c1 = _hcap(C("1uF", rot=90))
    c1.move_pin_to("2", (L - 2.54, yv))
    S.wire(u.pin("5"), c1.pin("2"))
    S.wire(c1.pin("1"), (L - 17.78, yv), (L - 17.78, yc), (L - 17.78, ya), u.pin("4"))
    c2 = _hcap(C("1uF", rot=90))
    c2.move_pin_to("2", (L - 10.16, yc))
    S.wire(u.pin("6"), c2.pin("2"))
    S.junction((L - 17.78, yc))
    c3 = _hcap(C("1uF", rot=90))
    c3.move_pin_to("2", (L - 2.54, yd))
    S.wire(u.pin("8"), c3.pin("2"))
    S.wire(c3.pin("1"), (L - 12.7, yd), (L - 12.7, ys), u.pin("7"))
    S.wire(u.pin("9"), (L - 5.08, yg), (L - 17.78, yg))
    for t in (L - 5.08, L - 17.78):
        shunt(C("2.2uF", fp=FP_C0805), (t, yg))
    S.junction((L - 5.08, yg))

    # outputs: 1 uF boot caps BST -> OUT, then labels to the filter block
    for pin, net in [("26", "~{AMP_FAULT}"), ("27", "~{AMP_WARN}")]:
        S.label(u.pin(pin), net, (1, 0), color=ctl)
    for ch, (bp, op, om, bm) in zip(CHANNELS, [("35", "34", "32", "31"), ("41", "40", "38", "37"),
                                               ("48", "47", "45", "44"), ("54", "53", "51", "50")]):
        for bst, out, pol in [(bp, op, "+"), (bm, om, "-")]:
            b, o = u.pin(bst), u.pin(out)
            cb = C("1uF", rot=90, fp=FP_C0805)
            cb.move_pin_to("1", (b[0] + 5.08, b[1]))
            cb.place_prop("Reference", 7.62, 0)      # on the free BST row
            cb.place_prop("Value", 13.97, 0)
            S.wire(b, cb.pin("1"))
            tap = (cb.pin("2")[0], o[1])
            S.wire(cb.pin("2"), tap)
            S.wire(o, tap)
            S.junction(tap)
            S.label(tap, f"AMP_{ch}{pol}", (1, 0), color=spk, stub=10.16)
    for p in ("1", "18", "36", "49"):
        S.power(u.pin(p), "GND")

    S.text(x + 2.54, y + 142.24, "TDM4 on SDIN1, 32-bit slots, SCLK = 128 fs; MCLK = SCLK is allowed in TDM "
           "(SLOSE73A 9.3.1.4), jumper-selected in the clock block.", size=1.27)
    S.text(x + 2.54, y + 144.78, "~{STANDBY} / ~{MUTE} have 100k internal pull-downs: the amp stays silent "
           "until the Pi's I2C init. I2C address 0x6A.", size=1.27)
    S.text(x + 2.54, y + 147.32, "Bypass bank: one 10 uF + 100 nF pair at each PVDD group (2/29/30, 42/43, 55/56), "
           "1 uF at VBAT. Ceramics 50 V X7R.", size=1.27)
    S.text(x + 2.54, y + 149.86, "HSSOP-56 thermal pad is on TOP: clamp a GND-bonded heatsink on it. "
           "AREF and AVSS are local returns, not GND.", size=1.27)
    return u


def output_filter(x, y):
    """Per-leg LC reconstruction filter from SLOSE73A fig 10-2: 3.3 uH with
    1 uF + 1 nF to GND, for fSW = 2.1 MHz (corner ~88 kHz into 4 R)."""
    spk = COLORS["spk"]
    S.box(x, y, x + 127, y + 88.9, "OUTPUT FILTERS (2.1 MHz PWM -> speakers)", spk)
    for row, ch in enumerate(CHANNELS):
        for col, pol in enumerate("+-"):
            x0, y0 = x + 12.7 + col * 60.96, y + 15.24 + row * 17.78
            S.label((x0, y0), f"AMP_{ch}{pol}", (-1, 0), color=spk, stub=0)
            ind = S.part("Device:L", ref("L"), "3.3uH", (0, 0), rot=90,
                         footprint="Inductor_SMD:L_Wuerth_XHMI-6060")
            ind.move_pin_to("1", (x0 + 5.08, y0))
            ind.place_prop("Reference", 0, -2.54)
            ind.place_prop("Value", 0, 2.54)
            n1, n2, end = x0 + 17.78, x0 + 27.94, x0 + 35.56
            S.wire((x0, y0), ind.pin("1"), color=spk)
            S.wire(ind.pin("2"), (n1, y0), (n2, y0), (end, y0), color=spk)
            shunt(C("1uF", fp=FP_C0805), (n1, y0))
            shunt(C("1nF"), (n2, y0))
            S.junction((n1, y0))
            S.junction((n2, y0))
            S.label((end, y0), f"SPK_{ch}{pol}", (1, 0), color=spk, stub=0)
    S.text(x + 2.54, y + 83.82, "Inductors: 3.3 uH, Isat >= 6 A, DCR <= 50 mR (SLOSE73A 10.2.1.2.4). "
           "1 uF 50 V X7R, 1 nF C0G.", size=1.27)
    S.text(x + 2.54, y + 86.36, "Channel 1..4 = FL, FR, RL, RR (the Pi's TDM slot order; remap in software).",
           size=1.27)


# ------------------------------------------------------- SWC + battery ADC ---

def _swc_chain(x0, y0, net_in, net_out):
    """Ladder input: 1k pull-up makes the ladder a divider, ESD diode at the
    harness, 10k + 100 nF into the ADC. A short to 14 V pushes ~1 mA into
    the ADS1115's own clamps (rated 10 mA), so no external clamp."""
    swc = COLORS["swc"]
    S.label((x0, y0), net_in, (-1, 0), color=swc, stub=0)
    n = x0 + 7.62
    pu = R("1k")
    pu.move_pin_to("2", (n, y0))
    S.power(pu.pin("1"), "+3V3")
    esd = S.part("Device:D_TVS", ref("D"), "PESD5V0S1BL", (0, 0), rot=90, footprint="Diode_SMD:D_SOD-323")
    esd.move_pin_to("2", (n, y0))
    esd.place_prop("Reference", 2.54, -1.27, "left", rot=0)
    esd.place_prop("Value", 2.54, 1.27, "left", rot=0)
    S.power(esd.pin("1"), "GND")
    rs = R("10k", rot=90)
    rs.move_pin_to("1", (x0 + 17.78, y0))
    rs.place_prop("Reference", 0, -2.54)
    rs.place_prop("Value", 0, 2.54)
    m, end = x0 + 27.94, x0 + 35.56
    S.wire((x0, y0), (n, y0), rs.pin("1"), color=swc)
    S.wire(rs.pin("2"), (m, y0), (end, y0), color=swc)
    S.junction((n, y0))
    S.junction((m, y0))
    shunt(C("100nF"), (m, y0))
    S.label((end, y0), net_out, (1, 0), color=swc, stub=0)


def swc_adc(x, y):
    swc, i2c = COLORS["swc"], COLORS["i2c"]
    S.box(x, y, x + 132.08, y + 73.66, "STEERING WHEEL + BATTERY ADC (ADS1115)", swc)
    _swc_chain(x + 12.7, y + 20.32, "SWC1_IN", "SWC1_ADC")
    _swc_chain(x + 12.7, y + 48.26, "SWC2_IN", "SWC2_ADC")
    # wheel ladder ground: 0R link (fit a ferrite if the wheel picks up noise)
    S.label((x + 17.78, y + 63.5), "SWC_GND", (-1, 0), color=swc, stub=0)
    rg = R("0R", rot=90)
    rg.move_pin_to("1", (x + 20.32, y + 63.5))
    rg.place_prop("Reference", 0, -2.54)
    rg.place_prop("Value", 0, 2.54)
    S.wire((x + 17.78, y + 63.5), rg.pin("1"), color=swc)
    S.wire(rg.pin("2"), (x + 30.48, y + 63.5))
    S.power((x + 30.48, y + 63.5), "GND")

    u = S.part("Analog_ADC:ADS1115IDGS", ref("U"), "ADS1115IDGS", (x + 88.9, y + 38.1),
               footprint="Package_SO:TSSOP-10_3x3mm_P0.5mm")
    u.place_prop("Reference", -2.54, -20.32, "right")
    u.place_prop("Value", -2.54, -17.78, "right")
    S.label(u.pin("4"), "SWC1_ADC", (-1, 0), color=swc)
    S.label(u.pin("5"), "SWC2_ADC", (-1, 0), color=swc)
    a2, a3 = u.pin("6"), u.pin("7")
    S.wire(a2, (a2[0] - 12.7, a2[1]))
    S.label((a2[0] - 12.7, a2[1]), "BATT_MON", (-1, 0), color=swc)
    cf = shunt(C("10nF"), (a2[0] - 7.62, a2[1]))
    cf.place_prop("Reference", -2.54, -1.27, "right")
    cf.place_prop("Value", -2.54, 1.27, "right")
    S.junction((a2[0] - 7.62, a2[1]))
    S.wire(a3, (a3[0] - 2.54, a3[1]))
    S.power((a3[0] - 2.54, a3[1]), "GND")
    S.power(u.pin("1"), "GND")                    # ADDR low: 0x48
    S.power(u.pin("3"), "GND")
    S.label(u.pin("9"), "I2C_SDA", (1, 0), color=i2c)
    S.label(u.pin("10"), "I2C_SCL", (1, 0), color=i2c)
    al = u.pin("2")
    node = (al[0] + 5.08, al[1])
    S.wire(al, node)
    pu = R("10k")
    pu.move_pin_to("2", node)
    S.power(pu.pin("1"), "+3V3")
    S.junction(node)
    S.label(node, "~{ADC_ALERT}", (1, 0), color=swc, stub=7.62)
    vdd = u.pin("8")
    top = (vdd[0], vdd[1] - 10.16)
    S.wire(vdd, top, (top[0] + 7.62, top[1]))
    S.power(top, "+3V3")
    S.junction(top)
    shunt(C("100nF"), (top[0] + 7.62, top[1]))
    S.text(x + 50.8, y + 66.04, "AIN0/1: wheel ladders, learned in software (press each button once).", size=1.27)
    S.text(x + 50.8, y + 68.58, "AIN2: battery voltage (VBAT / 11.9). I2C address 0x48.", size=1.27)


# ---------------------------------------------------------- RTC + ID EEPROM ---

def rtc_eeprom(x, y):
    i2c, ctl = COLORS["i2c"], COLORS["ctl"]
    S.box(x, y, x + 132.08, y + 111.76, "RTC (DS3231SN + CR2032) + HAT ID EEPROM", i2c)
    u = S.part("carrier:DS3231SN", ref("U"), "DS3231SN", (x + 38.1, y + 35.56),
               footprint="Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm")
    u.place_prop("Reference", 10.16, 17.78, "left")
    u.place_prop("Value", 10.16, 20.32, "left")
    S.label(u.pin("16"), "I2C_SCL", (-1, 0), color=i2c)
    S.label(u.pin("15"), "I2C_SDA", (-1, 0), color=i2c)
    S.no_connect(u.pin("4"))
    S.no_connect(u.pin("1"))
    it = u.pin("3")
    node = (it[0] + 5.08, it[1])
    S.wire(it, node)
    pu = R("10k")
    pu.move_pin_to("2", node)
    S.power(pu.pin("1"), "+3V3")
    S.junction(node)
    S.label(node, "~{RTC_INT}", (1, 0), color=ctl, stub=7.62)
    vcc = u.pin("2")
    top = (vcc[0], vcc[1] - 7.62)
    S.wire(vcc, top, (top[0] - 10.16, top[1]))
    S.power(top, "+3V3")
    S.junction(top)
    shunt(C("100nF"), (top[0] - 10.16, top[1]))
    vb = u.pin("14")
    bt = (vb[0], vb[1] - 2.54)
    S.wire(vb, bt, (bt[0] + 15.24, bt[1]), (bt[0] + 30.48, bt[1]))
    S.pwr_flag((bt[0] + 15.24, bt[1]))
    S.junction((bt[0] + 15.24, bt[1]))
    bat = S.part("Device:Battery_Cell", ref("BT"), "CR2032", (0, 0),
                 footprint="Battery:BatteryHolder_Keystone_1060_1x2032")
    bat.move_pin_to("1", (bt[0] + 30.48, bt[1]))
    bat.place_prop("Reference", 3.81, -2.54, "left")
    bat.place_prop("Value", 3.81, 0, "left")
    S.power(bat.pin("2"), "GND")
    for p in ("13", "5", "9"):
        S.power(u.pin(p), "GND")

    # ID EEPROM per the Raspberry Pi HAT design guide
    e = S.part("Memory_EEPROM:24LC32", ref("U"), "CAT24C32", (x + 38.1, y + 83.82),
               footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
    e.place_prop("Reference", 3.81, 10.16, "left")
    e.place_prop("Value", 3.81, 12.7, "left")
    a0, a1, a2 = e.pin("1"), e.pin("2"), e.pin("3")
    ax = a0[0] - 2.54
    for p in (a0, a1, a2):
        S.wire(p, (ax, p[1]))
    S.wire((ax, a0[1]), (ax, a2[1]))
    S.junction((ax, a1[1]))
    S.power((ax, a2[1]), "GND")                   # 0x50
    S.power(e.pin("4"), "GND")
    ev = e.pin("8")
    et = (ev[0], ev[1] - 7.62)
    S.wire(ev, et, (et[0] - 15.24, et[1]))
    S.power(et, "+3V3")
    S.junction(et)
    shunt(C("100nF"), (et[0] - 15.24, et[1]))
    S.label(e.pin("5"), "ID_SDA", (1, 0), color=i2c)
    S.label(e.pin("6"), "ID_SCL", (1, 0), color=i2c)
    wp = e.pin("7")
    wn = (wp[0] + 15.24, wp[1])
    S.wire(wp, wn, (wn[0] + 7.62, wn[1]))
    S.junction(wn)
    rwp = R("1k")
    rwp.move_pin_to("2", wn)
    S.power(rwp.pin("1"), "+3V3")
    jp = S.part("Jumper:SolderJumper_2_Open", ref("JP"), "EEPROM_WP", (0, 0), rot=270,
                footprint="Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm")
    jp.move_pin_to("1", wn)
    jp.place_prop("Reference", 2.54, -1.27, "left", rot=0)
    jp.place_prop("Value", 2.54, 1.27, "left", rot=0)
    S.power(jp.pin("2"), "GND")
    tp = S.part("Connector:TestPoint", ref("TP"), "WP", (wn[0] + 7.62, wn[1]),
                footprint="TestPoint:TestPoint_Pad_D1.5mm")
    tp.place_prop("Reference", 1.27, -5.08, "left")
    tp.place_prop("Value", 1.27, -2.54, "left")
    for i, net in enumerate(("ID_SDA", "ID_SCL")):
        px = x + 104.14 + 10.16 * i
        r = R("3.9k")
        r.move_pin_to("1", (px, y + 71.12))
        S.power(r.pin("1"), "+3V3")
        S.label(r.pin("2"), net, (0, 1), color=i2c, stub=5.08)
    S.text(x + 2.54, y + 106.68, "RTC: kernel i2c-rtc,ds3231 overlay, 0x68. Keeps time with the key off; "
           "the Pi reads it at boot.", size=1.27)
    S.text(x + 2.54, y + 109.22, "EEPROM: 0x50 on ID_SD/ID_SC, 3.9k pull-ups, WP 1k up. Bridge JP to "
           "reflash (HAT design guide).", size=1.27)


# ------------------------------------------------- MCLK option (CS2100, DNP) ---

def clock_option(x, y):
    """Fallback if MCLK = SCLK misbehaves: CS2100-CP locks a clean 256 fs
    MCLK to FSYNC. Not fitted; the 0R from I2S_BCLK is the default."""
    i2s, i2c = COLORS["i2s"], COLORS["i2c"]
    S.box(x, y, x + 127, y + 71.12, "AMP MCLK SELECT (CS2100 option, not fitted)", i2s)
    u = S.part("carrier:CS2100-CP", ref("U"), "CS2100-CP", (x + 45.72, y + 40.64),
               footprint="Package_SO:MSOP-10_3x3mm_P0.5mm", dnp=True)
    u.place_prop("Reference", -17.78, 20.32, "left")
    u.place_prop("Value", -17.78, 22.86, "left")
    S.label(u.pin("5"), "I2S_FSYNC", (-1, 0), color=i2s)
    S.label(u.pin("7"), "XTI", (-1, 0))
    S.label(u.pin("6"), "XTO", (-1, 0))
    S.label(u.pin("9"), "I2C_SCL", (-1, 0), color=i2c)
    S.label(u.pin("10"), "I2C_SDA", (-1, 0), color=i2c)
    S.power(u.pin("8"), "GND")                    # AD0 low: 0x4E
    S.power(u.pin("2"), "GND")
    S.no_connect(u.pin("4"))
    vd = u.pin("1")
    top = (vd[0], vd[1] - 7.62)
    S.wire(vd, top, (top[0] - 10.16, top[1]))
    S.power(top, "+3V3")
    S.junction(top)
    shunt(C("100nF", dnp=True), (top[0] - 10.16, top[1]))
    # MCLK select: fit exactly one of the two 0R links
    co = u.pin("3")
    r_cs = R("0R", rot=90, dnp=True)
    r_cs.move_pin_to("1", (co[0] + 7.62, co[1]))
    r_cs.place_prop("Reference", 0, 2.54)
    r_cs.place_prop("Value", 0, 5.08)
    node = (co[0] + 20.32, co[1])
    S.wire(co, r_cs.pin("1"))
    S.wire(r_cs.pin("2"), node)
    r_bc = R("0R", rot=90)
    r_bc.move_pin_to("1", (co[0] + 7.62, co[1] - 10.16))
    r_bc.place_prop("Reference", 0, -2.54)
    r_bc.place_prop("Value", 0, -5.08)
    S.label(r_bc.pin("1"), "I2S_BCLK", (-1, 0), color=i2s, stub=5.08)
    S.wire(r_bc.pin("2"), (node[0], r_bc.pin("2")[1]), node, color=i2s)
    S.junction(node)
    S.label(node, "AMP_MCLK", (1, 0), color=i2s, stub=7.62)
    # 12 MHz reference crystal
    cx, cy = x + 91.44, y + 48.26
    S.label((cx - 7.62, cy), "XTI", (-1, 0), stub=0)
    xt = S.part("Device:Crystal", ref("Y"), "12MHz", (0, 0), footprint="Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
                dnp=True)
    xt.move_pin_to("1", (cx - 3.81 + 0.0, cy))
    xt.place_prop("Reference", 0, -3.81)
    xt.place_prop("Value", 0, -6.35)
    S.wire((cx - 7.62, cy), xt.pin("1"))
    S.wire(xt.pin("2"), (xt.pin("2")[0] + 3.81, cy))
    S.label((xt.pin("2")[0] + 3.81, cy), "XTO", (1, 0), stub=0)
    for px, side in ((cx - 7.62, -1), (xt.pin("2")[0] + 3.81, 1)):
        c = shunt(C("18pF", dnp=True), (px, cy))
        if side < 0:
            c.place_prop("Reference", -2.54, -1.27, "right")
            c.place_prop("Value", -2.54, 1.27, "right")
        S.junction((px, cy))
    S.text(x + 2.54, y + 66.04, "Default: R (I2S_BCLK) fitted, MCLK = SCLK in TDM. Option: fit U, Y, caps "
           "and the CLK_OUT 0R instead, remove the BCLK 0R.", size=1.27)
    S.text(x + 2.54, y + 68.58, "CS2100 I2C address 0x4E.", size=1.27)


# ------------------------------------------------------------------- fans ---

def _fan(x, y, n):
    fan = COLORS["fan"]
    f = S.part("Motor:Fan_4pin", ref("M"), f"FAN{n}", (x, y),
               footprint="Connector:FanPinHeader_1x04_P2.54mm_Vertical")
    f.place_prop("Reference", 5.08, -1.27, "left")
    f.place_prop("Value", 5.08, 1.27, "left")
    S.power(f.pin("2"), "+5V")
    S.power(f.pin("1"), "GND")
    # tach: open collector in the fan, pulled to 3.3 V here
    t = f.pin("3")
    tn = (t[0] - 5.08, t[1])
    S.wire(t, tn, (t[0] - 20.32, t[1]), color=fan)
    S.junction(tn)
    pu = R("10k")
    pu.move_pin_to("2", tn)
    pu.place_prop("Reference", -2.54, -1.27, "right")
    pu.place_prop("Value", -2.54, 1.27, "right")
    S.power(pu.pin("1"), "+3V3")
    S.label((t[0] - 20.32, t[1]), f"FAN{n}_TACH", (-1, 0), color=fan, stub=0)
    # PWM: fan pulls its PWM input up internally; the FET pulls it low.
    # Gate pull-down means a dead Pi leaves the fans at full speed.
    p = f.pin("4")
    q = S.part("Transistor_FET:2N7002", ref("Q"), "2N7002", (0, 0), footprint="Package_TO_SOT_SMD:SOT-23")
    q.move_pin_to("3", (p[0] - 7.62, p[1] + 5.08))
    q.place_prop("Reference", 5.08, 1.27, "left")
    q.place_prop("Value", 5.08, 3.81, "left")
    S.wire(p, (p[0] - 7.62, p[1]), q.pin("3"), color=fan)
    S.power(q.pin("2"), "GND")
    g = q.pin("1")
    gn = (g[0] - 5.08, g[1])
    S.wire(g, gn, (g[0] - 12.7, g[1]), color=fan)
    S.junction(gn)
    pd = shunt(R("100k"), gn)
    pd.place_prop("Reference", -2.54, -1.27, "right")
    pd.place_prop("Value", -2.54, 1.27, "right")
    S.label((g[0] - 12.7, g[1]), f"FAN{n}_PWM", (-1, 0), color=fan, stub=0)


def fans(x, y):
    S.box(x, y, x + 132.08, y + 50.8, "FANS (2 x Noctua 5 V PWM)", COLORS["fan"])
    _fan(x + 50.8, y + 20.32, 1)
    _fan(x + 116.84, y + 20.32, 2)
    S.text(x + 2.54, y + 45.72, "PWM from the Pi's hardware PWM (GPIO12/13) at 25 kHz, inverted by the FET. "
           "Tach: 2 pulses per turn.", size=1.27)
    S.text(x + 2.54, y + 48.26, "Fan PWM inputs float high inside the fan: no Pi, full speed.", size=1.27)


# --------------------------------------------------- debug UART, mechanical ---

def misc(x, y):
    grey = (90, 90, 90)
    S.box(x, y, x + 93.98, y + 55.88, "DEBUG UART + MOUNTING", grey)
    j = S.part("Connector:Conn_01x03_Pin", ref("J"), "UART", (x + 10.16, y + 17.78),
               footprint="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical")
    j.place_prop("Reference", 0, -6.35)
    j.place_prop("Value", 0, 6.35 + 2.54)
    S.label(j.pin("1"), "UART_TX", (1, 0), color=COLORS["misc"])
    S.label(j.pin("2"), "UART_RX", (1, 0), color=COLORS["misc"])
    S.power(j.pin("3"), "GND")
    holes = [("Pi", "MountingHole:MountingHole_2.7mm_M2.5_Pad_Via")] * 4 + \
            [("Heatsink", "MountingHole:MountingHole_3.2mm_M3_Pad_Via")] * 2
    for i, (val, fp) in enumerate(holes):
        h = S.part("Mechanical:MountingHole_Pad", ref("H"), val, (x + 38.1 + 10.16 * i, y + 38.1), footprint=fp)
        h.place_prop("Reference", 0, -7.62)
        h.place_prop("Value", 0, -5.08)
        S.power(h.pin("1"), "GND")
    S.text(x + 2.54, y + 50.8, "Pi holes and the amp heatsink screws bond the Pi, heatsink and board GND.",
           size=1.27)
    S.text(x + 2.54, y + 53.34, "UART: 3.3 V, GPIO14/15 serial console.", size=1.27)


def main():
    # row 1
    harness(15.24, 15.24)
    input_protection(113.03, 15.24)
    swc_adc(278.13, 15.24)
    rtc_eeprom(415.29, 15.24)
    # row 2
    pi_header(15.24, 134.62)
    power_hold(113.03, 137.16)
    buck(270.51, 132.08)
    # row 3
    misc(15.24, 236.22)
    amplifier(113.03, 226.06)
    output_filter(288.29, 226.06)
    fans(420.37, 226.06)
    clock_option(288.29, 320.04)
    S.write(OUT)
    print("wrote", os.path.relpath(OUT))


if __name__ == "__main__":
    main()
