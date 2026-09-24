"""Two Noctua NF-A4x10 5V PWM fans.

The board drives each fan's PWM input through a 2N7002 that pulls it low,
so the Pi's PWM duty is inverted: Pi 0 % = fan 100 %. With the Pi down the
gate pull-down leaves the fans at full speed. Tach is open collector,
2 pulses per revolution.
"""
import time

CURVE = [(45.0, 0.25), (55.0, 0.40), (65.0, 0.70), (72.0, 1.00)]   # (deg C, fan duty)


def fan_duty(temp_c, amp_warning=False):
    """Fan duty 0..1 from the hotter of CPU/board temperature."""
    if amp_warning:
        return 1.0
    if temp_c <= CURVE[0][0]:
        return CURVE[0][1]
    for (t0, d0), (t1, d1) in zip(CURVE, CURVE[1:]):
        if temp_c <= t1:
            return d0 + (d1 - d0) * (temp_c - t0) / (t1 - t0)
    return 1.0


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
