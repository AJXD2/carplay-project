"""Bench tool for the carrier board's TAS6424 (BRINGUP.md stage 7). Run on the
Pi as root with carrierd stopped:

    python3 -m board.amptest diag            DC load diagnostics, all channels
    python3 -m board.amptest tone FL [dB]    one channel, its own tone, 3 s
    python3 -m board.amptest sweep [dB]      FL, FR, RL, RR in turn
    python3 -m board.amptest play WAV CH [dB]  a file (S32_LE, 48 kHz, stereo) on one channel
    python3 -m board.amptest off             Hi-Z, muted, standby

Each channel plays its own frequency (FL 440, FR 660, RL 880, RR 1100 Hz) so
a recording shows which channel was heard. Volume defaults to -40 dB and is
capped at -30 dB: full scale is 15 V peak, which would cook headphones.
"""
import math
import os
import struct
import subprocess
import sys
import tempfile
import time

from . import hw
from .tas6424 import (ADDR, MODE_CTRL, MISC1, MISC2, SAP, CH_STATE, VOL_BASE,
                      CH_FAULTS, GLOBAL_FAULTS1, GLOBAL_FAULTS2, WARNINGS,
                      MISC3, MISC5, MISC1_VALUE, MISC2_VALUE, SAP_VALUE,
                      MISC5_VALUE, HIZ, CHANNELS, db_to_reg)

STANDBY_GPIO, MUTE_GPIO = 22, 23           # both active low
DC_DIAG_CTRL1 = 0x09                       # bit 0: skip the automatic DC diagnostics
DC_DIAG_REPORT = (0x0C, 0x0D)              # CH1/CH2, CH3/CH4
CH_STATE_REPORT = 0x0F
TONES = {"FL": 440, "FR": 660, "RL": 880, "RR": 1100}
MAX_DB = -30.0


def playback_device():
    """The Carrier card's playback PCM (its number depends on link order)."""
    import glob
    p = glob.glob("/proc/asound/Carrier/pcm*p")
    return f"hw:Carrier,{p[0].rsplit('pcm', 1)[1][:-1]}" if p else "hw:Carrier,0"


def pin(gpio, high):
    subprocess.run(["pinctrl", "set", str(gpio), "op", "dh" if high else "dl"], check=True)


def state_byte(states):
    """states: channel name -> 0 PLAY, 1 Hi-Z, 2 MUTE, 3 DC diag (2 bits each, CH1 in bits 7:6)."""
    b = 0
    for i, ch in enumerate(CHANNELS):
        b |= states.get(ch, 1) << (6 - 2 * i)
    return b


def init(bus):
    """tas6424.Amp.start() order up to the channel state, with every channel muted."""
    pin(MUTE_GPIO, False)
    pin(STANDBY_GPIO, False)
    time.sleep(0.02)
    pin(STANDBY_GPIO, True)
    time.sleep(0.01)
    w = bus.write_u8
    w(ADDR, MODE_CTRL, 0x80)
    time.sleep(0.005)
    for reg, val in ((MISC5, MISC5_VALUE), (MISC1, MISC1_VALUE), (MISC2, MISC2_VALUE), (SAP, SAP_VALUE)):
        w(ADDR, reg, val)
    for i in range(4):
        w(ADDR, VOL_BASE + i, 0x00)
    w(ADDR, MISC3, 0x80)                    # clear faults
    time.sleep(0.01)


def faults(bus):
    r = bus.read_u8
    return {name: r(ADDR, reg) for name, reg in (
        ("channel", CH_FAULTS), ("global1", GLOBAL_FAULTS1), ("global2", GLOBAL_FAULTS2),
        ("warnings", WARNINGS), ("state", CH_STATE_REPORT))}


