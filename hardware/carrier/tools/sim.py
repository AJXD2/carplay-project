#!/usr/bin/env python3
"""SPICE testbenches for the carrier board's analog circuits.

    .venv/bin/python tools/sim.py [block ...]      # all blocks by default

Each block builds its decks from the values in gen_sch.py (line numbers are
cited next to each deck), runs them through KiCad's libngspice
(tools/ngspice_run.py, inside the Flatpak), checks pass/fail limits and
writes out/sim/<block>.png plus out/sim/results.json. Exit status 1 if any
check fails.

The ICs are behavioural stand-ins built from datasheet numbers (TI's own
models are encrypted PSpice or don't exist): they check the parts around
the chips, not the chips.
"""
import json
import os
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "out", "sim")

# Values copied from gen_sch.py (update both together).
R_ACC = 10e3                          # gen_sch.py power_hold(): ACC -> D -> R -> SYS_EN
R_OV_TOP, R_OV_MID, R_OV_BOT = 95.3e3, 5.11e3, 3.74e3   # gen_sch.py input_protection(): OV ladder

# ---------------------------------------------------------------- models ---
# Diodes/BJT/FET: vendor-published SPICE parameters (Diodes Inc / onsemi).
MODELS = """
.model D1N4148 D(Is=2.52n Rs=0.568 N=1.752 Cjo=4p M=0.4 tt=20n BV=75 IBV=5u)
.model DZ15 D(Is=1n Rs=5 N=1.5 BV=15 IBV=5m)
.model Q3904 NPN(Is=6.734f Xti=3 Eg=1.11 Vaf=74.03 Bf=416.4 Ne=1.259 Ise=6.734f Ikf=66.78m Xtb=1.5
+ Br=.7371 Nc=2 Isc=0 Ikr=0 Rc=1 Cjc=3.638p Mjc=.3085 Vjc=.75 Fc=.5 Cje=4.493p Mje=.2593 Vje=.75
+ Tr=239.5n Tf=301.2p Itf=.4 Vtf=4 Xtf=2 Rb=10)
.model DESD D(Is=1f N=1 BV=16 IBV=1u)
.model DCLAMP D(Is=1e-14 N=1)
"""


def x5r_47u(v):
    """TMK325ABJ476MM (25 V X5R 1210) DC-bias factor, typical high-CV 1210
    curve: ~-45% at 5 V, ~-60% at 8 V. Taiyo Yuden's own curve wasn't
    reachable; the 'mild' corner brackets it from the other side."""
    return f"1/(1+pow(abs({v})/{{VK}},1.5))"


