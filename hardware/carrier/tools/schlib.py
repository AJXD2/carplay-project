"""Tiny KiCad 10 schematic writer used by gen_sch.py.

Symbols are copied verbatim (balanced-paren extraction) from the stock
Flatpak library and lib/carrier.kicad_sym, so nothing is lost to a
round-trip through a parser. Pin coordinates are computed from the library
pin positions with the instance rotation/mirror, so wires and labels land
exactly on pin ends; ERC and the netlist check in check_sch.py confirm it.

Coordinates are millimetres, schematic convention (y grows downward).
"""
import math
import os
import re
import uuid as uuidlib

STOCK = "/var/lib/flatpak/runtime/org.kicad.KiCad.Library.Symbols/x86_64/stable/active/files/symbols"
HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = {"carrier": os.path.join(HERE, "..", "lib", "carrier.kicad_sym")}

G = 1.27  # 50 mil grid


def snap(v, g=G):
    return round(round(v / g) * g, 4)


def uid():
    return str(uuidlib.uuid4())


# ---------------------------------------------------------------- library --

def _balanced(text, start):
    depth = 0
    i = start
    in_str = False
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    raise ValueError("unbalanced")


_lib_cache = {}


def lib_text(lib):
    if lib not in _lib_cache:
        path = LOCAL.get(lib, os.path.join(STOCK, f"{lib}.kicad_sym"))
        with open(path) as f:
            _lib_cache[lib] = f.read()
    return _lib_cache[lib]


def symbol_block(lib_id):
    lib, name = lib_id.split(":")
    text = lib_text(lib)
    m = re.search(r'\(symbol "%s"\s' % re.escape(name), text)
    if not m:
        raise KeyError(lib_id)
    block = _balanced(text, m.start())
    ext = re.search(r'\(extends "([^"]+)"\)', block)
    if ext:
        block = _flatten(lib, name, block, ext.group(1))
    return block


def _props(block):
    out = {}
    for m in re.finditer(r'\(property "([^"]+)"', block):
        out[m.group(1)] = _balanced(block, m.start())
    return out


def _flatten(lib, name, derived, base_name):
    """Schematics store derived symbols fully expanded: take the base
    symbol's pins/graphics, rename it, and apply the derived properties."""
    base = symbol_block(f"{lib}:{base_name}")
    base = base.replace(f'(symbol "{base_name}"', f'(symbol "{name}"', 1)
    base = re.sub(r'\(symbol "%s_(\d+)_(\d+)"' % re.escape(base_name), rf'(symbol "{name}_\1_\2"', base)
    base_props = _props(base)
    for key, prop in _props(derived).items():
        if key in base_props:
            base = base.replace(base_props[key], prop, 1)
        else:
            i = base.index("(symbol", 1)  # before the first sub-unit
            base = base[:i] + prop + "\n" + base[i:]
    return base


def parse_pins(block):
    """(number, name, x, y, angle, length) for every pin, lib coords (y up)."""
    pins = []
    for m in re.finditer(r'\(pin (\w+) (\w+)\s*\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)\s*\(length ([-\d.]+)\)', block):
        tail = block[m.end():m.end() + 800]
        name = re.search(r'\(name "([^"]*)"', tail).group(1)
        number = re.search(r'\(number "([^"]*)"', tail).group(1)
        pins.append(dict(etype=m.group(1), number=number, name=name,
                         x=float(m.group(3)), y=float(m.group(4)), angle=float(m.group(5))))
    return pins


# --------------------------------------------------------------- schematic --

