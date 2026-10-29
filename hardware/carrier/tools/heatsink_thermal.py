#!/usr/bin/env python3
"""Rough thermal comparison of the amp heatsink options (assembly.HEATSINK).

A resistance chain, junction to air:

  junction -> top pad    TAS6424 theta_JC(top), 0.4 K/W
  interface              tape ~2.5 K/W (0.25 mm at ~0.7 W/m.K over ~140 mm2
                         of chip top), clamped paste ~0.3 K/W
  base                   through the base, plus spreading from the chip out to
                         the whole base (Lee, Song, Au & Moran 1995)
  base + fins -> air     h on the bare base and the fins (fin efficiency for
                         each fin), plus radiation off the outer envelope

The air side is the big unknown. h comes from fan 1's air washing down the
fins (laminar flat plate), with the fan's flow scaled by its duty and cut to
FAN_LOAD of free air by the grille, heatsink and vents. FAN_LOAD is a guess,
and the fan's hub sits over the chip, so read the table as a ranking of the
options and of fan speeds, not as the temperatures the amp will reach. Only
a bench test gives those (README "Amp heatsink").

Two stock heatsinks end to end over the chip's centre count as one 40 x 20
piece: the seam is a plane of symmetry, so no heat would cross it anyway.

    .venv/bin/python tools/heatsink_thermal.py
"""
import math

import heatsink as cnc

K_AL = 167.0                 # W/m.K, 6061-T6 (extruded 6063 is ~200)
SIGMA = 5.67e-8
THETA_JC = 0.4
R_TAPE, R_PASTE = 2.5, 0.3
CHIP = (18.5, 7.5)           # heat source on the base, mm
AMBIENT = 60.0               # hot dash
WARN, SHUTDOWN = 120.0, 160.0
H_STILL = 7.0                # W/m2.K, fan stopped, closed box

# fan 1: Noctua NF-A4x10 5V PWM, 8.9 m3/h free air at 5000 rpm, 1050 rpm at 20 %
FAN_FLOW = 8.9 / 3600                               # m3/s
FAN_OPEN = 0.04 ** 2 - math.pi * 0.0085 ** 2        # 40 mm frame less a ~17 mm hub
FAN_LOAD = 0.6               # share of free-air flow left after grille, heatsink, vents (guess)
FAN_DUTY = (0.25, 0.5, 1.0)  # 25 % is the launcher's floor (launcher/board/fans.py)
NU_AIR, K_AIR, PR = 2.0e-5, 0.029, 0.7              # air at ~70 C
POWER = 6.0                  # W, loud music worst case (VERIFICATION.md)

# name, length (along the fins), width, base, fin thickness, fins, fin height,
# cross-cuts through the fins, emissivity, interface. The stock one is read
# off the seller's photo (black anodised, 8 fins ~1 mm on a ~2 mm base,
# cross-cut into 4): measure yours with calipers and correct it here.
STOCK = (2.0, 1.0, 8, 8.0)
CUT_W = 1.5                  # cross-cut slot width
OPTIONS = [
    ("stock 20x20, tape", 20.0, 20.0, *STOCK, 3, 0.85, R_TAPE),
    ("stock 20x20, paste", 20.0, 20.0, *STOCK, 3, 0.85, R_PASTE),
    ("two 20x20, paste", 40.0, 20.0, *STOCK, 6, 0.85, R_PASTE),
    ("CNC 39x20, paste", cnc.L, cnc.W, cnc.BASE, cnc.FIN_T, cnc.FINS, cnc.FIN_H, 0, 0.10, R_PASTE),
]