# ----------------------------------------------------------------- engine ---
def run(name, deck):
    """Run one deck, return (plots, log)."""
    os.makedirs(OUT, exist_ok=True)
    cir = os.path.join(OUT, name + ".cir")
    js = os.path.join(OUT, name + ".json")
    with open(cir, "w") as f:
        f.write(deck)
    r = subprocess.run(["flatpak", "run", "--command=python3", "org.kicad.KiCad",
                        os.path.join(HERE, "ngspice_run.py"), cir, js],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode or not os.path.exists(js):
        raise SystemExit(f"{name}: ngspice run failed\n{r.stdout}\n{r.stderr}")
    d = json.load(open(js))
    errs = [line for line in d["log"] if "error" in line.lower() and "rms" not in line.lower()]
    if errs:
        raise SystemExit(f"{name}: " + "\n".join(errs))
    return d["plots"], d["log"]


def last_plot(plots, kind):
    names = sorted((p for p in plots if p.startswith(kind)), key=lambda s: int(s[len(kind):] or 0))
    return plots[names[-1]]


def vec(plot, name):
    v = plot[name]
    if isinstance(v, dict):
        return np.array(v["re"]) + 1j * np.array(v["im"])
    return np.array(v)


RESULTS = []


def check(block, item, value, limit, ok, unit=""):
    RESULTS.append({"block": block, "item": item, "value": value, "limit": limit,
                    "pass": bool(ok), "unit": unit})
    mark = "PASS" if ok else "FAIL"
    val = f"{value:.4g}" if isinstance(value, (int, float)) else str(value)
    print(f"  [{mark}] {item}: {val} {unit}  (limit {limit})")


def note(block, item, value, unit=""):
    RESULTS.append({"block": block, "item": item, "value": value, "limit": None,
                    "pass": None, "unit": unit})
    val = f"{value:.4g}" if isinstance(value, (int, float)) else str(value)
    print(f"  [info] {item}: {val} {unit}")


def cross(t, y, level, falling=True, after=0.0):
    """First time y crosses level (linear interpolation), or None."""
    m = t >= after
    t, y = t[m], y[m]
    s = (y < level) if falling else (y > level)
    idx = np.argmax(s)
    if not s[idx]:
        return None
    if idx == 0:
        return t[0]
    t0, t1, y0, y1 = t[idx - 1], t[idx], y[idx - 1], y[idx]
    return t0 + (level - y0) * (t1 - t0) / (y1 - y0)


# ------------------------------------------------------------ power hold ---
# gen_sch.py power_hold(). ACC_IN -> 1N4148W -> R_ACC -> SYS_EN; PI_HOLD -> 1k ->
# 1N4148W -> SYS_EN; SYS_EN: 100k bleed, 47 uF (TMK325ABJ476MM), BZT52C15.
# LM74800 EN/UVLO (SNOSD95C 7.5): rising 1.195/1.231/1.267 V, falling
# 1.091/1.132/1.159 V, low-Iq shutdown V(ENF) 0.3/0.67/0.93 V, pin current
# 52 nA typ / 200 nA max.
UVLOR = (1.195, 1.231, 1.267)
UVLOF = (1.091, 1.132, 1.159)
ENF = (0.3, 0.67, 0.93)

HOLD_CORNERS = {
    # name: (cap factor, VK for the DC-bias curve, bleed factor, EN current)
    "nominal": (1.0, 6.0, 1.0, 52e-9),
    "short": (0.8, 4.5, 0.99, 200e-9),     # -20% cap, steep derating, -1% bleed
    "long": (1.2, 12.0, 1.01, 0.0),        # +20% cap, mild derating, +1% bleed
}


def hold_deck(corner, acc_pwl, pi_pwl, tstop, title):
    cf, vk, rf, ien = HOLD_CORNERS[corner]
    return f"""* power hold: {title} ({corner})
.param VK={vk}
{MODELS}
VACC acc 0 PWL({acc_pwl})
VPI pio 0 PWL({pi_pwl})
RPI pio pih 40
D1 acc n1 D1N4148
R1 n1 en {R_ACC:g}
R2 pih n2 1k
D2 n2 en D1N4148
RB en 0 {100e3 * rf}
CH en 0 C='{47e-6 * cf}*{x5r_47u('v(en)')}'
DZ 0 en DZ15
RZL en 0 210Meg
IEN en 0 {ien}
.tran 1m {tstop} 0 5m uic
.ic v(en)=0
.control
run
.endc
.end
"""


def block_power_hold():
    b = "power_hold"
    print(f"\n== {b}")
    fig, ax = plt.subplots(2, 2, figsize=(13, 8))
    # A: ACC on only briefly (key straight to START), then crank, Pi not up yet.
    # Toyota drops ACC while cranking. How long a crank can the board ride out?
    for i, (pre, lab) in enumerate([(0.3, "ACC 0.3 s then crank"), (3.0, "ACC 3 s then crank"),
                                    (30.0, "ACC steady then crank")]):
        pwl = f"0 0 1m 12.6 {pre} 12.6 {pre + 1e-3} 0"
        rides = {}
        for corner in HOLD_CORNERS:
            p = last_plot(run(f"hold_crank_{i}_{corner}", hold_deck(corner, pwl, "0 0", pre + 40, lab))[0], "tran")
            t, v = vec(p, "time"), vec(p, "en")
            ton = cross(t, v, UVLOR[2], falling=False)
            toff = cross(t, v, UVLOF[2], after=pre)
            rides[corner] = (toff - pre) if toff else 99
            if i == 2 and corner == "nominal":
                note(b, "key on: SYS_EN reaches UVLO rising (max 1.267 V) after", ton * 1e3, "ms")
                note(b, "key on: SYS_EN steady level at 12.6 V ACC", float(v[t < pre][-1]), "V")
            ax[0][0].plot(t, v, label=f"{lab} / {corner}", lw=1)
        note(b, f"{lab}: crank ride-through per corner",
             ", ".join(f"{c} {r:.1f} s" for c, r in rides.items()))
        worst = min(rides.values())
        check(b, f"{lab}: crank ride-through before power cut (worst corner)", worst,
              ">= 3 s (typical crank)", worst >= 3.0, "s")
    ax[0][0].axhline(UVLOF[2], ls="--", c="k", lw=0.8)
    ax[0][0].set(title="Crank before the Pi holds power (ACC drops at the dotted time)",
                 xlabel="s", ylabel="SYS_EN (V)", xlim=(0, 40))
    ax[0][0].legend(fontsize=6)

    # B: normal key-off. Pi holds (GPIO26 = 3.3 V), ACC off at 5 s, Pi halts and
    # drops the hold 8 s + ~5 s shutdown later (t = 18 s).
    acc = "0 0 1m 14.4 5 14.4 5.001 0"
    pi = "0 0 1 0 1.001 3.3 18 3.3 18.001 0"
    for corner in HOLD_CORNERS:
        p = last_plot(run(f"hold_keyoff_{corner}", hold_deck(corner, acc, pi, 60, "key off"))[0], "tran")
        t, v = vec(p, "time"), vec(p, "en")
        held = float(v[(t > 14) & (t < 18)].min())
        if corner == "nominal":
            check(b, "key off, Pi holding: SYS_EN held at", held, f"> {UVLOR[2]} V (UVLO rising max)",
                  held > UVLOR[2], "V")
        t_off = [cross(t, v, lv, after=18.0) for lv in UVLOF]
        t_q = [cross(t, v, lv, after=18.0) for lv in ENF]
        worst_off = max(x - 18 for x in t_off if x) if all(t_off) else 99
        note(b, f"Pi drops hold -> load cut (V < V(UVLOF) 1.09..1.16 V), {corner}", worst_off, "s")
        worst_q = (max(t_q) - 18) if all(t_q) else float("inf")
        note(b, f"Pi drops hold -> 3 uA shutdown (V < V(ENF) 0.3..0.93 V), {corner}, worst", worst_q, "s")
        ax[0][1].plot(t, v, label=corner, lw=1)
    for lv in UVLOF + ENF:
        ax[0][1].axhline(lv, ls=":", c="gray", lw=0.6)
    ax[0][1].set(title="Key off at 5 s, Pi drops PI_HOLD at 18 s", xlabel="s", ylabel="SYS_EN (V)")
    ax[0][1].legend(fontsize=7)

    # C: load dump on ACC (ISO 16750-2 test B, clamped 35 V for 400 ms) and an
    # unclamped 53 V (TVS clamp level, in case ACC shares the battery feed).
    for vd in (35, 53):
        acc = f"0 0 1m 14 2 14 2.005 {vd} 2.4 {vd} 2.405 14 4 14"
        p = last_plot(run(f"hold_dump_{vd}", hold_deck("nominal", acc, "0 0", 4, "load dump"))[0], "tran")
        t, v = vec(p, "time"), vec(p, "en")
        check(b, f"ACC load dump {vd} V: SYS_EN peak", float(v.max()), "< 65 V (EN abs max) and < 25 V (47 uF rating)",
              v.max() < 25, "V")
        ax[1][0].plot(t, v, label=f"{vd} V dump")
    ax[1][0].set(title="Load dump on ACC", xlabel="s", ylabel="SYS_EN (V)")
    ax[1][0].legend(fontsize=7)
    ax[1][1].axis("off")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "power_hold.png"), dpi=110)
    plt.close(fig)


