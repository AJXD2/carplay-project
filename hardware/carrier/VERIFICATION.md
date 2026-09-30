# Carrier board: pre-order verification (2026-09-29)

Board state checked: `carrier.kicad_pcb` / `fab/` as of commit 9e2e4d0.
ERC 0, DRC 0 errors (10 silkscreen warnings), unconnected 0, schematic
parity 0.

## Verdict

The circuit holds up. Nothing in the schematic would stop the board from
working, and every IC pinout and critical strap checks out against its
datasheet. **The real risk is the placement file.** 17 parts in
`fab/carrier_cpl.csv` have KiCad rotations that don't match JLC's own
footprints. Among them are the CR2032 holder (battery in backwards), the
harness connector (latch on the wrong side), the transistors and four ICs.
Fix that before ordering. The other findings are small.

## Fixes applied (2026-09-29)

| Finding | Status |
|---|---|
| 1. Placement file rotations and centres | Fixed in `tools/jlc_cpl.py` (`JLC_ROT`, `JLC_ORIGIN`) and `tools/jlc_export.sh`; `fab/carrier_cpl.csv` regenerated. `tools/check_cpl.py`: 0 mismatches (the old file fails 18). Also fixed: BT1's centre was the 3D model's origin, 3.8 mm from JLC's footprint origin. Q1/Q2 stay on the preview checklist. |
| 2. Fast key-to-START | Fixed: R15 47k -> 10k. Worst-case ride-through 4.6 s. |
| 3. OV cutoff tolerance | Fixed: R4 3.65k -> 3.74k (C2933210). Cutoff 32.6 to 36.0 V. |
| 4. SWC short to 12-14 V | Accepted (wiring-fault case only; 1206 pull-ups declined). |
| 5. Inner copper | Order-time option, noted in README. |
| 6. Notes | Schematic notes and README updated to the simulated numbers. |

`tools/sim.py` after the fixes: 37 pass, 0 fail.

## Findings, most serious first

### 1. Placement file rotations (would wreck the assembled board)

JLC places each part using its own (EasyEDA) footprint, rotated by the CPL
angle. `tools/check_cpl.py` fetched that footprint for every BOM line and
fitted it onto ours by pad number:

| Parts | Add to KiCad rotation | What goes wrong otherwise |
|---|---|---|
| BT1 (CR2032 holder) | 180 | Both holes are 1.5 mm, so it fits either way. + lands on GND and the DS3231 VBAT sees -3 V (abs max -0.3 V) |
| J1 (Micro-Fit 2x10) | 180 | Latch on the other row: the harness plug mates rotated, e.g. +12 V on REV_IN and speakers on the SWC pins |
| M1, M2 (fan headers) | 180 | Ramp reversed: fan GND on PWM, no fan power |
| Q3-Q7 (SOT-23) | 180 | B/E/C and G/S/D land on the wrong pads |
| U6 (TLV75533, SOT-23-5) | 180 | No 3.3 V |
| U2 (ADS1115), U3 (DS3231), U4 (EEPROM), U7 (TAS6424) | 270 | Pin 1 in the wrong corner |
| Q1, Q2 (LFPAK56) | 180 | Gate/source on the tab pad |

