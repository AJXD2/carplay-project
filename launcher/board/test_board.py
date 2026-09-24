"""Tests for the carrier board services, on simulated hardware.

    cd launcher && python3 -m unittest board.test_board -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from board import carrierd, fans, hw, power, sim, swc, tas6424  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class GpioAbi(unittest.TestCase):
    """The packed request must match what the kernel's own struct holds."""

    C = r'''
#include <stdio.h>
#include <string.h>
#include <linux/gpio.h>
int main(void) {
    struct gpio_v2_line_request r; memset(&r, 0, sizeof r);
    r.offsets[0] = 23; strcpy(r.consumer, "carrierd");
    r.config.flags = GPIO_V2_LINE_FLAG_OUTPUT | GPIO_V2_LINE_FLAG_BIAS_PULL_DOWN;
    r.config.num_attrs = 2;
    r.config.attrs[0].attr.id = GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES;
    r.config.attrs[0].attr.values = 1; r.config.attrs[0].mask = 1;
    r.config.attrs[1].attr.id = GPIO_V2_LINE_ATTR_ID_DEBOUNCE;
    r.config.attrs[1].attr.debounce_period_us = 5000; r.config.attrs[1].mask = 1;
    r.num_lines = 1;
    fwrite(&r, sizeof r, 1, stdout);
    return 0;
}'''

    @unittest.skipUnless(shutil.which("cc") and os.path.exists("/usr/include/linux/gpio.h"), "no C toolchain")
    def test_line_request_matches_kernel_struct(self):
        with tempfile.TemporaryDirectory() as d:
            src, exe = os.path.join(d, "r.c"), os.path.join(d, "r")
            with open(src, "w") as f:
                f.write(self.C)
            subprocess.run(["cc", src, "-o", exe], check=True)
            want = subprocess.run([exe], capture_output=True, check=True).stdout
        got = hw.line_request(23, "out", pull="down", value=1, debounce_us=5000)
        self.assertEqual(len(want), 592)
        self.assertEqual(bytes(got), want)


class AmpTests(unittest.TestCase):
    def setUp(self):
        self.dev = sim.SimTAS6424()
        self.bus = hw.SimI2CBus({tas6424.ADDR: self.dev})
        self.pins = {n: hw.SimGpioLine(0, "out") for n in ("standby", "mute")}
        self.fault = hw.SimGpioLine(0, "in", pull="up")
        self.warn = hw.SimGpioLine(0, "in", pull="up")
        self.amp = tas6424.Amp(self.bus, self.pins["standby"], self.pins["mute"], self.fault, self.warn,
                               sleep=lambda s: None)

    def test_volume_register(self):
        self.assertEqual(tas6424.db_to_reg(0), 0xCF)
        self.assertEqual(tas6424.db_to_reg(24), 0xFF)
        self.assertEqual(tas6424.db_to_reg(-6), 0xCF - 12)
        self.assertEqual(tas6424.db_to_reg(-100), 0x00)
        self.assertEqual(tas6424.db_to_reg(None), 0x00)

    def test_fader(self):
        g = tas6424.fader_gains(0, 0)
        self.assertEqual(set(g.values()), {0.0})
        g = tas6424.fader_gains(1.0, 0)                       # front only
        self.assertEqual((g["FL"], g["FR"], g["RL"], g["RR"]), (0.0, 0.0, None, None))
        g = tas6424.fader_gains(-0.5, 0.5)                    # toward rear, toward right
        self.assertEqual(g["RR"], 0.0)
        self.assertAlmostEqual(g["FL"], -40.0)
        self.assertAlmostEqual(g["FR"], -20.0)

    def test_start_sequence(self):
        self.assertTrue(self.amp.start())
        regs = [r for r, _ in self.dev.writes]
        self.assertLess(regs.index(tas6424.MISC5), regs.index(tas6424.CH_STATE),
                        "PHASE_SEL must be set before leaving Hi-Z/standby")
        self.assertEqual(self.dev.regs[tas6424.MISC5] & 0x20, 0x20)
        self.assertEqual(self.dev.regs[tas6424.SAP], 0x44)    # 48 kHz, I2S
        self.assertEqual(self.dev.regs[tas6424.MISC1] & 0x03, 0b01)
        self.assertEqual(self.dev.regs[tas6424.CH_STATE], tas6424.PLAY)
        self.assertEqual((self.pins["standby"].value, self.pins["mute"].value), (1, 1))

    def test_fault_blocks_play(self):
        self.dev.inject(tas6424.GLOBAL_FAULTS1, 0x10, sticky=True)   # clock missing
        self.assertFalse(self.amp.start())
        self.assertEqual(self.dev.regs[tas6424.CH_STATE], tas6424.HIZ)
        self.assertEqual(self.pins["mute"].value, 0)
        self.assertIn("clock", self.amp.last_fault)

    def test_stop_is_quiet(self):
        self.amp.start()
        self.amp.stop()
        self.assertEqual((self.pins["standby"].value, self.pins["mute"].value), (0, 0))
        self.assertEqual(self.dev.regs[tas6424.CH_STATE], tas6424.HIZ)

    def test_duck_and_thermal(self):
        self.amp.start()
        self.amp.set_duck(-12)
        self.assertEqual(self.dev.regs[tas6424.VOL_BASE], 0xCF - 24)
        self.amp.set_thermal_cut(-6)
        self.assertEqual(self.dev.regs[tas6424.VOL_BASE], 0xCF - 36)