def air_side(L, W, base, t, n, fh, cuts, eps, h, t_sink):
    """Conductance (W/K) from the base and fins to the air."""
    L, W, base, t, fh = (v / 1000 for v in (L, W, base, t, fh))
    lf = L - cuts * CUT_W / 1000                 # fin length left after the cross-cuts
    lc = fh + t / 2                              # the tip convects too
    m = math.sqrt(2 * h / (K_AL * t))
    eta = math.tanh(m * lc) / (m * lc)
    fins = n * (2 * lc * lf + 2 * cuts * t * fh)  # faces + tips, and the cut ends
    bare = W * L - n * t * lf + 2 * base * (L + W)
    # radiation off the outer envelope only: the fins mostly see each other
    tk, ta = t_sink + 273.15, AMBIENT + 273.15
    h_rad = eps * SIGMA * (tk ** 2 + ta ** 2) * (tk + ta)
    envelope = L * W + 2 * (base + fh) * (L + W)
    return h * (bare + eta * fins) + h_rad * envelope


def base_r(L, W, base, g_air):
    """Through the base plus spreading out from the chip (K/W)."""
    a_s, a_p, t = CHIP[0] * CHIP[1] * 1e-6, L * W * 1e-6, base / 1000
    a, b = math.sqrt(a_s / math.pi), math.sqrt(a_p / math.pi)
    eps, tau = a / b, t / b
    bi = g_air / a_p * b / K_AL
    lam = math.pi + 1 / (math.sqrt(math.pi) * eps)
    phi = (math.tanh(lam * tau) + lam / bi) / (1 + lam / bi * math.tanh(lam * tau))
    psi = 0.5 * (1 - eps) ** 1.5 * phi
    return t / (K_AL * a_p) + psi / (K_AL * a * math.sqrt(math.pi))


def h_fan(opt, duty):
    """h (W/m2.K) from fan 1 at a duty: laminar flat plate over the run the air
    makes before its boundary layer restarts (the fin height, or a cross-cut
    segment if that is shorter)."""
    _, L, _, _, _, _, fh, cuts, *_ = opt
    rpm = 1050 + (5000 - 1050) * (duty - 0.2) / 0.8
    v = FAN_FLOW * rpm / 5000 * FAN_LOAD / FAN_OPEN
    run = min(fh, (L - cuts * CUT_W) / (cuts + 1)) / 1000
    nu = 0.664 * (v * run / NU_AIR) ** 0.5 * PR ** (1 / 3)
    return nu * K_AIR / run


def solve(opt, h, power):
    """Junction temperature and the chain's parts (K/W)."""
    _, L, W, base, t, n, fh, cuts, eps, r_int = opt
    t_sink = AMBIENT + 20
    for _ in range(30):                          # radiation depends on t_sink
        g = air_side(L, W, base, t, n, fh, cuts, eps, h, t_sink)
        t_sink = AMBIENT + power / g
    r_base = base_r(L, W, base, g)
    parts = {"chip": THETA_JC, "interface": r_int, "base": r_base, "air": 1 / g}
    return AMBIENT + power * sum(parts.values()), parts


def mark(tj):
    return f"{tj:5.0f}{'!!' if tj >= SHUTDOWN else '! ' if tj >= WARN else '  '}"


def main():
    print(f"Amp junction temperature at {POWER:g} W, {AMBIENT:g} C ambient "
          f"(! over the {WARN:g} C warning, !! over the {SHUTDOWN:g} C shutdown)\n")
    head = "  ".join(f"{d:>5.0%}  " for d in FAN_DUTY)
    print(f"{'fan 1 duty:':20}  {head}    off     h at {FAN_DUTY[-1]:.0%}")
    for opt in OPTIONS:
        cells = "  ".join(mark(solve(opt, h_fan(opt, d), POWER)[0]) for d in FAN_DUTY)
        off = mark(solve(opt, H_STILL, POWER)[0])
        print(f"{opt[0]:20}  {cells}  {off}   {h_fan(opt, FAN_DUTY[-1]):.0f} W/m2.K")
    print(f"\nFAN_LOAD {FAN_LOAD:.0%} of free-air flow is a guess: the ranking holds, "
          "the absolute numbers are +/-20 C.")


if __name__ == "__main__":
    main()
