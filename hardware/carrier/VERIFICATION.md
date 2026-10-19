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

## Second pass (2026-09-29): everything else that could be checked

### New findings

| # | Finding | Severity | Suggested action |
|---|---|---|---|
| A | **I2S slot width (software).** The PCM1808 fixes BCLK at 64 fs. Nothing forces 32-bit slots on the Pi, so if PulseAudio opens the port as 16-bit (its default), bcm2835-i2s puts channel 2 at bit 17 of the frame: the right slot is empty and **FR and RR are silent**. | Would misbehave (software, fixable any time) | `launcher/board/system/carrier-audio-overlay.dts`: add `dai-tdm-slot-num = <2>; dai-tdm-slot-width = <32>;` to `simple-audio-card,cpu` (or run PulseAudio at s32le). Confirm on first power-up. |
| B | **TAS6424 land pattern** (KiCad `SSOP-56_7.5x18.5mm`): pads 1.2 x 0.4 mm on a 9.4 mm row pitch; TI's DKQ0056A example is 1.9 x 0.4 mm on 9.5 mm. The leads (span 10.03-10.67, foot 0.51-1.02) land on the pads with ~0.12 mm toe / 0.3 mm heel typically, but with little margin at tolerance extremes. | Low | Accept for rev A (JLC solders this routinely); use TI's pad length in a later revision. |
| C | **Mic input ESD:** the H15VND3B clamps at up to 38 V and nothing limits current between it and the 1 uF into PCM1808 VINL. | Low | Rev B: 1k in series before VINL (60k input, negligible loss). |
| D | **Back-powering:** the board feeds the Pi's 5 V through GPIO pins 2/4 with no ideal diode (the HAT guide recommends one). | Caution | Never plug USB-C power into the Pi while the carrier is powered. |
| E | **Silkscreen:** 104 reference labels are 0.8 mm / 0.12 mm stroke (JLC recommends >= 1 mm / 0.153 mm). A stray 0.06 mm dot sits on U5 pin 1 and is clipped by the pad; U5's real pin-1 dot is 0.25 mm. | Cosmetic | None; JLC places from the CPL. |
| F | **470 uF bulk (C36)** is rated 380 mA ripple at 120 Hz, 2000 h at 105 C. The harness supplies most of the amp's audio-frequency current, and the dash runs well under 105 C (~20,000 h at 70 C). | Note | Watch for heat at sustained high volume. |
| G | `launcher/board/system/config.txt` comment says the board cuts power "~2 s" after halt; it's 3-5 s. | Text | Update with the overlay fix. |
| H | **Via-in-pad (found by PCBWay's CAM review).** 7 vias had their hole inside an SMD pad (U3.16, C10.1, C11.1, R11.1, U5.1, U6.3, U6.5) and 5 more sat 0-0.11 mm from one (C16, C17, C26), all left by `maze.py`, which treated the net's own pads as free space. | Fixed | `maze.py` now keeps vias off own-net SMD pads; `tools/via_off_pad.py` (run by `build_board.sh`) moved all 12 beside their pads with short stubs (U5.1 now uses the +5V via already beside it). DRC unchanged: 0 errors, 0 unconnected, parity clean. Only copper and PTH drill Gerbers changed; BOM and CPL identical. |

### Checked, no issue

- **Fab files:** all 11 Gerber layers plus PTH/NPTH drill files present, metric. Smallest drill 0.3 mm, smallest copper feature 0.15 mm (JLC 4-layer minimum 0.09 mm). Heatsink screw holes plated (GND), Pi holes NPTH 2.7 mm. No bottom paste (no bottom SMD). Job file: 4 layers, 1.6 mm, 165.0 x 102.1 mm, 1 oz on all layers.
- **Zone fills are current:** refilling every zone gives byte-identical copper Gerbers.
- **Rendered layers (pygerber):** In2 split (+12V_PROT / +5V) intact, heatsink screw antipads in the +12 V plane, notch and ribbon slot clear of copper.
- **BOM, live:** all 53 LCSC numbers match their MPN, package and value, and all are in stock. The lowest stock is PCM1808-Q1 (162) and LM61460 (205). Caps: 100 V upstream of the cutoff, 50 V X7R on 12 V rails, C0G for 1 nF/22 pF; resistors 0603 1 % 100 mW, 75 V working (worst case 53 V on the 95.3k). LM61460AFS is the adjustable version.
- **Pi header J2:** pad 1 is 4.87 mm from the Pi hole at the non-USB end (HAT geometry), on the inner row; 5 V pins 2/4 on the outer row. Rotated, not mirrored.
- **Heatsink:** H5/H6 at +/-15.5 mm on the chip's long axis, as the heatsink's feet. Nothing within 4 mm of either foot (feet are 6.5 mm across). Parts under the base: 0603/0805 caps and three 1206 10 uF (1.8 mm max) against 2.24-2.42 mm clearance. Feet 2.20 mm against a 2.33 +/- 0.09 mm chip: the base always lands on the chip, and the screws pull the board up by 0.04-0.22 mm, so tighten gently.
- **Connector pegs:** Micro-Fit, fan header and jack peg holes are where JLC's parts have their pegs.
- **Pinouts** also checked for PCM1808 (all 14 pins) and the oscillator (1 tri-state, 2 GND, 3 out, 4 Vdd).
- **Buck values** match TI's 5 V / 400 kHz row exactly: 4.7 uH, 2 x 47 uF, 100k/24.9k, 22 pF + 1k feed-forward, 100 nF boot, 0 R RBOOT, 1 uF VCC, RT 33.2k.
- **TAS6424 power sequence:** VDD comes up after PVDD (3.3 V is derived from PVDD), as required; STANDBY has an internal pull-down, and `tas6424.stop()` holds it low for 20 ms before power goes.
- **Thermal:** amp idle 1.9 W typ / 2.7 W max, ~4-6 W with loud music; junction ~0.4 + 0.3 K/W to the heatsink. Still air (~15 K/W): ~140 C at 60 C ambient with loud music, past the 120 C warning. With a fan (~3-4 K/W): ~85 C. The software already runs fans at >= 25 %, goes to 100 % and -6 dB on the amp's warning. Buck ~1.5 W in the IC at 4 A, ~45 K rise. LDO 60 mW. Q1/Q2 < 0.1 W RMS.
- **I2C:** Pi 1.8k pull-ups, ~70 pF estimated: 110 ns rise (400 kHz limit 300 ns). ID bus 3.9k: ~100 ns.
- **Software vs board:** every GPIO in `carrierd.py` matches the netlist (ACC 17, lights 27, reverse 7, amp 22/23/24/25, ADC alert 6, tach 16/4, PWM GPIO12/13 on ALT0). `gpio-poweroff,active_low=1` drives PI_HOLD low only at halt. Amp registers: 0x6A, MISC5 bit 5 set before PLAY, SAP 0x44 = 48 kHz I2S, MISC2 0x62 = 2.11 MHz; channels come up Hi-Z. The 18 board software tests pass.
- **Tool scripts:** all compile / parse.

## Third pass (2026-10-07): before ordering

Board state: commit f40dfcb. Everything above was re-run or re-derived
independently against the current files.

### Re-checked, no issue

- ERC 0; DRC 0 errors, 0 unconnected, parity 0 (10 silkscreen warnings).
- `fab/carrier_gerbers.zip` is byte-identical (timestamps aside) to a fresh
  export; refilling every zone changes no copper Gerber.
- BOM re-exported from the schematic matches `fab/carrier_bom.csv`. Board,
  both BOMs, `fab/carrier_cpl.csv` and `fab/pcbway/carrier_pos.csv` all cover
  the same 162 parts; the PCBWay file matches the board's positions exactly.
  `check_cpl.py`: 0 fail; review in JLC's preview: Q1, Q2, and L1 (JLC has no
  footprint for it).
