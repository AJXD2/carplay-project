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
               footprint="Connector_Molex:Molex_Micro-Fit_3.0_43045-2012_2x10_P3.00mm_Vertical")
    j.place_prop("Reference", -13.97, -22.86, "left")
    j.place_prop("Value", -13.97, -20.32, "left")
    for pin, net, col in [("+12V_BATT", "+12V_BATT", "power12"), ("ACC", "ACC_IN", "ctl"),
                          ("ILLUM", "ILLUM_IN", "ctl"), ("REV", "REV_IN", "ctl"), ("SWC1", "SWC1_IN", "swc"),
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
    cvs = C("100nF", fp=FP_C0805)                 # sees battery transients: 100 V part
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
                 footprint="Inductor_SMD:L_APV_APH0840")
    ind.move_pin_to("1", (sx + 25.4, sy))
    S.wire(sw, ct, ind.pin("1"))
    S.label((sx + 5.08, sy), "SW_5V", (0, -1), color=org, stub=0)   # net name for the PCB rules

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
    S.box(x, y, x + 152.4, y + 109.22, "POWER HOLD + KEY / LIGHTS / REVERSE SENSE", ctl)
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
    _sense(x + 83.82, y + 81.28, "REV_IN", "~{REVERSE}")

    S.text(x + 2.54, y + 100.33, "PI_HOLD (GPIO26): config.txt gpio=26=op,dh raises it ~1 s after power-up; "
           "dtoverlay=gpio-poweroff drops it once the Pi halts.", size=1.27)
    S.text(x + 2.54, y + 102.87, "Key off: the Pi syncs and halts, SYS_EN decays under 1.13 V ~2 s later and the "
           "LM74800 cuts everything (3 uA standby).", size=1.27)
    S.text(x + 2.54, y + 105.41, "ACC alone holds SYS_EN ~5 s (100k x 47 uF) so a crank before the Pi boots doesn't "
           "drop power. BZT52C15 limits load dump on the cap.", size=1.27)
    S.text(x + 2.54, y + 107.95, "Hung Pi: the BCM watchdog resets it, GPIO26 floats low (100k bleed), and the board "
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
    "13": ("~{LIGHTS_ON}", "ctl"), "26": ("~{REVERSE}", "ctl"), "38": ("I2S_DIN", "i2s"),
}
PI_UNUSED = ["24", "21", "19", "23"]   # SPI0 (GPIO8-11); GPIO7 carries ~REVERSE


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

CHANNELS = ["RL", "RR", "FL", "FR"]   # amp channel 1..4 (odd = left, SDIN L slot); board order FR FL RR RL


def _hcap(p):
    # labels clear of the plates on a horizontal cap
    p.place_prop("Reference", 0, -3.81)
    p.place_prop("Value", 0, 3.81)
    return p


def amplifier(x, y):
    """TAS6424E-Q1 after SLOSE73A fig 10-2 (4-ch BTL head unit)."""
    red, i2s, ctl = COLORS["power12"], COLORS["i2s"], COLORS["ctl"]
    spk = COLORS["spk"]
    S.box(x, y, x + 170.18, y + 154.94, "AMPLIFIER: TAS6424E-Q1, 4 x BTL, I2S from the Pi", spk)
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
    # PVDD bulk (fig 10-2's 470 uF), also the buck's CIN-BLK
    bx, by = x + 12.7, uy + 30.48
    S.power((bx, by), "+12V_PROT")
    S.wire((bx, by), (bx + 10.16, by), color=red)
    cb = shunt(C("470uF", fp="Capacitor_SMD:CP_Elec_10x12.5", polarized=True), (bx + 10.16, by))
    cb.place_prop("Value", 2.54, 1.27, "left")
    S.text(bx - 5.08, by + 17.78, "10 x 12.5 mm, 50 V, 105 C", size=1.27)
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
    S.label(u.pin("16"), "I2S_DOUT", (-1, 0), color=i2s)   # SDIN2 = SDIN1: rear plays front
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
            cb = C("1uF", rot=90)                  # 0603: fits the 0.635 mm pin pitch
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

    S.text(x + 2.54, y + 142.24, "I2S stereo on SDIN1 and SDIN2 (rear = front); per-channel volume registers do "
           "the fader. MCLK 256 fs from the audio clock block.", size=1.27)
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
                         footprint="Inductor_SMD:L_Chilisin_BMRx00060630")
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
    S.text(x + 2.54, y + 86.36, "Channel 1..4 = RL, RR, FL, FR (matches J1 order on the board). SDIN1 = SDIN2; fader via per-channel volume.",
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
    esd = S.part("Device:D_TVS", ref("D"), "H15VND3B", (0, 0), rot=90, footprint="Diode_SMD:D_SOD-323")
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
                 footprint="Battery:BatteryHolder_MYOUNG_BS-07-A1BJ001_CR2032")
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
                footprint="Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm", in_bom=False)
    jp.move_pin_to("1", wn)
    jp.place_prop("Reference", 2.54, -1.27, "left", rot=0)
    jp.place_prop("Value", 2.54, 1.27, "left", rot=0)
    S.power(jp.pin("2"), "GND")
    tp = S.part("Connector:TestPoint", ref("TP"), "WP", (wn[0] + 7.62, wn[1]),
                footprint="TestPoint:TestPoint_Pad_D1.5mm", in_bom=False)
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