# ----------------------------------------------------------------- sense ---
# gen_sch.py:334-361. IN -> 47k -> base; 10k + 100 nF base to GND; MMBT3904;
# 10k collector pull-up to +3V3. Used for ACC, ILLUM and REV.
def sense_deck(src, analysis):
    return f"""* key/lights/reverse sense
{MODELS}
{src}
RS in b 47k
RBE b 0 10k
CB b 0 100n
Q1 c b 0 Q3904
RPU v33 c 10k
V33 v33 0 3.3
{analysis}
.control
run
.endc
.end
"""


def block_sense():
    b = "sense"
    print(f"\n== {b}")
    fig, ax = plt.subplots(1, 2, figsize=(12, 4))
    p = last_plot(run("sense_dc", sense_deck("VIN in 0 0", ".dc VIN 0 40 0.05"))[0], "dc")
    vin, vc = vec(p, "v(in-sweep)") if "v(in-sweep)" in p else vec(p, "in"), vec(p, "c")
    ib = (vin - vec(p, "b")) / 47e3 - vec(p, "b") / 10e3
    th = cross(vin, vc, 1.65)
    check(b, "input threshold (GPIO reads active)", th, "between 3 V and 8 V (off at 0-2 V, on from 9 V)",
          3.0 < th < 8.0, "V")
    v9 = float(np.interp(9.0, vin, vc))
    check(b, "GPIO level at 9 V input (cranking, lights on)", v9, "< 0.8 V (Pi VIL)", v9 < 0.8, "V")
    v2 = float(np.interp(2.0, vin, vc))
    check(b, "GPIO level at 2 V input (leakage / ground offset)", v2, "> 2.0 V (Pi VIH)", v2 > 2.0, "V")
    ib40 = float(np.interp(40.0, vin, ib))
    check(b, "base current at 40 V load dump", ib40 * 1e3, "< 1 mA (design note); MMBT3904 abs 200 mA",
          ib40 < 1e-3, "mA")
    p47 = (40 - float(np.interp(40.0, vin, vec(p, "b")))) ** 2 / 47e3
    check(b, "47k dissipation at 40 V", p47 * 1e3, "< 100 mW (0603)", p47 < 0.1, "mW")
    ax[0].plot(vin, vc)
    ax[0].set(title="Sense DC transfer", xlabel="input (V)", ylabel="GPIO (V)")
    # Lights input PWM-dimmed (some trucks dim the ILL+ feed): 200 Hz, 50 %.
    for f in (100, 200, 1000):
        per = 1 / f
        src = f"VIN in 0 PULSE(0 12.6 0 10u 10u {per / 2} {per})"
        pp = last_plot(run(f"sense_pwm_{f}", sense_deck(src, f".tran 10u {max(0.1, 20 * per)} 0 10u"))[0], "tran")
        t, vcc = vec(pp, "time"), vec(pp, "c")
        tail = t > t[-1] - 3 * per
        lo, hi = float(vcc[tail].min()), float(vcc[tail].max())
        note(b, f"ILLUM PWM {f} Hz 50%: GPIO swings {lo:.2f}..{hi:.2f} V",
             "toggles (software must treat as on)" if hi > 2.0 and lo < 0.8 else "steady")
        ax[1].plot(t[tail] - t[tail][0], vcc[tail], label=f"{f} Hz")
    ax[1].set(title="Lights input PWM-dimmed", xlabel="s", ylabel="GPIO (V)")
    ax[1].legend()
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "sense.png"), dpi=110)
    plt.close(fig)