- Live stock: ICs, connectors and specialty parts all in stock; lowest
  LM61460 157, PCM1808 162.
- Pinouts re-read from the datasheets: TAS6424E (PVDD/VBAT, all 11 GND pins,
  address pins to GND = 0xD4/0x6A, 1 uF X7R >= 16 V boot caps as the bootstrap section asks), LM74800 (A/VSNS
  on the battery, VS and C on the common drain, RTN floating), LM61460 (BIAS
  on 5 V, RBOOT = CBOOT; AFS = FPWM variant), PCM1808 (pin 10 MD0 = 1, pin 11
  MD1 = 1, pin 12 FMT = 0: master 256 fs, I2S), DS3231, ADS1115, CAT24C32,
  TLV75533, oscillator, SOT-23 parts, fan headers. Pi header: all 40 pins
  against the standard pinout.
- Capacitor voltage vs the net each sits on: 25 V parts only on nets of 15 V
  or less.
- Nothing with pin tails or screws over the Pi except J2; H5/H6 are outside
  its outline. Fan headers and the mic jack sit inside the edge.

### New findings

| # | Finding | Action |
|---|---|---|
| I | **Copper under the Pi standoffs.** Within the 2.25-2.9 mm radius an M2.5 head, nut or standoff covers: H1 has I2S_FSYNC (F.Cu, 1.68 mm), ~AMP_MUTE (B.Cu, 1.80 mm), I2C_SDA (B.Cu, 2.28 mm); H4 has +3V3 (F.Cu, 1.80 mm). The Pi's holes are grounded, so worn mask under brass hardware would short them. H2/H3 have only GND nearby. | Rev A: nylon washers on both faces at H1 and H4. Rev B: copper 3 mm clear of the Pi hole centres. |
| J | **Board support.** Only the four Pi standoffs and J2 hold the board; J1 is 28 mm outside them. Harness insertion force flexes the board near ceramic capacitors. | Support under J1 in the enclosure (or a mounting hole near J1 in rev B). |
| K | **CNC heatsink dropped** on cost; rev A uses a stock 20 x 20 x 10 mm heatsink with thermal tape on U7. It sits flat (parts under it max 1.8 mm, chip 2.33 mm). Estimated with tape and still air: ~30 K/W, so loud music reaches the 160 C shutdown; with a fan across it, ~100-120 C worst case, inside the software's warning/-6 dB handling. The tape insulates it from GND, which the datasheet requires. | Fan airflow across it; thermal epoxy or a strap through H5/H6 to retain it; ground it (wire or strap to H5/H6). See README "Amp heatsink". |

The heatsink and thermal entries in the second pass above describe the CNC
heatsink and no longer apply to rev A.

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
