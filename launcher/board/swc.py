"""Steering-wheel buttons: Toyota resistor ladders read by an ADS1115.

Each ladder wire is pulled up to 3.3 V through 1k on the board, so a button
shorts it to ground through its own resistor and the ADC sees a fixed
voltage per button. Nothing is hard-coded: learn mode records what each
button actually reads, so any wheel (and any wiring order) works.
"""
import logging
import statistics
import time

log = logging.getLogger("swc")

ADDR = 0x48                      # ADDR pin to GND
REG_CONV, REG_CFG = 0x00, 0x01
FSR = 4.096                      # PGA +/-4.096 V: covers 0..3.3 V
IDLE_V = 3.0                     # above this the wire is released
MIN_SEP_V = 0.12                 # learned buttons must differ by at least this
MATCH_V = 0.06                   # a reading within this of a learned value is that button
STABLE_SAMPLES = 3               # ~3 x 8 ms at 250 SPS per channel before a press counts
REPEAT_AFTER, REPEAT_EVERY = 0.45, 0.15

# The buttons learn mode asks for, in order. Wheels without one can skip it.
LEARN_ORDER = ["vol_up", "vol_down", "seek_up", "seek_down", "mode", "voice", "phone_on", "phone_off"]
REPEATS = {"vol_up", "vol_down"}


class ADS1115:
    def __init__(self, bus, addr=ADDR, sleep=time.sleep):
        self.bus, self.addr, self.sleep = bus, addr, sleep

    def read(self, ch):
        """Single-shot, single-ended AINch, 250 SPS. Returns volts."""
        mux = 0b100 + ch                              # AINx vs GND
        cfg = (1 << 15) | (mux << 12) | (0b001 << 9) | (1 << 8) | (0b101 << 5) | 0b11
        self.bus.write(self.addr, REG_CFG, [cfg >> 8, cfg & 0xFF])
        for _ in range(10):
            self.sleep(0.0045)
            hi, lo = self.bus.read(self.addr, REG_CFG, 2)
            if hi & 0x80:                             # OS = 1: conversion done
                break
        hi, lo = self.bus.read(self.addr, REG_CONV, 2)
        raw = (hi << 8) | lo
        if raw & 0x8000:
            raw -= 1 << 16
        return raw * FSR / 32768.0


class Buttons:
    """Turns ADC samples into button presses.

    buttons: {name: {"ch": 0|1, "v": volts}} from learn mode.
    on_press(name, repeat) is called for each press and for held repeats.
    """

    def __init__(self, buttons, on_press, clock=time.monotonic):
        self.buttons = buttons
        self.on_press, self.clock = on_press, clock
        self.cand = [None, None]
        self.count = [0, 0]
        self.held = [None, None]
        self.next_repeat = [0.0, 0.0]

    def classify(self, ch, v):
        if v > IDLE_V:
            return None
        best, dist = None, MATCH_V
        for name, b in self.buttons.items():
            if b["ch"] == ch and abs(b["v"] - v) <= dist:
                best, dist = name, abs(b["v"] - v)
        return best or "?"

    def feed(self, ch, v):
        name = self.classify(ch, v)
        if name == self.cand[ch]:
            self.count[ch] += 1
        else:
            self.cand[ch], self.count[ch] = name, 1
        now = self.clock()
        if self.count[ch] == STABLE_SAMPLES and name != self.held[ch]:
            self.held[ch] = name
            if name not in (None, "?"):
                self.on_press(name, False)
                self.next_repeat[ch] = now + REPEAT_AFTER
        elif name is None and self.count[ch] >= STABLE_SAMPLES:
            self.held[ch] = None
        elif (self.held[ch] in REPEATS and name == self.held[ch] and now >= self.next_repeat[ch]):
            self.on_press(name, True)
            self.next_repeat[ch] = now + REPEAT_EVERY


class Learner:
    """Learn mode: ask for each button in LEARN_ORDER, record where it sits.

    Feed samples in; poll .state for the UI ({"step", "prompt", "done",
    "error", "learned"}). A button must be held steady for ~0.3 s; the
    median of that window is stored.
    """

    HOLD_SAMPLES = 36                                 # ~0.3 s at 2 x 250 SPS, both channels

    def __init__(self, order=LEARN_ORDER):
        self.order = list(order)
        self.learned = {}
        self.i = 0
        self.window = []
        self.wait_release = None                      # channel that must go idle first
        self.error = None

    @property
    def done(self):
        return self.i >= len(self.order)

    @property
    def state(self):
        return {"step": self.i, "total": len(self.order), "done": self.done,
                "prompt": None if self.done else self.order[self.i],
                "error": self.error, "learned": dict(self.learned)}

    def skip(self):
        if not self.done:
            self.i += 1
            self.window, self.error = [], None

    def feed(self, ch, v):
        if self.done:
            return
        if self.wait_release is not None:
            if ch == self.wait_release and v > IDLE_V:
                self.wait_release = None
            return
        if v > IDLE_V:
            self.window = [s for s in self.window if s[0] != ch]
            return
        self.window.append((ch, v))
        mine = [s for s in self.window if s[0] == ch]
        if len(mine) < self.HOLD_SAMPLES // 2:
            return
        vals = [s[1] for s in mine[-self.HOLD_SAMPLES // 2:]]
        if max(vals) - min(vals) > MATCH_V:
            return                                    # still moving (bounce or sliding contact)
        med = statistics.median(vals)
        clash = next((n for n, b in self.learned.items()
                      if b["ch"] == ch and abs(b["v"] - med) < MIN_SEP_V), None)
        name = self.order[self.i]
        self.window, self.wait_release = [], ch
        if clash:
            self.error = f"{name} reads the same as {clash}; try again or skip"
            log.warning(self.error)
            return
        self.learned[name] = {"ch": ch, "v": round(med, 4)}
        self.error = None
        self.i += 1
        log.info("learned %s: ch%d %.3f V", name, ch, med)