# ----------------------------------------------------- input protection ---
# gen_sch.py:93-194. OV ladder 95.3k / 5.11k / 3.65k (1 %), LM74800 V(OVR)
# 1.195..1.267 V, V(OVF) 1.091..1.159 V. HGATE source 39/55/75 uA into
# 100R + 22 nF (gen_sch.py:143-146). Load: 470 uF + ceramics on +12V_PROT.
def block_input_protection():
    b = "input_protection"
    print(f"\n== {b}")
    r1, r2, r3 = R_OV_TOP, R_OV_MID, R_OV_BOT
    tol = 0.01
    lo = min(v * (a + b_ + c) / c for v in (UVLOR[0],) for a in (r1 * (1 - tol),)
             for b_ in (r2 * (1 - tol),) for c in (r3 * (1 + tol),))
    hi = UVLOR[2] * (r1 * (1 + tol) + r2 * (1 + tol) + r3 * (1 - tol)) / (r3 * (1 - tol))
    nom = 1.231 * (r1 + r2 + r3) / r3
    rec = UVLOF[0] * (r1 * (1 - tol) + r2 * (1 - tol) + r3 * (1 + tol)) / (r3 * (1 + tol))
    note(b, "OV cutoff nominal", nom, "V")
    check(b, "OV cutoff lowest (all tolerances)", lo, "> 32 V (no trip in a 24 V jump start / 16 V charging)", lo > 32, "V")
    check(b, "OV cutoff highest (all tolerances)", hi, "<= 36 V (LM61460 operating max; abs max 42 V)", hi <= 36.0, "V")
    check(b, "OV cutoff highest vs TAS6424 PVDD", hi, "<= 40 V for <= 400 ms (load dump rating)", hi <= 40, "V")
    note(b, "OV recovery (lowest)", rec, "V")
    note(b, "BATT_MON ratio (ADS1115 AIN2)", (r1 + r2 + r3) / (r2 + r3), "x")

    # Soft start into the rail. Q2 as a source follower from HGATE (BUK7Y4R8-60E:
    # Vgs(th) ~3 V, gm large; modelled as Vgs = 3 V + I/gm). Buck: constant-power
    # load from 6 V (its EN UVLO) drawing the Pi's boot power, plus charging its
    # 94 uF output via its soft start (a few ms, folded into the constant power).
    fig, ax = plt.subplots(1, 2, figsize=(12, 4))
    worst_ipk = 0
    for ig, lab in ((39e-6, "min"), (55e-6, "typ"), (75e-6, "max")):
        deck = f"""* LM74800 soft start ({lab} HGATE current)
{MODELS}
VB bat 0 PWL(0 0 10u 12.6)
RH bat a 20m
IHG 0 hg {ig}
DHG hg hgc DCLAMP
VHGC hgc out 11.1
R4 hg cd 100
CD cd 0 22n
* Q2 BUK7Y4R8-60E (Vgs(th) 3 V typ, Ciss ~3.5 nF, Crss ~0.2 nF)
.model BUK7Y VDMOS(Rd=2m Rs=1m Vto=3 Kp=100 Cgs=3.3n Cgdmax=1n Cgdmin=0.15n a=0.5 Cjo=1n Is=1e-12)
VQ a ad 0
M2 ad hg out out BUK7Y
CB out ob 470u IC=0
RESR ob 0 0.1
CCER out 0 30u
* buck as a ~10 W constant-power load once VIN passes its 6 V EN UVLO
BL out 0 I=10/max(v(out),6)*0.5*(1+tanh(5*(v(out)-6)))
.tran 1u 30m 0 2u uic
.control
run
.endc
.end
"""
        p = last_plot(run(f"inrush_{lab}", deck)[0], "tran")
        t, vo, va = vec(p, "time"), vec(p, "out"), vec(p, "a")
        i = vec(p, "vq#branch")
        slew = np.max(np.gradient(vo, t)) / 1e3
        ipk = float(i.max())
        worst_ipk = max(worst_ipk, ipk)
        pd = (va - vo) * i
        e = float(np.trapezoid(pd, t))
        tr = cross(t, vo, 12.0, falling=False)
        check(b, f"inrush slew ({lab} HGATE current)", slew, "< 75 V/ms (TAS6424 PVDD)", slew < 75, "V/ms")
        note(b, f"inrush peak current / Q2 energy / ramp time ({lab})",
             f"{ipk:.2f} A / {e * 1e3:.0f} mJ / {tr * 1e3 if tr else float('nan'):.1f} ms")
        ax[0].plot(t * 1e3, vo, label=f"+12V_PROT {lab}")
        ax[1].plot(t * 1e3, i, label=f"Q2 current {lab}")
    # BUK7Y4R8-60E: Zth(j-mb) at 10 ms single pulse ~0.3 K/W (Nexperia fig.), peak power ~12 V x Ipk
    dT = 12.6 * worst_ipk * 0.3
    check(b, "Q2 junction rise during inrush (12.6 V x Ipk x Zth 0.3 K/W)", dT, "< 20 K", dT < 20, "K")
    ax[0].set(title="Soft start: +12V_PROT", xlabel="ms", ylabel="V")
    ax[1].set(title="Soft start: Q2 current", xlabel="ms", ylabel="A")
    ax[0].legend(fontsize=7)
    ax[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "input_protection.png"), dpi=110)
    plt.close(fig)


