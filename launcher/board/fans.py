"""Two Noctua NF-A4x10 5V PWM fans.

The board drives each fan's PWM input through a 2N7002 that pulls it low,
so the Pi's PWM duty is inverted: Pi 0 % = fan 100 %. With the Pi down the
gate pull-down leaves the fans at full speed. Tach is open collector,
2 pulses per revolution.
"""
import time

CURVE = [(45.0, 0.25), (55.0, 0.40), (65.0, 0.70), (72.0, 1.00)]   # SoC deg C -> duty
# The amp's heat is set by how loud it plays, which the SoC temperature
# doesn't see. PulseAudio's volume is cubic, so the amp's output power goes
# as (volume)^6: little below ~60 %, steep above. Its worst case (about 6 W
# in a 60 C dash) needs fan 1 at full speed with the stock heatsink
# (hardware/carrier/tools/heatsink_thermal.py).
VOLUME_CURVE = [(60.0, 0.25), (70.0, 0.40), (80.0, 0.60), (90.0, 0.80), (100.0, 1.00)]
# The DS3231 sits in the case: the air the heatsink and the Pi breathe.
DASH_CURVE = [(45.0, 0.25), (50.0, 0.50), (55.0, 0.75), (60.0, 1.00)]
MODES = ("auto", "max")


def _curve(points, x):
    if x is None or x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def fan_duty(cpu_c, amp_warning=False, mode="auto", volume=None, dash_c=None):
    """Fan duty 0..1. "max": always full speed. "auto": the highest of what
    the music volume, the air in the case and the SoC each need. The amp's
    overtemperature warning means full speed in either mode."""
    if amp_warning or mode == "max":
        return 1.0
    return max(_curve(CURVE, cpu_c), _curve(VOLUME_CURVE, volume), _curve(DASH_CURVE, dash_c))


def cpu_temp(path="/sys/class/thermal/thermal_zone0/temp"):
    try:
        with open(path) as f:
            return int(f.read()) / 1000.0
    except (OSError, ValueError):
        return 85.0                                    # unknown: assume hot


class Fan:
    def __init__(self, pwm, tach):
        self.pwm, self.tach = pwm, tach
        self.duty = None
        self.pulses = 0
        self.t0 = time.monotonic()
        self.rpm = 0

    def set(self, duty):
        if duty != self.duty:
            self.duty = duty
            self.pwm.duty(1.0 - duty)                  # FET inverts

    def poll_tach(self):
        """Count falling edges; update rpm about once a second."""
        self.pulses += sum(1 for _, rising in self.tach.events(0) if not rising)
        now = time.monotonic()
        if now - self.t0 >= 1.0:
            self.rpm = int(self.pulses / 2 / (now - self.t0) * 60)
            self.pulses, self.t0 = 0, now
        return self.rpm