class WheelTests(unittest.TestCase):
    def test_adc_scaling(self):
        dev = sim.SimADS1115()
        adc = swc.ADS1115(hw.SimI2CBus({swc.ADDR: dev}), sleep=lambda s: None)
        dev.volts = [0.82, 3.3]
        self.assertAlmostEqual(adc.read(0), 0.82, places=3)
        self.assertAlmostEqual(adc.read(1), 3.3, places=3)

    def test_press_and_repeat(self):
        clock = Clock()
        got = []
        b = swc.Buttons({"vol_up": {"ch": 0, "v": 0.30}, "seek_up": {"ch": 0, "v": 0.00},
                         "mode": {"ch": 1, "v": 0.02}}, lambda n, r: got.append((n, r)), clock)
        for _ in range(3):
            b.feed(0, 3.3)
        for _ in range(3):
            b.feed(0, 0.31)                                   # vol_up pressed
        self.assertEqual(got, [("vol_up", False)])
        clock.t += 0.5
        b.feed(0, 0.30)
        self.assertEqual(got[-1], ("vol_up", True))           # held: repeats
        for _ in range(3):
            b.feed(0, 3.3)                                    # released
        for _ in range(3):
            b.feed(0, 0.01)
        self.assertEqual(got[-1], ("seek_up", False))
        for _ in range(3):
            b.feed(1, 0.03)
        self.assertEqual(got[-1], ("mode", False))
        n = len(got)
        for _ in range(3):
            b.feed(0, 1.7)                                    # nothing learned there
        self.assertEqual(len(got), n)

    def test_learn_mode(self):
        L = swc.Learner(["vol_up", "vol_down", "mode"])

        def press(ch, v):
            for _ in range(L.HOLD_SAMPLES):
                L.feed(ch, v)
            for _ in range(3):
                L.feed(ch, 3.3)

        press(0, 0.30)
        self.assertEqual(L.state["prompt"], "vol_down")
        press(0, 0.33)                                        # too close to vol_up
        self.assertIn("same as vol_up", L.state["error"])
        self.assertEqual(L.state["prompt"], "vol_down")
        press(0, 2.50)
        press(1, 0.00)
        self.assertTrue(L.done)
        self.assertEqual(L.learned["vol_down"], {"ch": 0, "v": 2.5})
        self.assertEqual(L.learned["mode"]["ch"], 1)