# ---------------------------------------------------------------- buck ---
# gen_sch.py:220-231, 278-283. EN 100k / 26.7k; LM61460 VEN 1.263 V +/-5 %,
# hysteresis 24..32 % of VEN (SNVSB70F 8.5). FB 100k / 24.9k to 1.0 V +/-1 %.
def block_buck():
    b = "buck"
    print(f"\n== {b}")
    rt, rb = 100e3, 26.7e3
    ven = 1.263
    r = lambda a, c: (a + c) / c
    on_lo = ven * 0.95 * r(rt * 0.99, rb * 1.01)
    on_hi = ven * 1.05 * r(rt * 1.01, rb * 0.99)
    off_lo = ven * 0.95 * (1 - 0.32) * r(rt * 0.99, rb * 1.01)
    off_hi = ven * 1.05 * (1 - 0.24) * r(rt * 1.01, rb * 0.99)
    note(b, "buck turn-on input voltage range", f"{on_lo:.2f} .. {on_hi:.2f} V")
    note(b, "buck turn-off input voltage range", f"{off_lo:.2f} .. {off_hi:.2f} V")
    check(b, "buck starts before a 12 V battery is flat", on_hi, "< 9 V", on_hi < 9, "V")
    vo_lo = 0.99 * (1 + rt * 0.99 / (24.9e3 * 1.01))
    vo_hi = 1.01 * (1 + rt * 1.01 / (24.9e3 * 0.99))
    check(b, "5 V rail setpoint, all tolerances", f"{vo_lo:.3f} .. {vo_hi:.3f}",
          "4.85 .. 5.25 V (Pi input spec +/-5 %)", vo_lo > 4.85 and vo_hi < 5.25, "V")
    # Dropout: below ~VOUT + I*(Rds_hs + DCR + trace) the rail follows VIN.
    # LM61460 high side 41 mOhm typ, 4.7 uH DCR 26.5 mOhm, min off-time 60 ns
    # at 400 kHz caps the duty at ~97.6 %.
    iload = 3.0
    vin_need = (4.75 + iload * (0.041 + 0.0265)) / 0.976
    note(b, f"input needed to hold 4.75 V at the buck at {iload:.0f} A (dropout)", vin_need, "V")
    note(b, "cranking: Pi (4.63 V under-voltage flag) holds while +12V_PROT stays above", vin_need, "V")