# ------------------------------------------------------- audio clock master ---

def audio_clock(x, y):
    """The board is the I2S clock master. The Pi's PCM block only carries two
    channels, and the TAS6424 needs MCLK = 128-512 fs in I2S mode, so a
    12.288 MHz oscillator feeds the amp's MCLK and a PCM1808-Q1 in master mode
    (MD1 = MD0 = 1: 256 fs) divides it down to BCK = 64 fs and LRCK = 48 kHz.
    All three clocks come from one crystal, so they can never drift apart.
    The Pi runs its I2S port as a clock consumer (slave)."""
    i2s = COLORS["i2s"]
    S.box(x, y, x + 127, y + 81.28, "AUDIO CLOCKS: board is I2S master (48 kHz)", i2s)
    u = S.part("carrier:PCM1808-Q1", ref("U"), "PCM1808-Q1", (x + 76.2, y + 50.8),
               footprint="Package_SO:TSSOP-14_4.4x5mm_P0.65mm")
    u.place_prop("Reference", -8.89, 17.78, "right")
    u.place_prop("Value", -8.89, 20.32, "right")
    scki = u.pin("6")
    # 12.288 MHz oscillator, OUT level with SCKI, always enabled
    osc = S.part("Oscillator:ASE-xxxMHz", ref("X"), "12.288MHz", (0, 0),
                 footprint="Oscillator:Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm")
    osc.move_pin_to("3", (x + 30.48, scki[1]))
    osc.place_prop("Reference", -7.62, -6.35, "left")
    osc.place_prop("Value", 5.08, 5.08, "left")
    vdd, en = osc.pin("4"), osc.pin("1")
    top = (vdd[0], vdd[1] - 5.08)
    S.wire(vdd, top, (top[0] + 7.62, top[1]))
    S.wire(en, (en[0] - 2.54, en[1]), (en[0] - 2.54, top[1]), top)
    S.junction(top)
    S.power(top, "+3V3")
    shunt(C("100nF"), (top[0] + 7.62, top[1]))
    S.power(osc.pin("2"), "GND")
    # MCLK: one 33R at the source, then straight across to SCKI; tap to the amp
    out = osc.pin("3")
    rm = R("33R", rot=90)
    rm.move_pin_to("1", (out[0] + 2.54, out[1]))
    rm.place_prop("Reference", 0, -2.54)
    rm.place_prop("Value", 0, 2.54)
    S.wire(out, rm.pin("1"))
    mnode = (rm.pin("2")[0] + 5.08, out[1])
    S.wire(rm.pin("2"), mnode, scki, color=i2s)
    S.junction(mnode)
    S.label(mnode, "AMP_MCLK", (0, 1), color=i2s, stub=7.62)
    # straps: MD1 = MD0 = 1 (master, 256 fs), FMT = 0 (I2S)
    md0, md1, fmt = u.pin("10"), u.pin("11"), u.pin("12")
    tx = md0[0] - 5.08
    S.wire(md0, (tx, md0[1]))
    S.wire(md1, (tx, md1[1]))
    S.wire((tx, md1[1]), (tx, md0[1]), (tx, md0[1] - 5.08))
    S.junction((tx, md0[1]))
    S.power((tx, md0[1] - 5.08), "+3V3")
    S.wire(fmt, (fmt[0] - 2.54, fmt[1]))
    S.power((fmt[0] - 2.54, fmt[1]), "GND")
    lbl(u, "13", "MIC_IN", "i2s")               # VINL: the mic (section "mic")
    S.no_connect(u.pin("14"))                   # VINR unused
    dout = u.pin("9")
    rd = R("33R", rot=90)
    rd.move_pin_to("1", (dout[0] + 5.08, dout[1]))
    rd.place_prop("Reference", 0, -1.905)
    rd.hide_value = True
    S.wire(dout, rd.pin("1"))
    S.label(rd.pin("2"), "I2S_DIN", (1, 0), color=i2s, stub=5.08)
    # BCK / LRCK out through 33R to the Pi and the amp
    for pin, net in (("8", "I2S_BCLK"), ("7", "I2S_FSYNC")):
        pp = u.pin(pin)
        r = R("33R", rot=90)
        r.move_pin_to("1", (pp[0] + 5.08, pp[1]))
        r.place_prop("Reference", 0, -1.905 if pin == "8" else 1.905)
        r.hide_value = True
        S.wire(pp, r.pin("1"))
        S.label(r.pin("2"), net, (1, 0), color=i2s, stub=5.08)
    vref = u.pin("1")
    S.wire(vref, (vref[0] + 5.08, vref[1]))
    shunt(C("10uF", fp=FP_C0805), (vref[0] + 5.08, vref[1]))
    # supplies, raised clear of the chip: VCC 5 V left, VDD 3.3 V right
    vcc, vd = u.pin("3"), u.pin("4")
    t1 = (vcc[0], vcc[1] - 15.24)
    t2 = (vd[0], vd[1] - 20.32)
    S.wire(vcc, t1, (t1[0] - 7.62, t1[1]), (t1[0] - 20.32, t1[1]))
    S.wire(vd, t2, (t2[0] + 7.62, t2[1]), (t2[0] + 20.32, t2[1]))
    S.power(t1, "+5V")
    S.power(t2, "+3V3")
    S.junction(t1)
    S.junction(t2)
    for xx, val, fp in ((t1[0] - 7.62, "100nF", FP_C), (t1[0] - 20.32, "10uF", FP_C0805)):
        c = shunt(C(val, fp=fp), (xx, t1[1]))
        c.place_prop("Reference", -2.54, -1.27, "right")
        c.place_prop("Value", -2.54, 1.27, "right")
    S.junction((t1[0] - 7.62, t1[1]))
    for xx, val, fp in ((t2[0] + 7.62, "100nF", FP_C), (t2[0] + 20.32, "10uF", FP_C0805)):
        shunt(C(val, fp=fp), (xx, t2[1]))
    S.junction((t2[0] + 7.62, t2[1]))
    S.power(u.pin("2"), "GND")
    S.power(u.pin("5"), "GND")
    S.text(x + 2.54, y + 76.2, "Pi I2S = clock consumer (slave). MCLK 256 fs, BCK 64 fs, LRCK 48 kHz, one oscillator. "
           "PCM1808 ADC: mic on VINL, DOUT to the Pi.", size=1.27)
    S.text(x + 2.54, y + 78.74, "MD0/MD1 must be set before power-up (tied high). FMT low = I2S.", size=1.27)