Checked and correct as they are: U1, U5, U8, X1, all diodes and LEDs (JLC's
LED footprint calls pad 1 the anode, the opposite of KiCad, so the
by-number 180 is really 0), C36 (JLC's pad 1 carries the "+" mark), and
every R/C/L.

Also:
- **J4 (mic jack)**: JLC's PJ-320D origin is 0.925 mm from ours along the
  jack axis. Unshifted, its pegs miss our 1.5 mm holes. `tools/jlc_cpl.py` now
  moves it.
- **Q1/Q2**: JLC's LFPAK56 footprint puts the pin pads 0.5 to 0.8 mm further
  inward than KiCad's. Check in the preview that the body sits centred on our
  pads.
- **J2 (Pi socket, bottom)** is symmetric; JLC will align it to the holes.

**Fix (applied):** the corrections live in `tools/jlc_cpl.py`, so every
`tools/jlc_export.sh` run writes a correct `fab/carrier_cpl.csv`. Still check
each part in the table in JLC's placement preview: pin-1 dot against the
silkscreen, BT1 "+", J1 latch side, fan ramp.

### 2. Fast key-to-START drops power during the crank (misbehaves, harmless)

If the key goes straight through ACC to START, ACC is high for only a
fraction of a second before Toyota cuts it for the crank. SYS_EN charges
through the 47k too slowly to fill the 47 uF, so the board switches on
(after 0.24 s), then cuts out 0.5 to 1.7 s into the crank. The Pi reboots
once the engine is running. That's harmless with the read-only root, but it
isn't what the design intends.

| R15 (ACC -> SYS_EN) | Ride-through after 0.3 s of ACC (short / nominal / long corner) |
|---|---|
| 47k (now) | 1.7 / 1.3 / 0.5 s |
| 22k | 3.6 / 4.1 / 4.4 s |
| **10k** | **4.6 / 6.2 / 7.8 s** |

**Fix:** R15 47k -> 10k (C25804, already on the BOM). SYS_EN then sits at
12.6 V at 14.4 V ACC (under the 15 V zener). A 40 V dump puts 2.5 mA
into the zener. The discharge side (100k) is unchanged.

### 3. OV cutoff tolerance (spec edge, not damaging)

The cutoff is 35.1 V nominal, 33.4 to 36.8 V with 1% resistors and the
LM74800's threshold spread. The top end is 0.8 V over the LM61460's 36 V
operating maximum (its abs max is 42 V) and inside the TAS6424's 40 V /
400 ms load-dump rating. **Optional:** R4 (OV divider bottom, 3.65k) ->
3.74k gives 32.6 to 36.0 V.

### 4. SWC wire shorted to 12-14 V (fault case only)

Pin 8 (SWC1) sits next to pin 7 (ACC) in the harness plug. If they are swapped
or shorted, the 1k 0603 pull-up dissipates 123 mW (rated 100 mW) and pushes
12 mA back into +3V3. +3V3 only draws ~10-15 mA with the amp in standby, so
the rail could rise. **Optional:** the two 1k pull-ups (R5, R7) in 1206. Raising the
value instead would squeeze the 0 / 100 Ω button gap towards swc.py's
0.12 V limit.

### 5. Inner copper weight

The +12V_PROT plane (Q2 -> amp and buck, up to ~12 A peak at full volume) and
the +5V plane (buck -> Pi, ~4 A) are on In2. JLC's 4-layer default is
**0.5 oz inner**. Via counts are fine: 6 x 0.4 mm from Q2 into the plane,
16 at the amp, ~5 at the buck output. **Recommend** selecting 1 oz inner
copper at order time; it's a small surcharge.

### 6. Schematic notes that don't match the values (text only)

| Note | Simulated |
|---|---|
| Key off: SYS_EN under 1.13 V "~2 s" after the Pi halts | 2.8 to 5.1 s to load cut; 7 to 12 s to the 3 uA shutdown (needs V(ENF) 0.3-0.93 V) |
| ACC alone holds SYS_EN "~5 s" | 4.5 to 9.6 s from steady state (47 uF loses ~half at 8 V DC bias) |
| Mic bias "~1.2 V at 0.5 mA" | 1.65 V at 0.5 mA, 2.6 V at 0.2 mA |

## What passed

SPICE (`tools/sim.py`, KiCad's bundled ngspice; decks in `out/sim/*.cir`):

- **Power hold:** Pi alone holds SYS_EN at 2.85 V (> 1.267 V max). A 35 V or
  53 V dump on ACC clamps SYS_EN at 14.9 V. Normal crank after ACC has been
  on: 4.5 to 9.6 s ride-through.
- **Key/lights/reverse sense:** threshold 3.6 V; 0.05 V GPIO at 9 V in;
  0.77 mA base current at 40 V. A PWM-dimmed lights feed would toggle the
  GPIO. The 4Runner's ILL+ is steady, but software must treat any
  activity as "on" if that ever changes.
- **Soft start:** 1.8 to 3.4 V/ms slew (TAS6424 limit 75 V/ms), 2.4 to 3.2 A
  peak, ~50 mJ in Q2, well inside its SOA.
- **Buck:** starts at 5.6 to 6.4 V, stops at 3.8 to 4.9 V. 5 V setpoint
  4.89 to 5.15 V over all tolerances. The Pi stays above its 4.63 V warning
  while +12V_PROT > 5.1 V.
- **Speaker filter:** flat to 20 kHz (+0.1 dB at 4 Ω, +0.3 dB at 8 Ω),
  -55 dB at 2.1 MHz. Unloaded, it peaks +33 dB near 90 kHz, as TI's reference
  does; that's inaudible. Inductor peak 3.9 A at full power vs 12 A Isat.
- **SWC/ADC:** buttons 0 / 100 / 331 Ω read 0 / 0.30 / 0.82 V (gap 0.30 V
  vs 0.12 V needed); settles in 4.5 ms. AIN2 stays under VDD up to 39 V.
- **Mic:** flat 100 Hz to 8 kHz within 0.11 dB.
- **Fans:** PWM low 0.03 V even with a worst-case 2N7002.

Audit against datasheets:

- Pin-by-pin: TAS6424E-Q1 (incl. AREF/AVSS as local returns, as in TI fig
  10-2), LM74800-Q1, LM61460-Q1 (CBOOT/RBOOT), DS3231, PCM1808-Q1,
  12.288 MHz oscillator, SOT-23 parts.
- I2C addresses: 0x6A = 0xD4 >> 1, 0x48, 0x68, 0x50.
- PCM1808 MD1 = MD0 = 1 is master at 256 fs; 12.288 MHz gives 48 kHz.
- Land patterns: LM61460 RJR0014A matches TI to within ~0.03 mm. LM74800
  WSON: KiCad's pads are slightly larger than TI's DRR, and the RTN pad is
  on its own net, as required.
- Voltage ratings on every rail are fine. The one near-limit part is the
  22 nF HGATE cap (50 V), which sees up to ~50 V only if the rail sits right
  at the OV cutoff.

## Not covered

- Behaviour of the ICs themselves (no usable vendor models).
- EMI, and amp thermals under real music.
- Buck loop stability: internally compensated, and the values come from TI's
  table.

The first power-up plan in README "Open items" still applies.

## Files

- `tools/sim.py`, `tools/ngspice_run.py`: SPICE testbenches
  (`.venv/bin/python tools/sim.py`)
- `tools/check_cpl.py`: CPL vs JLC footprints
  (`flatpak run --command=python3 org.kicad.KiCad tools/check_cpl.py --dump`
  then `.venv/bin/python tools/check_cpl.py`)
- `out/sim/*.png`: plots, `out/sim/results.json`: every check (generated by `tools/sim.py`, not committed).