# --------------------------------------------------------- speaker filter ---
# gen_sch.py:574-599: per leg 3.3 uH (MHCI06030-3R3M: DCR 35 mOhm, Isat 12 A)
# + 1 uF (CL21B105KBFNNNE 50 V X7R 0805) + 1 nF C0G to GND. BTL, 2.1 MHz.
def filt_deck(load, cfac):
    return f"""* BTL output filter
VP p 0 AC 0.5
VM m 0 AC -0.5
LP p xp 3.3u
RLP xp op 35m
LM m xm 3.3u
RLM xm om 35m
CP op 0 {1e-6 * cfac}
CM om 0 {1e-6 * cfac}
CP2 op 0 1n
CM2 om 0 1n
{load}
.ac dec 200 100 10Meg
.control
run
.endc
.end
"""


def block_output_filter():
    b = "output_filter"
    print(f"\n== {b}")
    loads = {
        "4 ohm": "RL op om 4",
        "8 ohm": "RL op om 8",
        "open": "RL op om 1Meg",
        "speaker (Re 3.4 R, Le 0.25 mH)": "RL op sp 3.4\nLL sp om 0.25m",
    }
    fig, ax = plt.subplots(figsize=(8, 5))
    for cfac, clab in ((1.0, "1 uF nominal"), (0.6, "1 uF at 7 V bias (~-40 %)")):
        for lab, ld in loads.items():
            p = last_plot(run(f"filt_{lab.split()[0]}_{cfac}", filt_deck(ld, cfac))[0], "ac")
            f = np.real(vec(p, "frequency"))
            h = np.abs(vec(p, "op") - vec(p, "om"))
            db = 20 * np.log10(h)
            d20 = float(np.interp(20e3, f, db))
            pk = float(db.max())
            fpk = float(f[np.argmax(db)])
            a21 = float(np.interp(2.1e6, f, db))
            if lab in ("4 ohm", "8 ohm"):
                check(b, f"{lab}, {clab}: response at 20 kHz", d20, "within +/-1 dB", abs(d20) < 1.0, "dB")
            note(b, f"{lab}, {clab}: peak {pk:+.1f} dB at {fpk / 1e3:.0f} kHz; 2.1 MHz {a21:.0f} dB", "")
            if cfac == 1.0:
                ax.semilogx(f, db, label=lab)
    ax.set(title="Speaker filter (BTL), 1 uF nominal", xlabel="Hz", ylabel="dB", ylim=(-80, 30))
    ax.grid(True, which="both", lw=0.3)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "output_filter.png"), dpi=110)
    plt.close(fig)
    # Inductor current: 25 W into 4 R peak 3.54 A plus PWM ripple per leg.
    # Worst ripple at 50 % duty: PVDD x 0.25 / (L f), with L -20 % tolerance.
    for pvdd in (14.4, 18.0):
        rip = pvdd * 0.25 / (3.3e-6 * 0.8 * 2.1e6)
        ipk = np.sqrt(2 * 25 / 4) * (pvdd / 14.4) + rip / 2
        check(b, f"inductor peak current at PVDD {pvdd} V (full power + ripple/2)", float(ipk),
              "< 12 A Isat (and L stays > 1 uH per TAS6424 10.2.1.2.4)", ipk < 12, "A")