class Part:
    def __init__(self, sch, lib_id, ref, value, at, rot=0, mirror=None, footprint=None,
                 fields=None, dnp=False, hide_value=False, unit=1, in_bom=True):
        self.sch, self.lib_id, self.ref, self.value = sch, lib_id, ref, value
        self.x, self.y = snap(at[0]), snap(at[1])
        self.rot, self.mirror, self.unit = rot % 360, mirror, unit
        self.footprint, self.fields, self.dnp = footprint, fields or {}, dnp
        self.hide_value = hide_value
        self.in_bom = in_bom
        self.block = sch.use_symbol(lib_id)
        self.pins = parse_pins(self.block)
        self.uuid = uid()
        self.prop_pos = {}

    def _xf(self, px, py):
        """lib (y up) -> sheet (y down). KiCad rotates first, then mirrors in
        sheet space (verified against ERC with every rotation/mirror combo)."""
        a = math.radians(self.rot)
        rx = px * math.cos(a) - py * math.sin(a)
        ry = px * math.sin(a) + py * math.cos(a)
        dx, dy = rx, -ry
        if self.mirror == "x":     # flip top/bottom
            dy = -dy
        elif self.mirror == "y":   # flip left/right
            dx = -dx
        return (snap(self.x + dx, 0.01), snap(self.y + dy, 0.01))

    def _find(self, key):
        """A pin by number (also any member of a stacked "[a,b]" number) or
        by unique name."""
        key = str(key)
        hits = [p for p in self.pins if p["number"] == key or
                (p["number"].startswith("[") and key in re.findall(r"\d+", p["number"]))]
        if not hits:
            hits = [p for p in self.pins if p["name"] == key]
        if len(hits) != 1:
            raise KeyError(f"{self.ref}: pin {key!r} -> {len(hits)} matches")
        return hits[0]

    def pin(self, key):
        """Pin end point by number or by (unique) name."""
        p = self._find(key)
        return self._xf(p["x"], p["y"])

    def pin_dir(self, key):
        """Unit vector pointing *away* from the body at this pin's end."""
        p = self._find(key)
        a = math.radians(p["angle"])   # direction from end toward body, lib coords
        dx, dy = -math.cos(a), -math.sin(a)
        ex, ey = self._xf(p["x"] + dx, p["y"] + dy)
        sx, sy = self._xf(p["x"], p["y"])
        return (round(ex - sx), round(ey - sy))

    def move_pin_to(self, key, target):
        """Shift the whole part so that pin `key` lands exactly on `target`."""
        px, py = self.pin(key)
        # keep the symbol origin on the 50 mil grid: pins then stay on grid too
        self.x = snap(self.x + snap(target[0]) - px)
        self.y = snap(self.y + snap(target[1]) - py)
        return self

    def place_prop(self, name, dx, dy, justify=None, rot=0):
        self.prop_pos[name] = (dx, dy, justify, rot)

    def sexpr(self, project, root_uuid):
        def prop(name, value, dx, dy, hide=False, justify=None, rot=0):
            # KiCad draws a field whose net angle (symbol + field) is 180 as
            # upright text with left/right justification swapped; undo that
            # so "left" always means text runs rightward from the anchor.
            if justify and (self.rot + rot) % 360 == 180:
                justify = {"left": "right", "right": "left"}.get(justify, justify)
            j = f" (justify {justify})" if justify else ""
            h = " (hide yes)" if hide else ""
            return (f'(property "{name}" "{value}" (at {snap(self.x + dx, 0.01)} {snap(self.y + dy, 0.01)} {rot}){h} '
                    f'(effects (font (size 1.27 1.27)){j}))')
        # KiCad draws fields relative to the symbol's rotation; compensate so
        # text on 90/270-degree parts still reads horizontally.
        frot = 90 if self.rot in (90, 270) else 0
        rdx, rdy, rj, rr = self.prop_pos.get("Reference", (0, -3.81, None, frot))
        vdx, vdy, vj, vr = self.prop_pos.get("Value", (0, 3.81, None, frot))
        rr = frot if rr == 0 else rr
        vr = frot if vr == 0 else vr
        props = [prop("Reference", self.ref, rdx, rdy, hide=self.ref.startswith("#"), justify=rj, rot=rr),
                 prop("Value", self.value, vdx, vdy, hide=self.hide_value, justify=vj, rot=vr),
                 prop("Footprint", self.footprint or "", 0, 0, hide=True),
                 prop("Datasheet", "", 0, 0, hide=True)]
        for k, v in self.fields.items():
            props.append(prop(k, v, 0, 0, hide=True))
        mirror = f" (mirror {self.mirror})" if self.mirror else ""
        seen = []
        pin_lines = []
        for p in self.pins:
            for n in (re.findall(r"\d+", p["number"]) if p["number"].startswith("[") else [p["number"]]):
                if n not in seen:
                    seen.append(n)
                    pin_lines.append(f'(pin "{n}" (uuid "{uid()}"))')
        return (f'(symbol (lib_id "{self.lib_id}") (at {self.x} {self.y} {self.rot}){mirror} (unit {self.unit}) '
                f'(exclude_from_sim no) (in_bom {"yes" if self.in_bom and not self.ref.startswith("#") else "no"}) (on_board yes) '
                f'(dnp {"yes" if self.dnp else "no"}) (uuid "{self.uuid}") '
                + " ".join(props) + " " + " ".join(pin_lines) +
                f' (instances (project "{project}" (path "/{root_uuid}" (reference "{self.ref}") (unit {self.unit})))))')


COLORS = {
    # nets grouped by purpose (wire + label colour)
    "power12": (200, 60, 30), "power5": (200, 110, 0), "power3": (170, 130, 0),
    "i2c": (40, 110, 200), "i2s": (140, 60, 190), "spk": (0, 140, 110),
    "ctl": (90, 90, 160), "swc": (190, 60, 120), "fan": (60, 140, 60), "misc": (80, 80, 80),
}


