"""Equalizer: 7 bands on the launcher's Equalizer view, run by PulseAudio.

carrier.pa (launcher/board/system) puts a module-ladspa-sink "carrier_eq"
with swh-plugins' 15-band mbeq in front of the carrier board's sink and
makes it the default, so CarPlay and everything else goes through it. The
gains are changed live over PulseAudio's D-Bus interface
(module-dbus-protocol, python3-dbus), without a gap in the audio.

The 7 slider bands are spread over mbeq's 15 by interpolating in log
frequency. Boosts would clip at full volume, so every band is lowered by
the largest boost (headroom): the shape is kept, the loudest band sits at
0 dB.
"""
import json
import math
import os

BANDS = [60, 150, 400, 1000, 2500, 6000, 14000]          # Hz, the sliders
MBEQ = [50, 100, 156, 220, 311, 440, 622, 880, 1250, 1750, 2500, 3500, 5000, 10000, 20000]
MAX_DB = 12.0
SINK = "carrier_eq"
PRESETS = {
    "Flat": [0, 0, 0, 0, 0, 0, 0],
    "Bass": [6, 4, 1, 0, 0, 0, 0],
    "Vocal": [-2, -1, 1, 3, 3, 1, 0],
    "Treble": [0, 0, 0, 0, 2, 4, 5],
    "Loudness": [5, 3, 0, -1, 0, 2, 4],
}


def clamp(gains):
    g = [max(-MAX_DB, min(MAX_DB, float(x))) for x in gains][:len(BANDS)]
    return g + [0.0] * (len(BANDS) - len(g))


def to_mbeq(gains):
    """Slider gains (dB) to mbeq's 15 controls, with the headroom offset."""
    lb = [math.log(f) for f in BANDS]
    out = []
    for f in MBEQ:
        x = math.log(f)
        if x <= lb[0]:
            out.append(gains[0])
        elif x >= lb[-1]:
            out.append(gains[-1])
        else:
            i = next(k for k in range(len(lb) - 1) if lb[k] <= x <= lb[k + 1])
            t = (x - lb[i]) / (lb[i + 1] - lb[i])
            out.append(gains[i] + t * (gains[i + 1] - gains[i]))
    head = max(0.0, max(out))
    return [round(v - head, 2) for v in out]


def _pulse():
    """The ladspa sink's D-Bus object, or None (no python3-dbus, no
    module-dbus-protocol, or the EQ sink isn't loaded)."""
    try:
        import dbus
    except ImportError:
        return None, None
    path = f"/run/user/{os.getuid()}/pulse/dbus-socket"
    try:
        conn = dbus.connection.Connection(f"unix:path={path}")
        core = conn.get_object(object_path="/org/pulseaudio/core1")
        sink = core.GetSinkByName(SINK, dbus_interface="org.PulseAudio.Core1")
        return dbus, conn.get_object(object_path=sink)
    except Exception:
        return None, None


def available():
    return _pulse()[1] is not None


def apply(gains):
    """Set the EQ live. True when PulseAudio took it."""
    dbus, sink = _pulse()
    if sink is None:
        return False
    values = to_mbeq(clamp(gains))
    try:
        sink.Set("org.PulseAudio.Ext.Ladspa1", "AlgorithmParameters",
                 dbus.Struct((dbus.Array(values, signature="d"),
                              dbus.Array([False] * len(values), signature="b"))),
                 dbus_interface="org.freedesktop.DBus.Properties")
        return True
    except Exception:
        return False


def load(path):
    try:
        with open(path) as f:
            d = json.load(f)
        return {"gains": clamp(d.get("gains", [])), "preset": d.get("preset")}
    except (OSError, ValueError):
        return {"gains": [0.0] * len(BANDS), "preset": "Flat"}