# ----------------------------------------------------------- SWC + ADC ---
# gen_sch.py:604-681. Ladder in: 1k pull-up to +3V3, H15VND3B ESD, 10k +
# 100 nF into the ADS1115 (clamps to VDD, 10 mA abs). Software (swc.py):
# 250 SPS, MIN_SEP_V 0.12, MATCH_V 0.06, IDLE_V 3.0, 3 stable samples.
def swc_deck(src, analysis):
    return f"""* SWC input
{MODELS}
V33 v33 0 3.3
{src}
RL win 0 {{RLAD}}
RPU v33 w 1k
RW w win 0.5
DE 0 w DESD
RS w adc 10k
CF adc 0 100n
* ADS1115 input: ESD diodes to VDD/GND, 6 MOhm common-mode input impedance
DH adc v33 DCLAMP
DL 0 adc DCLAMP
RIN adc 0 6Meg
{analysis}
.control
run
.endc
.end
"""


def block_swc():
    b = "swc_adc"
    print(f"\n== {b}")
    # Measured on the truck: seek+ ~0, vol+ 100, seek- 331 R. Wheel ground
    # offset up to 0.1 V worst via the ladder ground wire.
    rows = []
    for r in (0.01, 100, 331, 1000, 3111, 1e7):
        vals = []
        for pu in (0.99, 1.01):
            vals.append(3.3 * r / (r + 1e3 * pu) * (6e6 / (6e6 + 10e3)))
        rows.append((r, min(vals), max(vals)))
        note(b, f"ladder {r:g} R -> ADC", f"{min(vals):.3f} .. {max(vals):.3f} V")
    gaps = [rows[i + 1][1] - rows[i][2] for i in range(len(rows) - 2)]
    check(b, "smallest gap between the measured buttons (0 / 100 / 331 R)", min(gaps[:2]),
          "> 0.12 V (swc.py MIN_SEP_V)", min(gaps[:2]) > 0.12, "V")
    # settle time for a press: released (open) -> 331 R
    src = "S1 win 0 ctl 0 SWM\n.model SWM SW(Ron=331 Roff=1e9 Vt=0.5)\nVCT ctl 0 PULSE(0 1 1m 1u 1u 1 2)"
    deck = swc_deck(src, ".param RLAD=1e9\n.tran 10u 30m")
    p = last_plot(run("swc_settle", deck)[0], "tran")
    t, va = vec(p, "time"), vec(p, "adc")
    vfinal = float(va[-1])
    ts = cross(t, np.abs(va - vfinal), 0.03, after=1.001e-3)
    check(b, "settle to within 30 mV after a press", (ts - 1e-3) * 1e3 if ts else 99,
          "< 12 ms (3 samples at 250 SPS = 24 ms before a press counts)", ts and ts - 1e-3 < 12e-3, "ms")
    # fault: SWC wire shorted to 14.4 V
    deck = swc_deck("VF win 0 14.4", ".param RLAD=1e12\n.op")
    p = last_plot(run("swc_short", deck)[0], "op")
    vw = float(vec(p, "w")[0])
    ipu = (vw - 3.3) / 1e3
    # Wiring-fault case only. Accepted 2026-09-29 (1206 pull-ups declined):
    # over the 0603's 100 mW rating, and more than +3V3's ~10-15 mA standby load.
    note(b, "SWC shorted to 14.4 V (fault, accepted): 1k pull-up dissipation", ipu ** 2 * 1e3 * 1e3, "mW")
    note(b, "SWC shorted to 14.4 V (fault, accepted): current pushed back into +3V3", ipu * 1e3, "mA")
    # battery monitor, gen_sch.py input_protection(): VBAT/11.8 through the 10..46 R switch
    for vb in (6, 12, 14.4, 16, 35, 53):
        v = vb * (R_OV_MID + R_OV_BOT) / (R_OV_TOP + R_OV_MID + R_OV_BOT + 46)
        note(b, f"BATT_MON at {vb} V", v, "V")
    vmax = 3.3 / ((R_OV_MID + R_OV_BOT) / (R_OV_TOP + R_OV_MID + R_OV_BOT))
    check(b, "battery voltage at which AIN2 reaches VDD (3.3 V)", vmax, "> 36 V (above the OV cutoff)", vmax > 36, "V")