# -------------------------------------------------------------------- mic ---

def mic(x, y):
    """Electret car mic on a 3.5 mm jack (mic on the tip, as hands-free kits
    wire it; ring and sleeve grounded so 2- and 3-pole plugs both work).
    Bias from +3V3 through a 1k + 10 uF filter and 2.2k, ESD diode and 1 nF
    RF shunt at the jack, 1 uF into the PCM1808's VINL (PCM1808-Q1
    datasheet: AC-coupled single-ended input). Gain is applied in software."""
    a = COLORS["i2s"]
    S.box(x, y, x + 132.08, y + 50.8, "MIC INPUT: electret, 3.5 mm jack -> PCM1808", a)
    x0, y0 = x + 12.7, y + 33.02
    S.label((x0, y0), "MIC_T", (-1, 0), color=a, stub=0)
    n, m, e = x0 + 7.62, x0 + 15.24, x0 + 35.56
    rb = R("2.2k")
    rb.move_pin_to("2", (n, y0))
    top = rb.pin("1")
    b = (top[0], top[1] - 5.08)
    S.wire(top, b, (b[0] + 7.62, b[1]))
    S.junction(b)
    shunt(C("10uF", fp=FP_C0805), (b[0] + 7.62, b[1]))
    rf = R("1k")
    rf.move_pin_to("2", b)
    S.power(rf.pin("1"), "+3V3")
    esd = S.part("Device:D_TVS", ref("D"), "H15VND3B", (0, 0), rot=90, footprint="Diode_SMD:D_SOD-323")
    esd.move_pin_to("2", (n, y0))
    esd.place_prop("Reference", 2.54, -1.27, "left", rot=0)
    esd.place_prop("Value", 2.54, 1.27, "left", rot=0)
    S.power(esd.pin("1"), "GND")
    cc = C("1uF", rot=90)
    cc.move_pin_to("1", (x0 + 22.86, y0))
    cc.place_prop("Reference", 0, -2.54)
    cc.place_prop("Value", 0, 2.54)
    S.wire((x0, y0), (n, y0), (m, y0), cc.pin("1"), color=a)
    S.junction((n, y0))
    S.junction((m, y0))
    shunt(C("1nF"), (m, y0))
    S.wire(cc.pin("2"), (e, y0), color=a)
    S.label((e, y0), "MIC_IN", (1, 0), color=a, stub=0)
    j = S.part("Connector_Audio:AudioJack4", ref("J"), "MIC", (x + 110.49, y + 27.94), rot=180,
               footprint="Connector_Audio:Jack_3.5mm_PJ320D_Horizontal")
    j.place_prop("Reference", 0, -10.16)
    j.place_prop("Value", 0, 10.16)
    lbl(j, "T", "MIC_T", "i2s")
    ends = {p: (j.pin(p)[0] - 5.08, j.pin(p)[1]) for p in ("R1", "R2", "S")}
    for p, e2 in ends.items():
        S.wire(j.pin(p), e2)
    ys = sorted(e2[1] for e2 in ends.values())
    S.wire((ends["R1"][0], ys[0]), (ends["R1"][0], ys[-1]))
    S.junction((ends["R1"][0], ys[1]))
    S.power((ends["R1"][0], ys[-1]), "GND")
    S.text(x + 2.54, y + 45.72, "Mic on the tip; ring + sleeve to GND. ~1.2 V bias at 0.5 mA. PCM1808 has no PGA: "
           "gain in software.", size=1.27)
    S.text(x + 2.54, y + 48.26, "Keep MIC_T / MIC_IN short and over solid GND, away from the amp outputs.", size=1.27)


