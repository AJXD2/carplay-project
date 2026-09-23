#!/usr/bin/env python3
"""Generate lib/carrier.kicad_sym: the symbols the stock KiCad library lacks.

Every pin table here was cross-checked against the manufacturer datasheet
and the EasyEDA/LCSC symbol for the exact part (see lib/ref/). Pins that
share a function are stacked with KiCad's "[a,b,c]" pin-number syntax.

Layout convention (KLC): power in on top, grounds on the bottom, inputs on
the left, outputs on the right. `None` in a side list leaves a one-grid gap.
"""
import os

GRID = 2.54
PIN_LEN = 2.54

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "lib", "carrier.kicad_sym")


def P(name, number, etype, alternates=()):
    return {"name": name, "number": number, "type": etype, "alt": alternates}


def font(size=1.27):
    return f"(effects (font (size {size} {size})))"


def pin_len(p):
    """Long stacked pin numbers ("[2,29,30]") are drawn along the pin, so the
    pin must be long enough to hold them without running into the pin name."""
    n = len(p["number"])
    if n <= 3:
        return GRID
    return min(3 * GRID, max(GRID, -(-(n * 1.25 + 1.0) // GRID) * GRID))


def pin_sexpr(p, x, y, angle, length):
    alts = "".join(f'(alternate "{a}" {t} line)' for a, t in p["alt"])
    return (f'(pin {p["type"]} line (at {x:.2f} {y:.2f} {angle}) (length {length:.2f}) '
            f'(name "{p["name"]}" {font()}) (number "{p["number"]}" {font()}) {alts})')


def clearance_rows(items):
    """Rows to keep free inside the body under top pins / above bottom pins,
    since their names are drawn rotated into the body."""
    names = [len(p["name"]) for p in items if p]
    if not names:
        return 0
    return int(-(-(max(names) * 0.9 + 0.8) // GRID))


def symbol(name, ref, value, footprint, datasheet, description, keywords,
           left, right, top, bottom, width, fields=None):
    rows = max(len(left), len(right))
    top_rows, bot_rows = clearance_rows(top), clearance_rows(bottom)
    half_w = round(width / 2 / GRID) * GRID

    def step_of(items):
        return 3 if any(p and len(p["number"]) > 6 for p in items) else 2

    # widen the body so top/bottom pins always land inside it with a grid to spare
    for items in (top, bottom):
        if items:
            half_w = max(half_w, (round((len(items) - 1) * step_of(items) / 2) + 1) * GRID)
    total_rows = top_rows + rows + bot_rows + 1
    top_y = round(total_rows * GRID / 2 / GRID) * GRID
    bot_y = top_y - total_rows * GRID
    pins = []
    # one pin length per side, so the pin ends line up neatly
    side_len = lambda items: max([pin_len(p) for p in items if p] or [GRID])  # noqa: E731
    L = side_len(left)
    for i, p in enumerate(left):
        if p:
            pins.append(pin_sexpr(p, -half_w - L, top_y - (top_rows + i + 1) * GRID, 0, L))
    L = side_len(right)
    for i, p in enumerate(right):
        if p:
            pins.append(pin_sexpr(p, half_w + L, top_y - (top_rows + i + 1) * GRID, 180, L))

    def spread(items, edge_y, sign):
        n = len(items)
        step = step_of(items)
        start = round(-((n - 1) * step) / 2) * GRID  # keep pins on the 100 mil grid
        L = side_len(items)
        for i, p in enumerate(items):
            if p:
                pins.append(pin_sexpr(p, start + i * step * GRID, edge_y + sign * L,
                                      270 if sign > 0 else 90, L))

    spread(top, top_y, +1)
    spread(bottom, bot_y, -1)
    top_ext = max([pin_len(p) for p in top if p] or [0])
    bot_ext = max([pin_len(p) for p in bottom if p] or [0])
    extra = "".join(f'(property "{k}" "{v}" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))'
                    for k, v in (fields or {}).items())
    return f'''
  (symbol "{name}" (pin_names (offset 0.508)) (exclude_from_sim no) (in_bom yes) (on_board yes)
    (property "Reference" "{ref}" (at {-half_w:.2f} {top_y + top_ext + 1.27:.2f} 0) (effects (font (size 1.27 1.27)) (justify left bottom)))
    (property "Value" "{value}" (at {-half_w:.2f} {bot_y - bot_ext - 1.27:.2f} 0) (effects (font (size 1.27 1.27)) (justify left top)))
    (property "Footprint" "{footprint}" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
    (property "Datasheet" "{datasheet}" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
    (property "Description" "{description}" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
    (property "ki_keywords" "{keywords}" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
    (property "ki_fp_filters" "{footprint.split(':')[-1].split('_')[0]}*" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
    {extra}
    (symbol "{name}_0_1"
      (rectangle (start {-half_w:.2f} {top_y:.2f}) (end {half_w:.2f} {bot_y:.2f})
        (stroke (width 0.254) (type default)) (fill (type background))))
    (symbol "{name}_1_1"
      {chr(10).join("      " + p for p in pins)})
    (embedded_fonts no))'''


SYMBOLS = []

# --- TI TAS6424E-Q1, 4-ch class-D, digital input (datasheet SLOSE73A table 6-1)
SYMBOLS.append(symbol(
    "TAS6424E-Q1", "U", "TAS6424E-Q1",
    "Package_SO:SSOP-56_7.5x18.5mm_P0.635mm",
    "https://www.ti.com/lit/ds/symlink/tas6424e-q1.pdf",
    "45-W 2.1-MHz digital-input 4-channel automotive class-D amplifier, HSSOP-56 (DKQ, thermal pad on top: needs a GND heatsink)",
    "class-D amplifier audio automotive I2S TDM",
    # SDIN2 / I2C_ADDRx tie to GND: two gaps after each group leave room for
    # the ground symbol. Analog bypass pins sit two gaps apart so their caps can
    # lie horizontally between pin and return bus. AREF / AVSS are *local*
    # bypass returns (datasheet fig 10-2), NOT ground.
    left=[P("MCLK", "12", "input"), P("SCLK", "13", "input"), P("FSYNC", "14", "input"),
          P("SDIN1", "15", "input"), P("SDIN2", "16", "input"), None, None,
          P("SCL", "20", "input"), P("SDA", "21", "bidirectional"),
          P("I2C_ADDR0", "22", "input"), P("I2C_ADDR1", "23", "input"), None, None,
          P("~{STANDBY}", "24", "input"), P("~{MUTE}", "25", "input"), None,
          P("VREG", "5", "power_out"), None, None, P("VCOM", "6", "power_out"), None, None,
          P("AREF", "4", "passive"), None, None, P("AVDD", "8", "power_out"), None, None,
          P("AVSS", "7", "passive"), None, P("GVDD", "[9,10]", "power_out")],
    # each channel: BST_P, gap, OUT_P, OUT_M, gap, BST_M so the 1 uF boot caps
    # lie on the BST rows and drop one row to their OUT pin
    right=[P("~{FAULT}", "26", "open_collector"), P("~{WARN}", "27", "open_collector"), None,
           P("BST_1P", "35", "passive"), None, P("OUT_1P", "34", "output"),
           P("OUT_1M", "32", "output"), None, P("BST_1M", "31", "passive"), None, None,
           P("BST_2P", "41", "passive"), None, P("OUT_2P", "40", "output"),
           P("OUT_2M", "38", "output"), None, P("BST_2M", "37", "passive"), None, None,
           P("BST_3P", "48", "passive"), None, P("OUT_3P", "47", "output"),
           P("OUT_3M", "45", "output"), None, P("BST_3M", "44", "passive"), None, None,
           P("BST_4P", "54", "passive"), None, P("OUT_4P", "53", "output"),
           P("OUT_4M", "51", "output"), None, P("BST_4M", "50", "passive")],
    top=[P("PVDD", "[2,29,30]", "power_in"), P("PVDD", "[42,43]", "power_in"),
         P("PVDD", "[55,56]", "power_in"), P("VBAT", "3", "power_in"), P("VDD", "19", "power_in")],
    bottom=[P("GND", "[1,11,17]", "power_in"), P("GND", "[18,28,33]", "power_in"),
            P("GND", "[36,39,46]", "power_in"), P("GND", "[49,52]", "power_in")],
    width=25.4))

# --- TI LM61460-Q1, 36 V 6 A synchronous buck, VQFN-HR-14 RJR (SNVSB70F table 7-1)
SYMBOLS.append(symbol(
    "LM61460-Q1", "U", "LM61460-Q1",
    "carrier:TI_RJR0014A_VQFN-HR-14_3.5x4mm",
    "https://www.ti.com/lit/ds/symlink/lm61460-q1.pdf",
    "Automotive 3-V to 36-V 6-A synchronous buck, FPWM + spread spectrum, VQFN-HR-14",
    "buck regulator automotive step-down",
    # BIAS on top beside VIN so it ties straight to a +5V symbol; SW/CBOOT/RBOOT
    # spaced one gap apart so the 100 nF boot cap and boot resistor wire neatly
    left=[P("EN/SYNC", "7", "input"), P("RT", "6", "passive"), None,
          P("VCC", "2", "power_out")],
    right=[P("SW", "10", "output"), None, P("CBOOT", "14", "passive"), None,
           P("RBOOT", "13", "passive"), None, P("FB", "4", "input"), P("PGOOD", "5", "open_collector")],
    top=[P("VIN", "[8,12]", "power_in"), P("BIAS", "1", "power_in")],
    bottom=[P("AGND", "3", "power_in"), P("PGND", "[9,11]", "power_in")],
    width=17.78))

# --- TI LM74800-Q1 ideal diode + load-dump controller, WSON-12 DRR (SNOSD... table)
SYMBOLS.append(symbol(
    "LM74800-Q1", "U", "LM74800-Q1",
    "Package_SON:WSON-12-1EP_3x3mm_P0.5mm_EP1.5x2.5mm",
    "https://www.ti.com/lit/ds/symlink/lm7480-q1.pdf",
    "Ideal diode controller with load-dump (overvoltage) cutoff, back-to-back N-FETs, WSON-12. Exposed pad RTN must float (not GND)",
    "ideal diode reverse battery load dump automotive",
    left=[P("A", "2", "passive"), None, P("VSNS", "3", "passive"), P("SW", "4", "passive"),
          P("OV", "5", "input"), P("EN/UVLO", "6", "input")],
    right=[P("C", "12", "passive"), P("DGATE", "1", "output"), None,
           P("HGATE", "8", "output"), P("OUT", "9", "passive")],
    top=[P("VS", "10", "power_in"), P("CAP", "11", "passive")],
    bottom=[P("GND", "7", "power_in"), P("RTN", "13", "passive")],
    width=17.78))

# --- Analog Devices DS3231SN, TCXO RTC, SOIC-16W. Pins 5-12 must be grounded.
SYMBOLS.append(symbol(
    "DS3231SN", "U", "DS3231SN",
    "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm",
    "https://www.analog.com/media/en/technical-documentation/data-sheets/DS3231.pdf",
    "Extremely accurate I2C RTC with integrated TCXO and crystal, SOIC-16W. N.C. pins 5-12 must be grounded (stacked on GND)",
    "RTC real time clock I2C TCXO",
    left=[P("SCL", "16", "input"), P("SDA", "15", "bidirectional"), None, P("~{RST}", "4", "bidirectional")],
    right=[P("32KHZ", "1", "open_collector"), P("~{INT}/SQW", "3", "open_collector")],
    top=[P("VCC", "2", "power_in"), P("VBAT", "14", "power_in")],
    bottom=[P("GND", "13", "power_in"), P("GND", "[5,6,7,8]", "power_in"),
            P("GND", "[9,10,11,12]", "power_in")],
    width=20.32))

# --- Cirrus CS2100-CP fractional-N clock multiplier (DNP fallback MCLK source)
SYMBOLS.append(symbol(
    "CS2100-CP", "U", "CS2100-CP",
    "Package_SO:MSOP-10_3x3mm_P0.5mm",
    "https://statics.cirrus.com/pubs/proDatasheet/CS2100-CP_F3.pdf",
    "Fractional-N clock multiplier, I2C control, MSOP-10",
    "clock PLL multiplier MCLK",
    left=[P("CLK_IN", "5", "input"), P("XTI/REF_CLK", "7", "input"), P("XTO", "6", "output"), None,
          P("SCL", "9", "input", [("CCLK", "input")]),
          P("SDA", "10", "bidirectional", [("CDIN", "input")]),
          P("AD0", "8", "input", [("~{CS}", "input")])],
    right=[P("CLK_OUT", "3", "output"), P("AUX_OUT", "4", "output")],
    top=[P("VD", "1", "power_in")],
    bottom=[P("GND", "2", "power_in")],
    width=27.94))

# --- 2007 4Runner harness (Metra adapter wires crimped into a Micro-Fit 2x10).
# Pin n sits directly above pin n+10, so each wire pair shares a column.
pa = "passive"
SYMBOLS.append(symbol(
    "Harness_4Runner", "J", "Harness_4Runner",
    "Connector_Molex:Molex_Micro-Fit_3.0_43045-2000_2x10_P3.00mm_Horizontal",
    "https://www.molex.com/pdm_docs/sd/430450201_sd.pdf",
    "Head-unit harness for the 2007 Toyota 4Runner (non-JBL), Molex Micro-Fit 3.0 2x10. REV = reverse-light 12 V",
    "harness connector car radio micro-fit",
    left=[P("+12V_BATT", "[1,11]", pa), None, P("ACC", "7", pa), P("ILLUM", "17", pa), P("REV", "10", pa), None,
          P("SWC1", "8", pa), P("SWC2", "18", pa), P("SWC_GND", "9", pa)],
    right=[P("SPK_FL+", "3", pa), P("SPK_FL-", "13", pa), None, P("SPK_FR+", "4", pa), P("SPK_FR-", "14", pa), None,
           P("SPK_RL+", "5", pa), P("SPK_RL-", "15", pa), None, P("SPK_RR+", "6", pa), P("SPK_RR-", "16", pa)],
    top=[],
    bottom=[P("GND", "[2,12,19]", pa), P("NC", "20", "no_connect")],
    width=27.94))

# --- Raspberry Pi 40-pin GPIO header as seen by a HAT (BCM names + alternates)
bi = "bidirectional"
SYMBOLS.append(symbol(
    "RaspberryPi_GPIO_40", "J", "RaspberryPi_GPIO_40",
    "Connector_PinSocket_2.54mm:PinSocket_2x20_P2.54mm_Vertical",
    "https://datasheets.raspberrypi.com/rpi4/raspberry-pi-4-datasheet.pdf",
    "Raspberry Pi 40-pin GPIO header, HAT side (female socket onto the Pi's pins)",
    "raspberry pi hat gpio header",
    left=[P("ID_SD", "27", bi), P("ID_SC", "28", bi), None,
          P("GPIO2", "3", bi, [("SDA1", bi)]), P("GPIO3", "5", bi, [("SCL1", bi)]),
          P("GPIO4", "7", bi, [("GPCLK0", "output")]), P("GPIO5", "29", bi), P("GPIO6", "31", bi),
          P("GPIO7", "26", bi, [("SPI0_CE1", "output")]), P("GPIO8", "24", bi, [("SPI0_CE0", "output")]),
          P("GPIO9", "21", bi, [("SPI0_MISO", "input")]), P("GPIO10", "19", bi, [("SPI0_MOSI", "output")]),
          P("GPIO11", "23", bi, [("SPI0_SCLK", "output")]),
          P("GPIO12", "32", bi, [("PWM0", "output")]), P("GPIO13", "33", bi, [("PWM1", "output")])],
    right=[P("GPIO14", "8", bi, [("TXD0", "output")]), P("GPIO15", "10", bi, [("RXD0", "input")]),
           P("GPIO16", "36", bi), P("GPIO17", "11", bi),
           P("GPIO18", "12", bi, [("PCM_CLK", "output")]), P("GPIO19", "35", bi, [("PCM_FS", "output")]),
           P("GPIO20", "38", bi, [("PCM_DIN", "input")]), P("GPIO21", "40", bi, [("PCM_DOUT", "output")]),
           P("GPIO22", "15", bi), P("GPIO23", "16", bi), P("GPIO24", "18", bi), P("GPIO25", "22", bi),
           P("GPIO26", "37", bi), P("GPIO27", "13", bi)],
    top=[P("5V", "[2,4]", "passive"), P("3V3", "[1,17]", "passive")],
    bottom=[P("GND", "[6,9,14]", "passive"), P("GND", "[20,25,30]", "passive"),
            P("GND", "[34,39]", "passive")],
    width=20.32))


def main():
    body = "".join(SYMBOLS)
    text = f'(kicad_symbol_lib (version 20251024) (generator "carrier_make_symbols") (generator_version "1.0"){body}\n)\n'
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(text)
    print("wrote", os.path.relpath(OUT))


if __name__ == "__main__":
    main()