# ------------------------------------------------------------------ mic ---
# gen_sch.py:874-924. +3V3 -> 1k -> 10 uF -> 2.2k -> MIC_T; 1 nF + ESD at the
# jack; 1 uF into PCM1808 VINL (60 kOhm to VREF = VCC/2 = 2.5 V, datasheet 7.5).
def block_mic():
    b = "mic"
    print(f"\n== {b}")
    fig, ax = plt.subplots(figsize=(7, 4))
    for idss in (0.2e-3, 0.35e-3, 0.5e-3):
        vto = -0.4
        beta = idss / vto ** 2
        deck = f"""* electret mic bias (Idss {idss * 1e3:.2f} mA)
{MODELS}
.model JMIC NJF(Vto={vto} Beta={beta} Lambda=0.02)
V33 v33 0 3.3
RF v33 f 1k
CF f 0 10u
RB f t 2.2k
J1 t g 0 JMIC
VG g 0 0 AC 0.01
DE 0 t DESD
C1N t 0 1n
CC t in 1u
RIN in vref 60k
VREF vref 0 2.5
.op
.ac dec 50 1 1Meg
.control
run
.endc
.end
"""
        plots, _ = run(f"mic_{int(idss * 1e6)}", deck)
        op = last_plot(plots, "op")
        vt = float(vec(op, "t")[0])
        ok = 0.9 < vt < 2.8
        check(b, f"mic bias at Idss {idss * 1e3:.2f} mA", vt,
              "0.9 .. 2.8 V (electret JFET stays saturated)", ok, "V")
        ac = last_plot(plots, "ac")
        f = np.real(vec(ac, "frequency"))
        h = 20 * np.log10(np.abs(vec(ac, "in")))
        ref = float(np.interp(1e3, f, h))
        d100, d8k = float(np.interp(100, f, h)) - ref, float(np.interp(8e3, f, h)) - ref
        check(b, f"mic response 100 Hz / 8 kHz vs 1 kHz (Idss {idss * 1e3:.2f} mA)",
              f"{d100:+.2f} / {d8k:+.2f}", "within +/-1 dB", abs(d100) < 1 and abs(d8k) < 1, "dB")
        ax.semilogx(f, h - ref, label=f"Idss {idss * 1e3:.2f} mA")
    ax.set(title="Mic path, relative to 1 kHz", xlabel="Hz", ylabel="dB", ylim=(-30, 5))
    ax.legend(fontsize=7)
    ax.grid(True, which="both", lw=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "mic.png"), dpi=110)
    plt.close(fig)


# ----------------------------------------------------------------- fans ---
# gen_sch.py:953-989. Pi GPIO (3.3 V, ~40 R drive) -> 2N7002 gate with 100k
# pull-down; drain to the fan's PWM input (Intel spec: pulled up to <= 5.25 V,
# low < 0.8 V at up to 5 mA sink).
def block_fans():
    b = "fans"
    print(f"\n== {b}")
    for vto in (1.0, 2.5):
        deck = f"""* fan PWM, 2N7002 Vth {vto} V
.model N7002 VDMOS(Rg=3 Rd=0.5 Rs=0.5 Vto={vto} Kp=0.3 Cgdmax=15p Cgdmin=2p Cgs=25p Cjo=12p Is=1e-15)
VG gp 0 PULSE(0 3.3 0 5n 5n 20u 40u)
RG gp g 40
RPD g 0 100k
M1 d g 0 0 N7002
RUP v5 d 1k
V5 v5 0 5.25
CD d 0 100p
.tran 10n 200u
.control
run
.endc
.end
"""
        p = last_plot(run(f"fan_{vto}", deck)[0], "tran")
        t, vd = vec(p, "time"), vec(p, "d")
        m = (t > 120e-6) & (t < 160e-6)
        vlow = float(vd[(t > 125e-6) & (t < 140e-6)].max())
        check(b, f"fan PWM low level, 2N7002 Vth {vto} V, 5 mA sink", vlow, "< 0.8 V", vlow < 0.8, "V")
        del m


BLOCKS = {
    "power_hold": block_power_hold,
    "sense": block_sense,
    "input_protection": block_input_protection,
    "buck": block_buck,
    "output_filter": block_output_filter,
    "swc_adc": block_swc,
    "mic": block_mic,
    "fans": block_fans,
}


def main(names):
    os.makedirs(OUT, exist_ok=True)
    for n in names or BLOCKS:
        BLOCKS[n]()
    json.dump(RESULTS, open(os.path.join(OUT, "results.json"), "w"), indent=1, default=str)
    fails = [r for r in RESULTS if r["pass"] is False]
    print(f"\n{sum(r['pass'] is True for r in RESULTS)} pass, {len(fails)} fail, "
          f"{sum(r['pass'] is None for r in RESULTS)} info")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