# ------------------------------------------------------------------ leds ---

def leds(x, y):
    """Three debug LEDs: which power stage is alive (12 V after the
    protection, 5 V, and the Pi holding the board on). Red is the only
    basic-library 0603 LED at JLC, so all three are red, labelled."""
    S.box(x, y, x + 132.08, y + 40.64, "STATUS LEDS (12V IN / 5V / PI HOLD)", COLORS["misc"])
    for i, (net, rv, tag) in enumerate((("+12V_PROT", "10k", "12V ~1 mA"), ("+5V", "1k", "5V ~3 mA"),
                                        ("PI_HOLD", "1k", "PI HOLD ~1 mA"))):
        xx, yy = x + 22.86 + 38.1 * i, y + 12.7
        r = R(rv)
        r.move_pin_to("1", (xx, yy))
        if net.startswith("+"):
            S.power((xx, yy), net)
        else:
            S.label((xx, yy), net, (0, -1), color=COLORS["ctl"], stub=2.54)
        led = S.part("Device:LED", ref("D"), "RED", (0, 0), rot=90, footprint="LED_SMD:LED_0603_1608Metric")
        led.move_pin_to("2", r.pin("2"))
        led.place_prop("Reference", 3.81, -1.27, "left", rot=0)
        led.place_prop("Value", 3.81, 1.27, "left", rot=0)
        S.power(led.pin("1"), "GND")
        S.text(xx - 5.08, y + 35.56, tag, size=1.27)


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
               footprint="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", dnp=True)
    j.place_prop("Reference", 0, -6.35)
    j.place_prop("Value", 0, 6.35 + 2.54)
    S.label(j.pin("1"), "UART_TX", (1, 0), color=COLORS["misc"])
    S.label(j.pin("2"), "UART_RX", (1, 0), color=COLORS["misc"])
    S.power(j.pin("3"), "GND")
    # Pi holes: plain, unplated, isolated (HAT mechanical spec: 2.75 mm drill,
    # 6.2 mm keep-out). Heatsink screws: plated and grounded (SLOSE73A 12.1.1).
    for i in range(4):
        h = S.part("Mechanical:MountingHole", ref("H"), "Pi", (x + 38.1 + 10.16 * i, y + 38.1),
                   footprint="MountingHole:MountingHole_2.7mm_M2.5", in_bom=False)
        h.place_prop("Reference", 0, -7.62)
        h.place_prop("Value", 0, -5.08)
    for i in range(2):
        h = S.part("Mechanical:MountingHole_Pad", ref("H"), "Heatsink", (x + 78.74 + 10.16 * i, y + 38.1),
                   footprint="MountingHole:MountingHole_3.2mm_M3_Pad_Via", in_bom=False)
        h.place_prop("Reference", 0, -7.62)
        h.place_prop("Value", 0, -5.08)
        S.power(h.pin("1"), "GND")
    S.text(x + 2.54, y + 50.8, "Pi holes are isolated per the HAT spec; the amp heatsink screws ground the heatsink.",
           size=1.27)
    S.text(x + 2.54, y + 53.34, "UART: 3.3 V, GPIO14/15 serial console. Header not fitted: solder one on if needed.", size=1.27)


