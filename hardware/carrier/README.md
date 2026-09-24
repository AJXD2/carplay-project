# Carrier board (2007 4Runner head unit)

One board that turns the Pi 4 + 7" screen into a complete car radio
replacement. It bolts onto the Pi like a HAT, plugs into the truck's radio
harness, and does everything the factory radio did plus what the Pi needs:

- survives car power (reverse battery, load dump, cranking) and switches
  itself fully off with the key (a few µA left on the battery)
- powers the Pi, the screen and the fans (5 V, 6 A)
- drives the four stock speakers from the Pi's digital audio (no USB DAC,
  no ground-loop hum)
- reads the steering-wheel buttons (learn mode, any wheel)
- senses key, headlights (night mode) and reverse
- keeps the clock running with the power off
- runs two fans, and tells the Pi what it is at boot (HAT ID EEPROM)

Software for it lives in [`launcher/board/`](../../launcher/board/README.md).

## Status

| Stage | State |
|---|---|
| Schematic | Done. ERC 0 errors / 0 warnings. |
| Parts list (BOM) | Done. 148 fitted parts, every one with an LCSC number, stock checked at JLCPCB. |
| Placement | Done for the nominal Pi position. DRC: no overlaps or clearance errors. |
| Routing | Done. 0 unrouted, 0 DRC errors (silkscreen tidy pending), schematic parity 0. |
| Silkscreen tidy | Not started (cosmetic DRC items only). |
| Pi position on the screen | Measured on the real screen and confirmed with a printed fit test (see Mechanical). |
| Software | Written and tested on simulated hardware (18 tests), not installed. |
| Ordering | Not yet. |

## How it works, block by block

The schematic (`carrier.kicad_sch`, one A2 sheet, PDF in `out/carrier.pdf`)
is split into boxed sections. The same section names tag every part
(hidden `Section` field) so the board layout can find each block.