def diag(bus):
    init(bus)
    bus.write_u8(ADDR, CH_STATE, state_byte({ch: 3 for ch in CHANNELS}))
    time.sleep(1.5)                          # 230 ms typical; at 0.5 s CH4 was not done yet
    rep = [bus.read_u8(ADDR, reg) for reg in DC_DIAG_REPORT]
    bus.write_u8(ADDR, CH_STATE, HIZ)
    for i, ch in enumerate(CHANNELS):
        bits = (rep[i // 2] >> (4 if i % 2 == 0 else 0)) & 0xF
        found = [n for n, b in (("short to GND", 8), ("short to supply", 4),
                                ("open load", 2), ("shorted load", 1)) if bits & b]
        print(f"{ch} (amp CH{i + 1}): {', '.join(found) or 'load OK (under ~40 ohm)'}")
    print("faults:", {k: f"0x{v:02x}" for k, v in faults(bus).items()})


def tone_file(freq, seconds=3.0, rate=48000, level=0.5):
    """Same tone on both I2S slots, S32_LE stereo WAV."""
    n = int(seconds * rate)
    amp = int(level * 0x7FFFFFFF)
    data = bytearray()
    for i in range(n):
        s = int(amp * math.sin(2 * math.pi * freq * i / rate))
        data += struct.pack("<ii", s, s)
    hdr = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(data), b"WAVE", b"fmt ", 16, 1, 2,
                      rate, rate * 8, 8, 32, b"data", len(data))
    fd, path = tempfile.mkstemp(suffix=".wav")
    with os.fdopen(fd, "wb") as f:
        f.write(hdr + data)
    return path


def play(bus, ch, db, wav=None):
    db = min(db, MAX_DB)
    i = CHANNELS.index(ch)
    path = wav or tone_file(TONES[ch])
    try:
        for j in range(4):
            bus.write_u8(ADDR, VOL_BASE + j, db_to_reg(db) if j == i else 0x00)
        bus.write_u8(ADDR, CH_STATE, state_byte({ch: 0}))
        time.sleep(0.05)
        pin(MUTE_GPIO, True)
        what = os.path.basename(wav) if wav else f"{TONES[ch]} Hz"
        print(f"{time.strftime('%T')} {ch} (amp CH{i + 1}) {what} at {db:.0f} dB", flush=True)
        subprocess.run(["aplay", "-q", "-D", playback_device(), path], check=True)
        print("  faults:", {k: f"0x{v:02x}" for k, v in faults(bus).items()}, flush=True)
    finally:
        pin(MUTE_GPIO, False)
        bus.write_u8(ADDR, CH_STATE, HIZ)
        if not wav:
            os.unlink(path)


def off(bus):
    pin(MUTE_GPIO, False)
    try:
        bus.write_u8(ADDR, CH_STATE, HIZ)
    except OSError:
        pass
    pin(STANDBY_GPIO, False)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "diag"
    bus = hw.I2CBus(1)
    try:
        if cmd == "diag":
            diag(bus)
        elif cmd == "tone":
            init(bus)
            # Headphones read as an open load (over 40 to 70 ohm), and the
            # automatic diagnostics would hold the channel off. Run `diag`
            # first: it checks for shorts.
            bus.write_u8(ADDR, DC_DIAG_CTRL1, 0x01)
            play(bus, argv[2].upper(), float(argv[3]) if len(argv) > 3 else -40.0)
        elif cmd == "sweep":
            init(bus)
            bus.write_u8(ADDR, DC_DIAG_CTRL1, 0x01)     # as for tone
            for ch in ("FL", "FR", "RL", "RR"):
                play(bus, ch, float(argv[2]) if len(argv) > 2 else -40.0)
                time.sleep(1.0)
        elif cmd == "play":
            init(bus)
            bus.write_u8(ADDR, DC_DIAG_CTRL1, 0x01)     # as for tone
            play(bus, argv[3].upper(), float(argv[4]) if len(argv) > 4 else -40.0, wav=argv[2])
        elif cmd != "off":
            sys.exit(__doc__)
    finally:
        off(bus)


if __name__ == "__main__":
    main(sys.argv)