# ----------------------------------------------------------------- parts ---
# (value, footprint suffix) -> (MPN, manufacturer, LCSC). All checked in stock
# at JLCPCB 2026-09-22. Ceramics on +12V rails are 50 V X7R; the two 100 nF
# upstream of the load-dump cutoff are 100 V (the TVS clamps up to 53 V).

UR, FJ, SEM = "UNI-ROYAL", "FOJAN", "Samsung Electro-Mechanics"
PARTS = {
    ("0R", "R_0603"): ("0603WAF0000T5E", UR, "C21189"),
    ("33R", "R_0603"): ("0603WAF330JT5E", UR, "C23140"),
    ("100R", "R_0603"): ("0603WAF1000T5E", UR, "C22775"),
    ("1k", "R_0603"): ("0603WAF1001T5E", UR, "C21190"),
    ("3.65k", "R_0603"): ("FRC0603F3651TS", FJ, "C2930089"),
    ("3.9k", "R_0603"): ("0603WAF3901T5E", UR, "C23018"),
    ("5.11k", "R_0603"): ("FRC0603F5111TS", FJ, "C2933233"),
    ("10k", "R_0603"): ("0603WAF1002T5E", UR, "C25804"),
    ("24.9k", "R_0603"): ("0603WAF2492T5E", UR, "C25962"),
    ("26.7k", "R_0603"): ("FRC0603F2672TS", FJ, "C2930082"),
    ("33.2k", "R_0603"): ("FRC0603F3322TS", FJ, "C2933200"),
    ("47k", "R_0603"): ("0603WAF4702T5E", UR, "C25819"),
    ("95.3k", "R_0603"): ("FRC0603F9532TS", FJ, "C2907078"),
    ("100k", "R_0603"): ("0603WAF1003T5E", UR, "C25803"),
    ("22pF", "C_0603"): ("CL10C220JB8NNNC", SEM, "C1653"),
    ("1nF", "C_0603"): ("CL10C102JB8NNNC", SEM, "C163508"),
    ("10nF", "C_0603"): ("0603B103K500NT", "FH", "C57112"),
    ("100nF", "C_0603"): ("CC0603KRX7R9BB104", "YAGEO", "C14663"),
    ("100nF", "C_0805"): ("CL21B104KCFNNNE", SEM, "C28233"),
    ("220nF", "C_0603"): ("CL10B224KB8NNNC", SEM, "C64705"),
    ("22nF", "C_0805"): ("CL21B223KBANNNC", SEM, "C1729"),
    ("1uF", "C_0603"): ("CL10B105KB8NQNC", SEM, "C5199872"),
    ("1uF", "C_0805"): ("CL21B105KBFNNNE", SEM, "C28323"),
    ("2.2uF", "C_0805"): ("GRM21BR71E225KE11L", "Murata", "C77081"),
    ("10uF", "C_1206"): ("CL31B106KBHNNNE", SEM, "C89632"),
    ("10uF", "C_0805"): ("CL21A106KAYNNNE", SEM, "C15850"),
    ("47uF", "C_1210"): ("TMK325ABJ476MM-P", "Taiyo Yuden", "C90142"),
    ("470uF", "CP_Elec_10x12.5"): ("KAT1H471M10130PDT", "KNSCHA", "C55348714"),
    ("3.3uH", "L_Chilisin_BMRx00060630"): ("MHCI06030-3R3M-R8", "Chilisin", "C108294"),
    ("4.7uH", "L_APV_APH0840"): ("APH0840T4R7MP", "APV", "C54123781"),
    ("12.288MHz", ""): ("SX3M12.288B10F20TNN", "SCTF", "C7431335"),
    ("1N4148W", ""): ("1N4148W", "ST(Semtech)", "C81598"),
    ("BZT52C15", ""): ("BZT52C15", "hongjiacheng", "C19077412"),
    ("H15VND3B", ""): ("H15VND3B", "hongjiacheng", "C20615813"),
    ("2.2k", "R_0603"): ("0603WAF2201T5E", UR, "C4190"),
    ("RED", "LED_0603"): ("KT-0603R", "Hubei KENTO Elec", "C2286"),
    ("MIC", "Jack_3.5mm_PJ320D"): ("PJ-320D", "SHOU HAN", "C431535"),
    ("SMBJ33CA", ""): ("SMBJ33CA", "hongjiacheng", "C19077587"),
    ("MMBT3904", ""): ("MMBT3904", "Changjing", "C20526"),
    ("2N7002", ""): ("2N7002", "Changjing", "C8545"),
    ("BUK7Y4R8-60E", ""): ("BUK7Y4R8-60EX", "Nexperia", "C503619"),
    ("LM74800-Q1", ""): ("LM74800QDRRRQ1", "Texas Instruments", "C3215600"),
    ("LM61460-Q1", ""): ("LM61460AFSQRJRRQ1", "Texas Instruments", "C2876600"),
    ("TLV75533PDBV", ""): ("TLV75533PDBVR", "Texas Instruments", "C404027"),
    ("TAS6424E-Q1", ""): ("TAS6424EQDKQRQ1", "Texas Instruments", "C4991409"),
    ("ADS1115IDGS", ""): ("ADS1115IDGSR", "Texas Instruments", "C37593"),
    ("DS3231SN", ""): ("DS3231SN#T&R", "Analog Devices", "C9866"),
    ("CAT24C32", ""): ("CAT24C32WI-GT3", "onsemi", "C81193"),
    ("PCM1808-Q1", ""): ("PCM1808QPWRQ1", "Texas Instruments", "C2864157"),
    ("CR2032", ""): ("BS-07-A1BJ001", "MYOUNG", "C2979167"),
    ("Harness_4Runner", ""): ("430452012", "Molex", "C485575"),
    ("Pi 4 GPIO", ""): ("ZX-PM2.54-2-20PY", "Megastar", "C7499354"),
    ("FAN1", ""): ("470531000", "Molex", "C240840"),
    ("FAN2", ""): ("470531000", "Molex", "C240840"),
}


