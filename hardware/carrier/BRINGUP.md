# Carrier board: first power-up (rev A)

Work through the stages in order and don't skip ahead: each one powers a
little more of the board than the last, so a fault shows up while it can
still only hurt one part. Write every reading in the log at the bottom.

**You need:** a bench supply with a current limit (0 to 30 V, 3 A), a
multimeter (frequency mode helps), fly leads with small hooks, and a
Micro-Fit plug with leads on pins 1, 2, 7, 10, 17 (or bare wire pushed into
J1 for the early stages). Optional: a scope, a 4 Ω or 8 Ω speaker or power
resistor, the two fans, a CR2032.

**Rules for every stage**

- Never plug USB-C into the Pi while the carrier is powered (nothing stops
  the two 5 V supplies back-feeding each other).
- The speaker outputs are bridged (BTL). Neither leg is ground. Don't put a
  scope ground clip on a speaker pin, and don't connect a speaker leg to
  chassis.
- If the current reads above the limit given for a stage, or anything gets
  warm that shouldn't, turn off and stop.

Harness pins used on the bench (pin n sits directly above pin n+10):

| J1 pin | Signal | Bench connection |
|---|---|---|
| 1, 11 | +12 V constant | Supply + |
| 2, 12, 19 | Ground | Supply − |
| 7 | Key / ACC | Jumper to + to switch the board on |
| 17 | Headlights | Jumper to + for night mode |
| 10 | Reverse | Jumper to + for reverse |
| 8, 18 / 9 | Steering wheel 1, 2 / its ground | Resistors to pin 9 (stage 6) |

## Stage 0: look before powering

With a loupe or phone macro, against `fab/pcbway/assembly_top.pdf`:

- [ ] U7 (TAS6424, 0.635 mm pitch): no bridges along either row of 28 pins.
- [ ] U1 (LM74800 WSON) and U5 (LM61460 QFN): square on their pads, no
      solder balls beside them.
- [ ] Pin-1 dots on U2, U3, U4, U6, U7, U8 and Q3-Q7 against the silkscreen
      dot (U2, U3, U4, U6 and U7 were the parts whose rotation was corrected in
      the placement file).
- [ ] Q1 and Q2 (LFPAK56): the tab on the large pad, the three pins on the
      small ones.
- [ ] L1 centred on its pads.
- [ ] BT1: the "+" side of the holder on the + silkscreen mark. A reversed
      holder puts −3 V on the DS3231.
- [ ] J1 latch on the side the silkscreen shows; fan header (M1, M2) ramps
      likewise.
- [ ] J2 (Pi socket) on the underside, straight, all 40 pins soldered.
- [ ] D8/D9/D10 (LEDs) fitted. Their polarity gets checked in stage 2.

## Stage 1: resistance, unpowered

Meter on ohms, black lead on GND (a heatsink hole H5/H6 is the easiest GND
pad). Each rail must be well above a short. Capacitors charge, so the
reading climbs; note where it settles.

| Net | Where to probe | Expect |
|---|---|---|
| +12V_BATT | J1 pin 1 | > 10 kΩ |
| +12V_PROT | C36 (470 µF) + lead | > 10 kΩ (climbs slowly) |
| +5V | J2 pin 2 | > 100 Ω |
| +3V3 | C28 or any 3V3 cap | > 100 Ω |
| SYS_EN | C12 + side | > 10 kΩ |

Then diode mode, red on GND, black on J1 pin 1: you should see the TVS
(D1) and nothing like 0 V.

Anything under 10 Ω: stop, don't power it, and find the short first (warm
it with 0.5 A at 1 V on the suspect rail and feel which part heats up).

## Stage 2: board alone, no Pi

Supply 12.0 V, **limit 150 mA**, on pins 1 and 2. ACC (pin 7) open.

1. **Off state.** Turn the supply on with ACC open. The board should stay
   off: current under 0.1 mA (design: about 3 µA), no LEDs lit.
2. **Key on.** Jumper pin 7 to +12 V.
   - [ ] D8 (12V) and D9 (5V) light, D10 (PI) stays off.
   - [ ] Current settles at tens of mA (amp in standby, buck idling). Over
         150 mA is a fault.
3. **Rails** (meter to GND):

   | Net | Where | Expect |
   |---|---|---|
   | +12V_PROT | C36 + | supply minus ~0.1 V |
   | +5V | J2 pin 2 or 4 | 4.89 to 5.15 V |
   | +3V3 | C28 | 3.23 to 3.37 V |
   | SYS_EN | C12 + | ~12 V (under 15 V) |
   | Coin cell | BT1 + (no cell fitted) | 0 V |