class Schematic:
    def __init__(self, project, title, paper="A2"):
        self.project, self.title, self.paper = project, title, paper
        self.uuid = uid()
        self.lib_symbols = {}
        self.parts, self.items = [], []
        self._pwr = 0
        self._refs = set()

    def use_symbol(self, lib_id):
        if lib_id not in self.lib_symbols:
            block = symbol_block(lib_id)
            name = lib_id.split(":")[1]
            self.lib_symbols[lib_id] = block.replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)
        return self.lib_symbols[lib_id]

    def part(self, lib_id, ref, value, at, **kw):
        assert ref not in self._refs, f"duplicate ref {ref}"
        self._refs.add(ref)
        p = Part(self, lib_id, ref, value, at, **kw)
        self.parts.append(p)
        return p

    # -- connectivity ------------------------------------------------------
    def wire(self, *pts, color=None):
        pts = [(snap(x), snap(y)) for x, y in pts]
        for a, b in zip(pts, pts[1:]):
            if a == b:
                continue
            c = f" (color {color[0]} {color[1]} {color[2]} 1)" if color else ""
            self.items.append(f'(wire (pts (xy {a[0]} {a[1]}) (xy {b[0]} {b[1]})) '
                              f'(stroke (width 0) (type solid){c}) (uuid "{uid()}"))')

    def route(self, a, b, color=None, horizontal_first=True):
        """Orthogonal two-segment wire from a to b."""
        if a[0] == b[0] or a[1] == b[1]:
            self.wire(a, b, color=color)
        elif horizontal_first:
            self.wire(a, (b[0], a[1]), b, color=color)
        else:
            self.wire(a, (a[0], b[1]), b, color=color)

    def junction(self, pt):
        self.items.append(f'(junction (at {snap(pt[0])} {snap(pt[1])}) (diameter 0) '
                          f'(color 0 0 0 0) (uuid "{uid()}"))')

    def no_connect(self, pt):
        self.items.append(f'(no_connect (at {snap(pt[0])} {snap(pt[1])}) (uuid "{uid()}"))')

    def label(self, pt, net, direction, color=None, stub=2.54):
        """Net label at the end of a short stub leaving `pt` in `direction`
        ((1,0) right, (-1,0) left, (0,1) down, (0,-1) up)."""
        dx, dy = direction
        pt = (snap(pt[0]), snap(pt[1]))
        end = (snap(pt[0] + dx * stub), snap(pt[1] + dy * stub))
        if stub:
            self.wire(pt, end, color=color)
        angle = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(dx, dy)]
        just = {0: "left bottom", 180: "right bottom", 90: "left bottom", 270: "right bottom"}[angle]
        col = f" (color {color[0]} {color[1]} {color[2]} 1)" if color else ""
        self.items.append(f'(label "{net}" (at {end[0]} {end[1]} {angle}) '
                          f'(effects (font (size 1.27 1.27){col}) (justify {just})) (uuid "{uid()}"))')
        return end

    def power(self, pt, net, kind=None):
        """Power symbol whose connection point is `pt`. GND always points down,
        positive rails always point up (skill convention)."""
        self._pwr += 1
        if kind is None:
            kind = "GND" if net in ("GND", "GNDA") or net.startswith("GND") else "VDD"
        lib_id = f"power:{kind}"
        ref = f"#PWR{self._pwr:03d}"
        p = Part(self, lib_id, ref, net, pt)
        # value text above (supply) / below (ground)
        if kind == "GND":
            p.place_prop("Value", 0, 3.81)
        else:
            p.place_prop("Value", 0, -3.81)
        p.place_prop("Reference", 0, 5, None)
        self.parts.append(p)
        return p

    def pwr_flag(self, pt):
        self._pwr += 1
        p = Part(self, "power:PWR_FLAG", f"#FLG{self._pwr:03d}", "PWR_FLAG", pt)
        p.hide_value = True
        self.parts.append(p)

    # -- annotation --------------------------------------------------------
    def box(self, x1, y1, x2, y2, title, color):
        r, g, b = color
        self.items.append(
            f'(rectangle (start {x1} {y1}) (end {x2} {y2}) (stroke (width 0.3) (type dash) (color {r} {g} {b} 1)) '
            f'(fill (type color) (color {r} {g} {b} 0.04)) (uuid "{uid()}"))')
        self.text(x1 + 2.54, y1 + 3.81, title, size=2.54, bold=True, color=color)

    def text(self, x, y, s, size=1.27, bold=False, color=None, justify="left bottom"):
        b = " (bold yes)" if bold else ""
        c = f" (color {color[0]} {color[1]} {color[2]} 1)" if color else ""
        s = s.replace('"', '\\"').replace("\n", "\\n")
        self.items.append(f'(text "{s}" (exclude_from_sim no) (at {x} {y} 0) '
                          f'(effects (font (size {size} {size}){b}{c}) (justify {justify})) (uuid "{uid()}"))')

    # -- output ------------------------------------------------------------
    def write(self, path, date="2026-09-22", rev="0.1"):
        libs = "\n".join(self.lib_symbols.values())
        parts = "\n".join(p.sexpr(self.project, self.uuid) for p in self.parts)
        items = "\n".join(self.items)
        text = (f'(kicad_sch (version 20250610) (generator "eeschema") (generator_version "10.0") '
                f'(uuid "{self.uuid}") (paper "{self.paper}") '
                f'(title_block (title "{self.title}") (date "{date}") (rev "{rev}")) '
                f'(lib_symbols\n{libs}\n)\n{parts}\n{items}\n'
                f'(sheet_instances (path "/" (page "1"))) (embedded_fonts no))\n')
        with open(path, "w") as f:
            f.write(text)