class PowerTests(unittest.TestCase):
    def test_crank_does_not_shut_down(self):
        clock, fired = Clock(), []
        k = power.KeyWatcher(lambda: fired.append(1), clock)
        k.update(True)
        for _ in range(30):                                   # 3 s ACC dropout while cranking
            clock.t += 0.1
            k.update(False)
        k.update(True)
        self.assertEqual(fired, [])
        for _ in range(90):                                   # key off 9 s
            clock.t += 0.1
            k.update(False)
        self.assertEqual(fired, [1])

    def test_dimmer_pwm_counts_as_lights_on(self):
        clock = Clock()
        avg = power.Averager(clock=clock)
        for i in range(100):                                  # 30 % duty dash dimmer
            clock.t += 0.01
            f = avg.feed(i % 10 < 3)
        self.assertGreater(f, power.LIGHTS_ON_FRACTION)

    def test_latched(self):
        clock = Clock()
        latch = power.Latched(1.0, clock)
        self.assertFalse(latch.update(True))
        clock.t += 0.5
        self.assertFalse(latch.update(True))
        clock.t += 0.6
        self.assertTrue(latch.update(True))
        self.assertTrue(latch.value)


class FanTests(unittest.TestCase):
    def test_curve(self):
        self.assertEqual(fans.fan_duty(30), 0.25)
        self.assertAlmostEqual(fans.fan_duty(60), 0.55)
        self.assertEqual(fans.fan_duty(90), 1.0)
        self.assertEqual(fans.fan_duty(30, amp_warning=True), 1.0)

    def test_pwm_is_inverted(self):
        pwm = hw.SimPwm(0)
        fan = fans.Fan(pwm, hw.SimGpioLine(0, "edge", pull="up"))
        fan.set(0.25)
        self.assertAlmostEqual(pwm.fraction, 0.75)


class BoardTests(unittest.TestCase):
    """The whole daemon on simulated hardware."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = carrierd.CONFIG
        carrierd.CONFIG = os.path.join(self.tmp, "config.json")
        carrierd.launcher_post = lambda path, data: self.posts.append((path, data))
        self.posts, self.keys = [], []
        self.board = carrierd.Board(sim=True)
        self.board.send_key = self.keys.append
        self.board.amp.sleep = lambda s: None
        self.board.adc.sleep = lambda s: None

    def tearDown(self):
        carrierd.CONFIG = self.old
        shutil.rmtree(self.tmp)

    def test_amp_comes_up(self):
        self.board.tick()
        self.assertTrue(self.board.status["amp_playing"])

    def test_learn_then_use(self):
        adc = self.board.bus.devices[swc.ADDR]
        errors = []
        real = swc.log.warning
        swc.log.warning = lambda msg, *a: errors.append(msg % a if a else msg)
        self.addCleanup(setattr, swc.log, "warning", real)
        self.board.api("/learn/start", {})
        for name, (ch, v) in (("vol_up", (0, 0.30)), ("vol_down", (0, 2.5)), ("seek_up", (0, 0.0)),
                              ("seek_down", (0, 0.82)), ("mode", (1, 0.0))):
            adc.volts = [3.3, 3.3]
            adc.volts[ch] = v
            for _ in range(swc.Learner.HOLD_SAMPLES):
                self.board.sample_wheel()
            adc.volts = [3.3, 3.3]
            for _ in range(3):
                self.board.sample_wheel()
        for _ in range(3):                                    # this wheel has no voice/phone buttons
            self.board.api("/learn/skip", {})
        self.board.sample_wheel()
        self.assertIsNone(self.board.learner)
        self.assertNotIn("error", str(self.board.status))
        self.assertEqual(errors, [])
        self.assertEqual(set(self.board.cfg["buttons"]), {"vol_up", "vol_down", "seek_up", "seek_down", "mode"})
        self.assertTrue(os.path.exists(carrierd.CONFIG))
        adc.volts = [0.83, 3.3]                               # press seek_down
        for _ in range(4):
            self.board.sample_wheel()
        self.assertEqual(self.keys, ["n"])
        adc.volts = [0.31, 3.3]                               # press vol_up
        for _ in range(4):
            self.board.sample_wheel()
        self.assertIn(("/api/volume", {"delta": 4}), self.posts)

    def test_reverse_ducks(self):
        self.board.tick()
        clock = Clock()
        self.board.in_reverse = power.Latched(0.3, clock)
        self.board.reverse.drive(0)                           # active low: in reverse
        self.board.poll_inputs()
        clock.t += 0.4
        self.board.poll_inputs()
        dev = self.board.bus.devices[tas6424.ADDR]
        self.assertEqual(dev.regs[tas6424.VOL_BASE], 0xCF - 24)


if __name__ == "__main__":
    unittest.main()