4. **Header safety check before the Pi ever goes on.** With the board on,
   probe each J2 socket contact (a male jumper wire in the socket makes this
   easy). Pins 2 and 4 must read 5 V. **Every other pin must be at or under
   3.4 V.** Pins 1 and 17 (the Pi's own 3V3) must read 0 V: the board leaves
   them unconnected. Any signal pin at 5 V or 12 V would kill the Pi.
5. **Audio clocks** (meter in frequency mode, or scope):

   | Signal | Where | Expect |
   |---|---|---|
   | MCLK | R38, either end | 12.288 MHz |
   | BCLK | J2 pin 12 | 3.072 MHz |
   | LRCK / FSYNC | J2 pin 35 | 48.000 kHz |

   A missing BCLK/LRCK with MCLK present points at U8 (PCM1808) or its
   MD0/MD1 straps.
6. **Inputs.** ~ACC_ON on J2 pin 11 reads ~0 V with ACC on. Jumper pin 17
   (lights) to +12 V: J2 pin 13 drops from 3.3 V to ~0 V. Same for pin 10
   (reverse) and J2 pin 26.
7. **Key off.** Remove the ACC jumper and time it. The board should hold on
   for 4.5 to 9.6 s (the crank ride-through), then D8/D9 go out and the
   current drops back under 0.1 mA within ~12 s.
8. **Undervoltage (cranking).** ACC on, lower the supply slowly from 12 V.
   +5V should hold up to ~5.1 V at the input and the buck should stop
   between 3.8 and 4.9 V. Raise it again: it restarts between 5.6 and 6.4 V.
9. **Reverse battery (optional but quick).** Limit 100 mA, swap the supply
   leads at J1 (− on pin 1, + on pin 2), 12 V, ACC on. Current should be
   near zero and nothing lit. Swap back and check that stage 2 step 2 still
   passes.

Skip the over-voltage cutoff (32.6 to 36 V) on the bench. It sits right
at the buck's limit, and a failed cutoff would cost the board.

## Stage 3: Pi on, stock software

Fit the Pi with nylon washers on both faces at H1 and H4 (tracks run under
those standoffs), the display attached as in the car. Don't install any
carrier software yet: with GPIO26 still an input, the board turns off on
key-off the same as in stage 2.

Supply 12 V, **limit 3 A**. ACC on.

- [ ] Inrush: the supply shouldn't hit the limit for more than a moment.
- [ ] The Pi and the screen boot. Running current at 12 V: note it (expect
      ~0.5 to 1 A).
- [ ] +5V at J2 under load: still above 4.9 V. `vcgencmd get_throttled`
      returns `0x0` (no undervoltage).
- [ ] Over SSH:

  ```
  vcgencmd get_throttled                     # 0x0
  sudo dtparam -d /boot/overlays i2c_arm=on  # until reboot only
  sudo modprobe i2c-dev
  i2cdetect -y 1        # expect 48 (ADC), 68 (RTC), 6a (amp)
  i2cdetect -y 0        # expect 50 (ID EEPROM, GPIO0/1 through the i2c-22 mux)
  pinctrl get 17,27,7   # ACC, lights, reverse: lo when active
  ```

  This Pi's OS keeps its config in `/boot/config.txt` and has no
  i2c-tools; a short Python probe does the same job.

  Normal readings here: amp registers 0x0F = 0x55 (all channels Hi-Z),
  faults 0x10 to 0x12 = 0, warnings 0x13 = 0x20 (VDD power-on, set at every
  power-up). GPIO24/25 read low until carrierd turns on their pull-ups:
  the board has none on those two lines.

  Toggle the lights and reverse jumpers and re-read `pinctrl get 27,7`.

## Stage 4: carrier software, power hold, RTC

Install with `launcher/board/install.sh --reboot` (progress card on the
Pi's screen; details in `launcher/board/README.md`). Without `--audio` it
leaves CarPlay on the USB adapter; the overlay already has the 32-bit slot
fix (finding A in VERIFICATION.md) that keeps FR and RR from going silent.

carrierd stays disabled until `--enable`, so this stage tests the hardware,
not the daemon.

- [ ] D10 (PI) lights once the Pi is up: GPIO26 holds the board.
- [ ] Remove ACC. The Pi stays on (nothing shuts it down yet).
- [ ] `sudo poweroff`. 3 to 5 s after the Pi halts, D8/D9/D10 go out and
      the current falls under 0.1 mA.
- [ ] RTC: `sudo hwclock -r` works. Fit the CR2032 (+ up, check against
      BT1's mark), `sudo hwclock -w`, power off, leave the supply off for a
      few minutes, boot: the time is right before the network comes up.

## Stage 5: fans

Plug both fans into M1 and M2.

- [ ] Before the Pi drives PWM, both run at full speed (fail-safe).
- [ ] `echo` a 25 kHz period and a low duty to `/sys/class/pwm/pwmchip0/pwm0`
      (and `pwm1`): the fan slows. The board's FET inverts the PWM, so a
      higher duty means slower.
- [ ] Tach on GPIO16 (fan 1) and GPIO4 (fan 2) toggles: 2 pulses per rev.

## Stage 6: ADC, steering wheel inputs

- [ ] Battery monitor (ADS1115 AIN2): the divider is R2 95.3k over R3 5.11k
      + R4 3.74k (it shares R4 with the OV cutoff divider) fed from the
      LM74800's SW pin, so AIN2 = battery / 11.77, ~1.02 V at 12 V. Check at
      12 and 14 V.
- [ ] Pins 8 and 18 open: AIN0/AIN1 read near 3.3 V. Short each to pin 9:
      near 0 V. 100 Ω: ~0.30 V. 330 Ω: ~0.82 V.

## Stage 7: amplifier

**Heatsink on U7 first** (the stock 20 x 20 mm, retained and grounded to H5
or H6; README "Amp heatsink"), fan 1 over it.

One speaker (or a 4 to 8 Ω power resistor) across one channel's + and −
pins, e.g. front left on pins 4 and 14. Supply limit 3 A.

1. Start carrierd (`sudo systemctl start carrierd`) and watch
   `journalctl -u carrierd -f`. It brings the amp up in datasheet order.
   - [ ] No I2C errors; ~AMP_FAULT (GPIO24) stays high.
2. Low volume first:

   ```
   speaker-test -D pulse -c 2 -r 48000 -t sine -f 440 -l 1
   ```

   - [ ] A clean tone on the channel under test. Move the speaker through
         FL (4/14), FR (3/13), RL (6/16), RR (5/15): each must work. FR and RR
         silent means the slot fix above isn't in.
   - [ ] Fader and balance through `POST /fader` move the sound between
         channels.
3. With no audio playing the outputs should be quiet: no hiss or hum heard
   at the speaker with your ear close.
4. Ten minutes of music at a loud level, fan on: the heatsink stays under
   ~80 °C (IR thermometer or thermocouple), ~AMP_WARN (GPIO25) stays high,
   no fault in the log.

## Stage 8: microphone

- [ ] Car mic in J4. `arecord -D <carrier mic device> -r 48000 -f S32_LE -c 2
      -d 5 /tmp/mic.wav`, play it back. Speech on the left channel. Set
      the gain in software.

## Then the truck

Build the harness plug (README "Wiring the truck"), check every pin of the
finished plug with a meter against the table before it goes near the board,
and redo stage 2 steps 2 to 7 in the truck with the Pi off. Then learn mode for the
wheel and the items in README open item 6.

## Log

Board serial / sticker: ________ Date: 2026-10-24

| Stage | Reading | Value | OK? |
|---|---|---|---|
| 1 | +12V_BATT / +12V_PROT / +5V / +3V3 to GND | | |
| 2.1 | Off current | 0.01 A on the supply display (at its resolution; check with a meter) | ? |
| 2.2 | On current, ACC, no Pi | | |
| 2.3 | +12V_PROT / +5V / +3V3 / SYS_EN | | |
| 2.4 | Highest J2 signal pin | | |
| 2.5 | MCLK / BCLK / LRCK | BCLK, LRCK dead at the Pi (GPIO18/19 low in 200/200 samples; method checked on a 25 kHz PWM: 94/106). MCLK not measured yet | **FAIL** |
| 2.7 | Hold time after ACC off | ~5 s | yes |
| 2.8 | Buck stop / start voltage | dip to 6 V with the Pi running: no reset, throttled 0x0 | yes |
| 2.9 | Reverse current | | |
| 2.6 | Lights / reverse / ACC inputs | each follows 12 V on and off; ACC dropout of 4.4 s rides through on the hold | yes |
| 3 | Run current with Pi + screen; get_throttled | not read; 0x0 | yes |
| 3 | i2cdetect bus 1 / bus 0 | 48, 68, 6a / 50 | yes |
| 4 | Cut-off delay after halt; RTC kept time | ~6 s after screen off; -0.28 s after full power-off | yes |
| 5 | Fan PWM / tach | default 4557 / 4707 rpm; 100 % 4665 / 4815, 50 % 2447 / 2527, 25 % 1146 / 1186, 0 % stopped | yes |
| 6 | AIN2 at 12 V; SWC open / 0 / 220 Ω | 11.87 V; pin 8: 3.293 / 0.003 / 0.595 V, pin 18: 3.293 / - / 0.598 V | yes |
| 7 | Each channel; heatsink temp after 10 min | board 2: DC diag clean on all 4; FR/FL/RR/RL tones heard on pins 3-13/4-14/5-15/6-16 at -30 dB, no faults; loud/thermal test not done | partial |
| 8 | Mic | board 2: empty jack -75 dBFS; speaking -73 to -37 dBFS rms, peak -21 dBFS; voice clear on playback (needs ~+20 dB software gain) | yes |

Notes from 2026-10-24:

- Stage 2 was run with the Pi already fitted, so the header check (2.4)
  and the board-only current (2.2) were skipped. A 300 mA limit tripped at
  switch-on with the Pi attached, which is expected.
- A flaky ACC jumper made the board cycle (hold time, then off, then on
  again) and looked like a boot loop.
- Battery monitor read 11.87 V at a 12.0 V supply.
- The RTC lost time once across a Pi reboot with ACC on and no coin cell
  fitted (cause not found; a 3.3 V dip during the Pi reset would do it).
  With the CR2032 fitted it keeps time through a full power-off.
- Audio clocks: BCLK (GPIO18) and LRCK (GPIO19) never toggle at the Pi.
  Checked and fine: schematic (MD1 = MD0 = high is master 256 fS per Table 2
  of the PCM1808-Q1 datasheet, SCKI/LRCK/BCK/DOUT on pins 6 to 9), X1 pinout
  and footprint (SCTF 3C series: 1 tri-state, 2 GND, 3 out, 4 Vdd), and in a
  photo X1 and U8 orientation and U8's visible joints. Next, DC volts (a
  running 50 % clock reads ~1.65 V): R38 (MCLK from X1), both ends of R40
  (BCK) and R41 (LRCK), U8 pin 3 (5 V) and pin 4 (3.3 V). Suspects: X1 not
  oscillating (pads hidden under the package) or U8 not running.
- Board 2 (2026-10-24, same Pi and software): BCLK, LRCK and DOUT all
  toggle at the Pi (GPIO18 162/300 high, GPIO19 151/300, GPIO20 129/300),
  so the clock design works and board 1 has a local fault (X1 joint or
  part most likely, then U8). Board 2 also passes power hold, I2C (48, 68,
  6a / 50) and the ACC/lights/reverse idle states. Bring-up continues on
  board 2; board 1 waits for the meter check and a rework.
- Amp on board 2 (2026-10-24), `python3 -m board.amptest` (launcher/board):
  `diag` with nothing connected reads open load on all four channels and no
  shorts (wait 1.5 s: at 0.5 s CH4 was not finished and read "load OK"). A
  10 ohm resistor reads "load OK" and plays without faults. With a headset
  earpiece, each channel's own tone (FL 440, FR 660, RL 880, RR 1100 Hz) was
  recorded on a PC mic only in that channel's slot, 20 to 50 dB over
  background, on the pins in README's harness table (amp CH1 RL, CH2 RR,
  CH3 FL, CH4 FR). The first tries failed only because the earpiece sat on
  pins 3/13 while FL (4/14) was playing: count the top row from pin 1 (+12 V).
  Still to do: loud test into 4 ohm with the heatsink and a fan.
- Mic capture: with both dummy codecs on one dai-link, this kernel (6.18)
  only offered playback. The overlay now has one link per direction (both
  on the I2S port): capture is Carrier device 0, playback device 1.
  PulseAudio opens the capture device on its own and at 44.1 kHz; record
  with `pasuspender -- arecord -D hw:Carrier,0 -f S32_LE -r 48000 -c 2`
  until PulseAudio is set to 48 kHz (needed anyway before CarPlay audio
  moves to the board).
- Music (30 s of a trailer soundtrack) played on RL through the earpiece at
  -30 dB with no faults.

## In the truck (board 2, 2026-10-28)

Harness: Klintotour Toyota adapter, 16-pin Android end cut off and crimped
into the Micro-Fit (`tools/harness_diagram.py`).

| Check | Result |
|---|---|
| Audio, all four speakers, CarPlay, mic | Pass (amp DC diagnostics clean at start, no faults) |
| Battery reading | 13.7 V running, 12.9 V off |
| Headlights -> night mode | Pass |
| Engine restart with the Pi running | Pass: ACC dropped for ~1 s, battery dipped to 11.6 V, Pi stayed up |
| Key off -> shutdown | Pass: 8 s countdown, clean halt, board off |
| Wheel volume, next/previous | Pass after the fixes (tolerances, DevTools key delivery) |
| Wheel Mode (KEY2, pin 18) | Pass: 0.01 V pressed, learned, bound to play/pause |
| Fan tachs | Pass: both read ~4600-4800 rpm at full speed (the 240 rpm cap was a software bug) |
| Reverse | Not wired yet |
