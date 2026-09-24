"""Key, headlights and reverse inputs, and the key-off shutdown.

All three inputs come from 12 V through an NPN inverter, so the Pi sees
them active low. Power hold: config.txt raises PI_HOLD (GPIO26) at boot and
gpio-poweroff drops it when the Pi halts; this module only decides when to
halt.
"""
import time

KEY_OFF_DELAY = 8.0        # s of ACC off before shutting down: rides out cranking
LIGHTS_WINDOW = 1.0        # s over which the headlight input is averaged
LIGHTS_ON_FRACTION = 0.2   # dash dimmers are PWM: on if low >20 % of the window


class KeyWatcher:
    """on_shutdown() fires once ACC has been off for KEY_OFF_DELAY; a key
    turned back on before then cancels it."""

    def __init__(self, on_shutdown, clock=time.monotonic):
        self.on_shutdown, self.clock = on_shutdown, clock
        self.off_since = None
        self.fired = False

    def update(self, acc_on):
        now = self.clock()
        if acc_on:
            self.off_since = None
            return None
        if self.off_since is None:
            self.off_since = now
        left = KEY_OFF_DELAY - (now - self.off_since)
        if left <= 0 and not self.fired:
            self.fired = True
            self.on_shutdown()
        return max(left, 0.0)


class Averager:
    """Fraction of recent samples that were active, for PWM-dimmed inputs."""

    def __init__(self, window=LIGHTS_WINDOW, clock=time.monotonic):
        self.window, self.clock = window, clock
        self.samples = []

    def feed(self, active):
        now = self.clock()
        self.samples.append((now, bool(active)))
        self.samples = [s for s in self.samples if now - s[0] <= self.window]
        return sum(a for _, a in self.samples) / len(self.samples)


class Latched:
    """Debounced boolean: changes only after `hold` s in the new state."""

    def __init__(self, hold, clock=time.monotonic, value=False):
        self.hold, self.clock, self.value = hold, clock, value
        self.since = None

    def update(self, raw):
        now = self.clock()
        if raw == self.value:
            self.since = None
        elif self.since is None:
            self.since = now
        elif now - self.since >= self.hold:
            self.value, self.since = raw, None
            return True                                # changed
        return False