def assign_parts():
    missing = []
    for p in S.parts:
        if p.ref.startswith("#") or not p.in_bom:
            continue
        fp = (p.footprint or "").split(":")[-1]
        hit = PARTS.get((p.value, "")) or next(
            (v for (val, pre), v in PARTS.items() if val == p.value and pre and fp.startswith(pre)), None)
        if hit:
            p.fields.update({"MPN": hit[0], "Manufacturer": hit[1], "LCSC": hit[2]})
        elif not p.dnp:
            missing.append(f"{p.ref} {p.value} {fp}")
    if missing:
        raise SystemExit("no part number for: " + ", ".join(missing))


def section(name, fn, *args):
    """Run a section and tag its parts with a hidden Section field, which
    the PCB placement uses to find each block's parts."""
    n = len(S.parts)
    fn(*args)
    for p in S.parts[n:]:
        if not p.ref.startswith("#"):
            p.fields["Section"] = name


def main():
    # row 1
    section("harness", harness, 15.24, 15.24)
    section("protection", input_protection, 113.03, 15.24)
    section("swc", swc_adc, 278.13, 15.24)
    section("rtc", rtc_eeprom, 415.29, 15.24)
    # row 2
    section("pi", pi_header, 15.24, 134.62)
    section("hold", power_hold, 113.03, 137.16)
    section("buck", buck, 270.51, 132.08)
    # row 3
    section("misc", misc, 15.24, 236.22)
    section("amp", amplifier, 113.03, 251.46)
    section("filter", output_filter, 288.29, 226.06)
    section("fans", fans, 420.37, 226.06)
    section("clock", audio_clock, 288.29, 320.04)
    section("mic", mic, 420.37, 284.48)
    section("leds", leds, 420.37, 345.44)
    assign_parts()
    S.write(OUT)
    print("wrote", os.path.relpath(OUT))


if __name__ == "__main__":
    main()
