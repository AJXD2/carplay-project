#!/usr/bin/env python3
"""Generates the update chimes played by xsplash.py progress.

  update-chime.wav  played once when an update starts: three soft bell
                    tones climbing G5, C6, E6, about 1.1 s, peak -12 dBFS
  update-done.wav   played when it finishes: two quieter tones, G5 then C6,
                    about 0.8 s, peak -16 dBFS

48 kHz, 16-bit, stereo, because the car's audio runs at a fixed 48 kHz.
Each tone is a sine plus two quiet inharmonic partials (the "bell" part),
with a raised-cosine attack of 8 ms and an exponential decay, so there are
no clicks and nothing sharp. A short lead of silence lets the amplifier
board's output settle before the first tone. Stdlib only.

Usage: ./make_chime.py     (rewrites both files next to this script)
"""
import math
import struct
import wave
from pathlib import Path

RATE = 48000
LEAD = 0.05       # seconds of silence before the first tone
ATTACK = 0.008    # seconds to reach full level
# partial ratio, level, decay scale (higher partials die away sooner)
PARTIALS = ((1.0, 1.00, 1.0), (2.756, 0.10, 0.45), (5.404, 0.03, 0.25))


def tone(buf, start, freq, amp, decay, length):
    """Mix one bell-like tone into buf, starting at `start` seconds."""
    i0 = int(start * RATE)
    for n in range(int(length * RATE)):
        t = n / RATE
        env = min(1.0, t / ATTACK)
        env = 0.5 - 0.5 * math.cos(math.pi * env)  # raised cosine in
        # last 60 ms fade to exactly zero so the tail never ends on a step
        tail = min(1.0, (length - t) / 0.06)
        s = 0.0
        for ratio, level, scale in PARTIALS:
            s += level * math.exp(-t / (decay * scale)) * math.sin(2 * math.pi * freq * ratio * t)
        buf[i0 + n] += amp * env * tail * s


def write(path, notes, total, peak_db):
    buf = [0.0] * int(total * RATE)
    for start, freq, amp, decay, length in notes:
        tone(buf, LEAD + start, freq, amp, decay, length)
    top = max(abs(x) for x in buf)
    gain = 10 ** (peak_db / 20) / top
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        frames = bytearray()
        for x in buf:
            v = round(x * gain * 32767)
            frames += struct.pack("<hh", v, v)
        w.writeframes(bytes(frames))


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    G5, C6, E6 = 783.99, 1046.50, 1318.51
    # (start s, Hz, relative level, decay time constant s, length s)
    write(here / "update-chime.wav",
          [(0.00, G5, 0.80, 0.28, 0.85),
           (0.17, C6, 0.90, 0.30, 0.85),
           (0.34, E6, 1.00, 0.34, 0.70)],
          total=LEAD + 1.05, peak_db=-12)
    write(here / "update-done.wav",
          [(0.00, G5, 0.75, 0.22, 0.65),
           (0.20, C6, 1.00, 0.28, 0.65)],
          total=LEAD + 0.85, peak_db=-16)