| Section | Parts | What it does |
|---|---|---|
| Harness | J1, Molex Micro-Fit 3.0 2x10 vertical | Truck wiring in; plug faces the firewall |
| Input protection | LM74800-Q1 + 2x BUK7Y4R8-60E + SMBJ33CA | Reverse-battery block, cuts off above 35.1 V (load dump), slow soft start (~2.5 V/ms). Its enable (SYS_EN) is the board's master switch |
| 5 V buck | LM61460-Q1, 4.7 µH | 5 V / 6 A at 400 kHz for Pi, screen (through GPIO pins 2/4 and the display's pogo pins), fans. Turns on at 6.0 V, off at 4.3 V, so it rides through cranking |
| 3.3 V | TLV75533 | Amp logic, ADC, RTC, EEPROM, clocks |
| Power hold + sensing | diodes, RC, 3x MMBT3904 | SYS_EN = key OR the Pi's hold line. Key/lights/reverse become active-low 3.3 V inputs |
| Amplifier | TAS6424E-Q1 | 4 x BTL, about 25 W/ch into 4 Ω at 14.4 V, 2.1 MHz switching, I2C controlled (0x6A) |
| Output filters | 8x 3.3 µH + 1 µF + 1 nF | Reconstruction filter per speaker leg (TI reference values) |
| Audio clocks | 12.288 MHz oscillator + PCM1808-Q1 | The board is the audio clock master (see decisions) |
| Mic input | 3.5 mm jack J4 (PJ-320D) into the PCM1808 | Electret car mic for calls and Siri: bias from 3.3 V, ESD and RF filtering at the jack, the PCM1808's ADC sends it to the Pi on GPIO20. Mic on the tip; ring and sleeve grounded |
| Status LEDs | 3 red 0603 (D8-D10), tagged 12V / 5V / PI | Which power stage is alive: protected 12 V, the 5 V rail, and the Pi holding the board on |
| Steering wheel + battery ADC | ADS1115 (0x48) | Two ladder inputs (1k pull-ups, ESD, RC filter), battery voltage on AIN2 |
| RTC + ID EEPROM | DS3231SN + CR2032 (0x68), CAT24C32 (0x50) | Clock through power-off; HAT ID per the Raspberry Pi HAT design guide |
| Pi | J2, 2x20 socket on the underside | Mates with the Pi's header |
| Fans | 2x 4-pin headers, 2N7002 each | PWM from the Pi, inverted by the FET; tach readback |
| Debug + mounting | UART header (not fitted), H1-H6 | Pi holes isolated per HAT spec; heatsink screws grounded |

## Design decisions and why

- **Class-D amp fed digitally (I2S).** The old setup went through a USB
  sound card; digital audio straight to the amp removes that and the
  ground-loop path. The TAS6424E-Q1 is automotive (AEC-Q100), survives
  40 V load dump, and was the only in-stock 4-channel part with digital
  input at JLCPCB.
- **The board is the audio clock master.** The Pi's PCM block carries only
  two channels, and the TAS6424 needs a real master clock (128-512 x the
  sample rate) outside TDM mode. So a 12.288 MHz oscillator drives the amp's
  MCLK directly and a PCM1808-Q1 in master mode (MD1 = MD0 = high, strapped,
  no software) divides it to the bit clock (64 fs) and frame clock
  (48 kHz). All three come from one crystal and cannot drift apart. The Pi
  runs its I2S port as a clock consumer. Consequences: audio is fixed at
  48 kHz (PulseAudio resamples), and the rear speakers play the same stereo
  as the front (SDIN1 and SDIN2 share the data); the fader and balance use
  the amp's per-channel volume. The CS2100 clock chip originally planned was
  dropped: JLC only stocks the -10 to 70 °C grade.
- **One master switch.** The LM74800's enable turns the whole board off.
  SYS_EN is the OR of the key (with a ~5 s RC grace period so a crank before
  the Pi boots does not cut power) and the Pi's own hold line (GPIO26). The
  Pi decides when to power off: key off for 8 s, then it shuts down cleanly,
  drops the hold line, and the board switches off about 2 s later. A hung Pi
  is reset by its watchdog, which also drops the hold line.
- **Steering wheel by learn mode.** Toyota wheels are resistor ladders on
  two wires. Instead of hard-coding resistor values, the software asks for
  each button once and remembers what it reads. It refuses two buttons it
  cannot tell apart.
- **Harness as one latching plug.** Every truck wire ends in one Micro-Fit
  plug (like a PC's ATX connector) that clicks into the board. 8.5 A per
  contact; 12 V and ground use several pins each.
- **Heatsink copied from TI's evaluation board.** The amp's thermal pad is
  on top of the chip. TI's EVM uses a custom 20 x 41.4 mm finned heatsink
  screwed down with M3 screws and Arctic Silver paste; ours is the same
  footprint with fins sized for CNC machining (`tools/heatsink.py`). Its
  feet sit on grounded pads, which grounds the heatsink as TI requires.
- **Part choices for car conditions.** Every IC is rated to at least 85 °C.
  Caps upstream of the 35 V cutoff are 100 V (the TVS can clamp to 53 V),
  the rest of the 12 V side is 50 V X7R. Speaker-filter 1 nF caps are C0G.
  Boot caps are 0603 (fit the amp's 0.635 mm pin pitch; datasheet asks for
  X7R ≥ 16 V, these are 50 V).
- **Fans fail safe.** The PWM FET's gate pull-down leaves the fans at full
  speed whenever the Pi is not driving them.

Full calculations (divider values, time constants, cut-off voltages) are
written as notes on the schematic next to each circuit.

## Mechanical

**Display:** Hosyond 7" DSI, **164.9 x 102.0 mm, 12.25 mm thick** per the
manufacturer's drawing (`datasheets/hosyond/`). The board uses the same
outline. Its own four mounting holes sit 5 mm in from each corner (154.89 x
91.92 mm apart): the enclosure screws into those, before the Pi and board go
on (the board sits ~18 mm above the screen's back, clear of the screw heads).

**Where the Pi sits on the screen.** First estimated from Hosyond's product
photo (the Pi's 58 x 49 mm hole pattern set the scale), then **measured on
the real screen** on 2026-09-24 with a printed fit plate and calipers, Pi
board edge to screen edge:

| Pi edge | To the screen edge |
|---|---|
| Ports side (USB/Ethernet) | 36.65 mm |
| Display ribbon side | 43.40 mm |
| GPIO side | 15.35 mm |
| USB-C / HDMI side | 31.45 mm |

The sums (165.05 x 102.80, all values rounded down) match the 165 x 103
screen. Left/right differed from the photo estimate by 1.35 mm, up/down by
under 0.2 mm. The plate's screw holes, header window and port notch all
lined up.

| Viewed from the back, from the display's top-left corner | mm |
|---|---|
| Upper Pi holes | x 60.15 and 118.15, y 35.1 |
| Lower Pi holes | x 60.15 and 118.15, y 84.1 |
| Pi outline | x 36.65 to 121.65, y 31.6 to 87.6 |
| Orientation | rotated 180°: GPIO header at the bottom, USB/Ethernet toward the right of the screen as seen from the front |

The manufacturer's drawing then confirmed the Pi holes at 60.36 / 118.36
mm from the screen's left edge and 35.19 / 84.19 mm from its top (within
0.2 mm of the measurements), and set the final outline.

How the correction is applied: the board is referenced to the Pi, so the
Pi, every part, the notch and the cable slot stay where they are and only
the outer outline moves (`OUTLINE_SHIFT` in `tools/place.py`). All copper was
routed at least 3 mm from the outer edges for exactly this; with the final
outline the edge margin is 2.5 mm.

**Board shape.** The Pi is mid-screen, so its USB/Ethernet block (13.5 mm
tall Ethernet jack, board sits 11 mm above the Pi) is ~30 mm in from the
display's edge. The board has a notch from the port block to the left edge
(back view): the jacks clear it and cables can reach them. A slot next to
the Pi's DSI connector clears the display ribbon (HAT spec position).

**Stack-up** (from the screen's glass, toward the firewall):

| Layer | z (mm) | Source |
|---|---|---|
| Display module | 0 to 6.0 | **assumed**, measure |
| Pi standoffs | 6.0 to 12.0 | **assumed**, measure |
| Pi 4 board | 12.0 to 13.6 | Pi spec |
| Header base + socket | 13.6 to 24.6 | 2.5 + 8.5 mm, HAT standard (11 mm M2.5 standoffs) |
| Carrier board | 24.6 to 26.2 | 1.6 mm |
| Tallest parts on it | to ~39 | 470 µF cap 12.5 mm, harness plug + mated housing |
| Heatsink fins | to 56.5 | 30.2 mm heatsink |

Overall **165 x 103 x 56.5 mm**. The heatsink sets the depth; shorter fins
(e.g. 15 mm) save ~13 mm at some cooling cost, which the fans make up.

**Fit test before ordering:** `tools/fit_plate.py` writes
`mech/fit_plate.stl`, a 1.6 mm plate with the board's exact outline, notch,
cable slot, Pi and heatsink holes and a window for the Pi header. Print it
text side up, mount it on the Pi with the 11 mm standoffs, and check the
edges against the screen and the holes against the standoffs.

**3D model:** `tools/assembly.py` builds display + Pi 4 + board + heatsink
(`mech/assembly.step`, `mech/assembly.stl`; generated, not committed).
Review images: `out/3d/*.png` via `tools/render3d.py`.

## Wiring the truck

The truck has three plugs behind the radio: two yellowish ones (power,
speakers; what the Metra harness mates with) and a white 20-pin one that
carries the steering-wheel wires. Build one Micro-Fit plug that gathers
them all:

- Power and speakers: the Metra harness wires, or the Klintotour adapter
  (which also has the white 20-pin plug). Either way the loose ends go into
  the Micro-Fit plug; nothing on the truck gets cut.
- Steering wheel: the Klintotour adapter's white-plug wires, cut from its
  16-pin end. Identify KEY1 and KEY2 with a meter (see below).
- Reverse: tap the truck's reverse-light wire (Posi-Tap) and run a wire to
  pin 10.

To build the plug: solder each wire to a pre-crimped Micro-Fit lead,
heat-shrink it, and push the pin into its numbered hole until it clicks.
Pin n sits directly above pin n+10. The speaker order (FR, FL, RR, RL) is
not a typo: it matches the amp's output order on the board, so the four
speaker tracks run straight to the plug without crossing.

| Pin | Signal | Typical wire colour |
|---|---|---|
| 1, 11 | +12 V constant | Yellow |
| 2, 12, 19 | Ground | Black |
| 7 | Key / accessory | Red |
| 17 | Headlights on (illumination) | Orange |
| 10 | Reverse (+12 V in reverse) | Pink "BACK" on the adapter, or your own wire |
| 8 | Steering wheel wire 1 (seek, volume) | KEY1 |
| 18 | Steering wheel wire 2 (mode) | KEY2 |
| 9 | Steering wheel ground | if separate; otherwise tie to ground |
| 3 / 13 | Front right + / − | Gray / gray-black |
| 4 / 14 | Front left + / − | White / white-black |
| 5 / 15 | Rear right + / − | Purple / purple-black |
| 6 / 16 | Rear left + / − | Green / green-black |
| 20 | Not used | |

Finding KEY1 / KEY2: adapter plugged into the truck, key off, meter on
ohms between each candidate wire and ground. The wire whose reading
changes with seek/volume is KEY1 (pin 8); the one that drops near 0 Ω on
Mode is KEY2 (pin 18). Earlier measurements on the purple SWC wire: seek+
~0 Ω, seek− 331 Ω, vol+ 100 Ω, vol− "3.111" (unit unclear). Learn mode
makes the exact values irrelevant.

Blue wires (power antenna, amp turn-on) are not used.

## Pi GPIO map

| Header pin | BCM | Net | Use |
|---|---|---|---|
| 2, 4 | 5V | +5V | Board powers the Pi (and the screen through its pogo pins) |
| 1, 17 | 3V3 | (unused) | The board makes its own 3.3 V |
| 3, 5 | GPIO2/3 | I2C_SDA/SCL | Amp 0x6A, ADC 0x48, RTC 0x68 (Pi has 1.8k pull-ups) |
| 27, 28 | ID_SD/SC | ID_SDA/SCL | HAT EEPROM 0x50 (3.9k pull-ups on the board) |
| 12 | GPIO18 | I2S_BCLK | Bit clock, **input** (board is master) |
| 35 | GPIO19 | I2S_FSYNC | Frame clock, **input** |
| 40 | GPIO21 | I2S_DOUT | Audio data to the amp |
| 32, 33 | GPIO12/13 | FAN1/2_PWM | Hardware PWM, 25 kHz, inverted |
| 36, 7 | GPIO16/4 | FAN1/2_TACH | Tach, 2 pulses/rev |
| 11 | GPIO17 | ~ACC_ON | Key on (active low) |
| 13 | GPIO27 | ~LIGHTS_ON | Headlights (active low, may be PWM-dimmed) |
| 38 | GPIO20 | I2S_DIN | Mic audio from the PCM1808, **input** |
| 26 | GPIO7 | ~REVERSE | Reverse gear (active low) |
| 37 | GPIO26 | PI_HOLD | Keeps the board powered while high |
| 15, 16 | GPIO22/23 | ~AMP_STBY/~AMP_MUTE | Amp control |
| 18, 22 | GPIO24/25 | ~AMP_FAULT/~AMP_WARN | Amp status (open drain) |
| 31 | GPIO6 | ~ADC_ALERT | ADC ready (unused by software for now) |
| 29 | GPIO5 | ~RTC_INT | RTC alarm |
| 8, 10 | GPIO14/15 | UART_TX/RX | Debug header (not fitted) |

## Shopping list (besides the board)

From DigiKey (genuine Molex; Amazon does not carry the 20-way housing):

| Qty | Part | Link |
|---|---|---|
| 2 | Micro-Fit 3.0 2x10 plug housing, Molex 43025-2000 | [DigiKey](https://www.digikey.com/en/products/detail/molex/0430252000/531408) |
| 25 | Micro-Fit pre-crimped lead, socket + 300 mm 18 AWG, Molex 2147611124 | [DigiKey](https://www.digikey.com/en/products/detail/molex/2147611124/12353036) |
| opt. | Micro-Fit extraction tool, Molex 11-03-0043 (the Amazon "11-03-0044" tools are Mini-Fit Jr, wrong size) | [DigiKey](https://www.digikey.com/en/products/detail/molex/0011030043/252489) |

From Amazon:

| Qty | Part | Link |
|---|---|---|
| 1 | Klintotour Toyota adapter (for the white steering-wheel plug) | [B0FBRNCNPD](https://www.amazon.com/dp/B0FBRNCNPD) |
| 1 | CR2032 | [B07G7KRQQ5](https://www.amazon.com/dp/B07G7KRQQ5) |
| 1 | M2.5 standoffs, 11 mm body + 6 mm thread | [B07KM27KC6](https://www.amazon.com/dp/B07KM27KC6) |
| 2 | Noctua NF-A4x10 5V PWM (each includes an extension cable) | [B07DXS86G7](https://www.amazon.com/dp/B07DXS86G7) |
| 1 | Posi-Tap 18-24 AWG | [B01HSBYX3I](https://www.amazon.com/dp/B01HSBYX3I) |
| 1 | 18 AWG wire (reverse run) | [B07D74RGVM](https://www.amazon.com/dp/B07D74RGVM) |
| 1 | Heat-shrink assortment | [B01MFA3OFA](https://www.amazon.com/dp/B01MFA3OFA) |
| opt. | 4-pin PWM fan extensions | [B0CNLDNZB2](https://www.amazon.com/dp/B0CNLDNZB2) |

With the board order (JLCPCB): the heatsink as a CNC part from
`mech/heatsink.step` plus `mech/heatsink_drawing.pdf` (threads, tolerances):
6061-T6 aluminium, **no surface finish** (anodising would insulate it; it is
grounded through its feet), two M3 threads in the feet, foot height
2.20 +/-0.05 mm. Also needed: thermal paste (Arctic MX-4 or similar) and two M3 x 5 mm
screws (they go up through the board into the heatsink).

## Files

| Path | What |
|---|---|
| `carrier.kicad_sch` / `.kicad_pcb` / `.kicad_pro` | KiCad 10 project (generated, see below) |
| `lib/carrier.kicad_sym`, `lib/carrier.pretty/` | Custom symbols and footprints |
| `lib/ref/` | EasyEDA/JLC reference symbols and footprints used to check pinouts |
| `datasheets/` | Every datasheet used, plus the HAT mechanical drawing and TI's EVM guide |
| `mech/heatsink.step`, `.stl` | Heatsink for CNC |
| `tools/` | Generators and checks (below) |
| `out/` | Renders, PDF, BOM, reports (generated, not committed) |

## Regenerating everything

The schematic and board are produced by scripts, not edited by hand, so
every value and position is reviewable in one place. KiCad runs as a
Flatpak; `kicad-cli` is a wrapper in `~/.local/bin`. The Python virtualenv
`.venv` holds `easyeda2kicad`, `cadquery` and `matplotlib`.

```bash
cd hardware/carrier
python3 tools/make_symbols.py            # lib/carrier.kicad_sym
python3 tools/gen_sch.py                 # carrier.kicad_sch (part numbers included)
python3 tools/render.py                  # out/sch/full.png, plus crops: render.py name x1 y1 x2 y2
kicad-cli sch erc -o out/erc.rpt carrier.kicad_sch
kicad-cli sch export pdf -o out/carrier.pdf carrier.kicad_sch
kicad-cli sch export bom --fields 'Value,Reference,Footprint,LCSC,MPN,Manufacturer,${QUANTITY},${DNP}' \
  --labels 'Comment,Designator,Footprint,LCSC,MPN,Manufacturer,Qty,DNP' \
  --group-by 'Value,Footprint,LCSC,${DNP}' --exclude-dnp -o out/bom_jlcpcb.csv carrier.kicad_sch

tools/build_board.sh                     # placement, planes, hand routes, Freerouting, finish, DRC (~20 min)
tools/build_board.sh noauto              # stop before the autorouter
flatpak run --command=python3 org.kicad.KiCad tools/dump_pcb.py   # then:
.venv/bin/python tools/view_pcb.py NAME [x0 y0 x1 y1] [--nets TEXT] [--labels]   # out/pcb/NAME.png
.venv/bin/python tools/fit_plate.py      # mech/fit_plate.stl

.venv/bin/python tools/heatsink.py       # mech/heatsink.step/.stl
kicad-cli pcb export step --subst-models --force -o mech/carrier_board.step carrier.kicad_pcb
.venv/bin/python tools/assembly.py       # mech/assembly.step/.stl
.venv/bin/python tools/render3d.py       # out/3d/*.png
```

What each script owns:

- `make_symbols.py`: custom symbols (TAS6424, LM61460, LM74800, DS3231,
  PCM1808, harness, Pi header). Pin numbers and names were checked against
  datasheets / EasyEDA each time a symbol was rearranged.
- `gen_sch.py` + `schlib.py`: the schematic. Each section is a function
  placed at an anchor; `PARTS` maps (value, footprint) to MPN /
  manufacturer / LCSC. Part UUIDs are derived from references, so reruns are
  byte-identical and the board stays linked to the schematic.
- `gen_pcb.py` + `place.py`: board outline, 4-layer stackup, JLC design
  rules, net classes and placement. `place.py` holds the Pi position, the
  notch/slot geometry and every block's layout, with parts found by
  Section field and nets.
- `route.py`: everything that carries current or needs care, locked so the
  autorouter works around it. In1 is solid GND; In2 is split into
  +12V_PROT (protection, amp, buck input) and +5V (buck output, Pi, LDO,
  clocks, fans). Top-layer pours for the battery path, VMID, buck VIN/PGND/SW
  and output, amp PVDD and the Pi's 5 V pins. Hand-routed amp outputs (P legs
  on top, M legs dropped to the bottom under the coils) and speaker lanes
  (1 mm, nested so none cross). Every GND pad gets its own via to In1, and
  +5V/+12V pads over their In2 region likewise. The LM74800's 0.5 mm pins
  and a few tight nets are routed by `maze.py` (a small grid router).
  Nothing copper within 3 mm of the outer edge.
- `autoroute.py` exports to Freerouting (with keepouts guarding the pours)
  and imports the result; `finish.py` maze-routes anything left open.
- `heatsink.py`, `assembly.py`, `render3d.py`: mechanical.

## Verification so far

- ERC: 0 errors, 0 warnings.
- Netlist check: every Pi GPIO lands on its intended net; amp pins, speaker
  filters and clock nets checked net by net.
- Board: 0 schematic-parity issues; no courtyard overlaps or clearance
  errors; parts clear of the Pi socket's solder pins by 3 mm; only parts
  under 2.2 mm under the heatsink.
- BOM: 148 fitted parts, all LCSC numbers present and in stock when chosen
  (2026-09-22/24).
- Pi socket orientation: pin 1 over the Pi's pin 1, checked by pad position
  (a mirrored socket would put 5 V on the wrong pins).
- Software: 18 tests on simulated hardware, including the GPIO request
  struct compared byte for byte with `<linux/gpio.h>`.

## Open items

1. ~~Fit check~~: done 2026-09-24, the corrected outline (`mech/fit_frame.stl`)
   fits the screen, screw holes, header and port notch exactly.
2. Measure display thickness and the display-to-Pi standoff height (3D
   model only).
3. Tidy silkscreen; add the harness pin table next to J1.
4. Final review (renders, BOM, cost), then order: board + assembly + CNC
   heatsink from JLCPCB.
5. On first power-up: confirm the react-carplay window class used for
   steering-wheel keys, run learn mode, check amp start-up and fault
   handling on real hardware, and check the mic capture path (the overlay
   puts two dummy codecs on one I2S link; set mic gain in software).
