#!/usr/bin/env python3
"""carrierd: runs the carrier board (hardware/carrier).

  - brings the TAS6424 amp up once the audio clocks run, applies fader,
    watches FAULT/WARN, recovers latched faults, trims volume when hot
  - reads the steering-wheel ladders (ADS1115) and turns presses into
    CarPlay keys / launcher volume; learn mode maps a new wheel
  - key off for 8 s -> mute, standby, poweroff (gpio-poweroff then drops
    PI_HOLD and the board switches itself off)
  - headlights -> launcher night mode; reverse -> duck the music
  - fan curve from the SoC temperature, tach readback

Local JSON API on 127.0.0.1:8735 for the launcher UI:
  GET  /state
  POST /learn/start | /learn/skip | /learn/cancel
  POST /fader {"fader": -1..1, "balance": -1..1}
  POST /actions {"vol_up": ["volume", 4], ...}

  python3 -m board.carrierd            (from launcher/, on the Pi)
  python3 -m board.carrierd --sim      (desktop: simulated hardware)
"""
import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from board import fans, hw, power, swc, tas6424  # noqa: E402

log = logging.getLogger("carrierd")

CONFIG = os.path.expanduser("~/.config/carrierd/config.json")
LAUNCHER = "http://127.0.0.1:8734"
API_PORT = 8735

# BCM GPIO numbers (hardware/carrier/tools/gen_sch.py PI_GPIO)
GPIO = dict(acc=17, lights=27, reverse=7, amp_stby=22, amp_mute=23, amp_fault=24,
            amp_warn=25, adc_alert=6, fan1_tach=16, fan2_tach=4)
PWM_CH = dict(fan1=0, fan2=1)                         # GPIO12 / GPIO13

DEFAULT_ACTIONS = {
    "vol_up": ["volume", 4],
    "vol_down": ["volume", -4],
    "seek_up": ["key", "m"],                          # react-carplay: next = KeyM
    "seek_down": ["key", "n"],                        # prev = KeyN
    "mode": ["toggle_play"],                          # play = KeyP, pause = KeyO
    "voice": ["key", "h"],                            # home
}
DEFAULTS = {"buttons": {}, "actions": DEFAULT_ACTIONS, "fader": 0.0, "balance": 0.0,
            "reverse_duck_db": -12.0, "carplay_window_class": "react-carplay"}


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with open(CONFIG) as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg, sim=False):
    data = json.dumps(cfg, indent=2) + "\n"
    if sim:
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w") as f:
            f.write(data)
        return
    import persist
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    if not persist.write_through(CONFIG, data):
        log.error("could not persist %s", CONFIG)


def launcher_post(path, data):
    req = urllib.request.Request(LAUNCHER + path, json.dumps(data).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.load(r)
    except OSError as e:
        log.warning("launcher %s: %s", path, e)


class Board:
    def __init__(self, sim=False):
        self.sim = sim
        self.cfg = load_config()
        if sim:
            from board import sim as simdev
            self.bus = hw.SimI2CBus(simdev.devices())
            gpio = lambda n, mode, **kw: hw.SimGpioLine(n, mode, **kw)  # noqa: E731
            pwm = hw.SimPwm
        else:
            self.bus = hw.I2CBus(1)
            gpio = lambda n, mode, **kw: hw.GpioLine(n, mode, **kw)  # noqa: E731
            pwm = hw.Pwm
        # active-low inputs; the board pulls them up, the Pi's pull-up just agrees
        self.acc = gpio(GPIO["acc"], "in", pull="up")
        self.lights = gpio(GPIO["lights"], "in", pull="up")
        self.reverse = gpio(GPIO["reverse"], "in", pull="up")
        self.amp = tas6424.Amp(self.bus,
                               standby=gpio(GPIO["amp_stby"], "out", value=0),
                               mute=gpio(GPIO["amp_mute"], "out", value=0),
                               fault=gpio(GPIO["amp_fault"], "in", pull="up"),
                               warn=gpio(GPIO["amp_warn"], "in", pull="up"))
        self.adc = swc.ADS1115(self.bus)
        self.buttons = swc.Buttons(self.cfg["buttons"], self.on_button)
        self.learner = None
        self.fans = [fans.Fan(pwm(PWM_CH[f]), gpio(GPIO[f + "_tach"], "edge", pull="up"))
                     for f in ("fan1", "fan2")]
        self.key = power.KeyWatcher(self.shutdown)
        self.lights_on = power.Latched(1.0)
        self.lights_avg = power.Averager()
        self.in_reverse = power.Latched(0.3)
        self.playing_toggle = False
        self.status = {}
        self.amp_retry_at = 0.0
        self.amp_backoff = 2.0
        self.lock = threading.Lock()
        self.stop = threading.Event()

    # -- actions -----------------------------------------------------------
    def on_button(self, name, repeat):
        act = self.cfg["actions"].get(name)
        log.info("button %s%s -> %s", name, " (repeat)" if repeat else "", act)
        if not act:
            return
        kind = act[0]
        if kind == "volume":
            launcher_post("/api/volume", {"delta": act[1]})
        elif kind == "key":
            self.send_key(act[1])
        elif kind == "toggle_play":
            self.playing_toggle = not self.playing_toggle
            self.send_key("o" if self.playing_toggle else "p")

    def send_key(self, key):
        if self.sim:
            log.info("(sim) key %s", key)
            return
        cls = self.cfg["carplay_window_class"]
        env = dict(os.environ, DISPLAY=os.environ.get("DISPLAY", ":0"))
        subprocess.run(["xdotool", "search", "--limit", "1", "--class", cls, "key", "--window", "%1", key],
                       env=env, capture_output=True)

    def shutdown(self):
        log.warning("key off: shutting down")
        self.amp.stop()
        if not self.sim:
            subprocess.run(["sudo", "systemctl", "poweroff"])

    # -- loops ---------------------------------------------------------------
    def sample_wheel(self):
        for ch in (0, 1):
            try:
                v = self.adc.read(ch)
            except OSError:
                return
            with self.lock:
                if self.learner:
                    self.learner.feed(ch, v)
                    if self.learner.done:
                        self.cfg["buttons"] = self.learner.learned
                        self.buttons.buttons = self.cfg["buttons"]
                        save_config(self.cfg, self.sim)
                        self.learner = None
                else:
                    self.buttons.feed(ch, v)

    def poll_inputs(self):
        acc_on = not self.acc.get()
        left = self.key.update(acc_on)
        frac = self.lights_avg.feed(not self.lights.get())
        if self.lights_on.update(frac >= power.LIGHTS_ON_FRACTION):
            launcher_post("/api/dim", {"dimmed": self.lights_on.value})
        if self.in_reverse.update(not self.reverse.get()):
            self.amp.set_duck(self.cfg["reverse_duck_db"] if self.in_reverse.value else 0.0)
        self.status.update(acc=acc_on, shutdown_in=left, lights=self.lights_on.value,
                           reverse=self.in_reverse.value)

    def tick(self):
        now = time.monotonic()
        st = self.status
        if not self.amp.playing and now >= self.amp_retry_at:
            try:
                ok = self.amp.start()
            except OSError as e:
                ok, st["amp_error"] = False, str(e)
            if ok:
                self.amp_backoff = 2.0
                self.amp.set_fader(self.cfg["fader"], self.cfg["balance"])
            else:
                self.amp_retry_at = now + self.amp_backoff
                self.amp_backoff = min(self.amp_backoff * 2, 60.0)
        amp = {}
        if self.amp.playing:
            try:
                amp = self.amp.check()
            except OSError as e:
                amp = {"error": str(e)}
            if amp.get("fault"):
                log.warning("amp fault %s; restarting in %.0f s", amp.get("faults"), self.amp_backoff)
                self.amp.stop()
                self.amp_retry_at = now + self.amp_backoff
                self.amp_backoff = min(self.amp_backoff * 2, 60.0)
            self.amp.set_thermal_cut(-6.0 if amp.get("overtemp_warning") else 0.0)
        temp = fans.cpu_temp()
        duty = fans.fan_duty(temp, bool(amp.get("overtemp_warning")))
        rpm = []
        for f in self.fans:
            f.set(duty)
            rpm.append(f.poll_tach())
        st.update(amp=amp, amp_playing=self.amp.playing, cpu_temp=temp, fan_duty=round(duty, 2),
                  fan_rpm=rpm)

    def run(self):
        last_in = last_tick = 0.0
        while not self.stop.is_set():
            self.sample_wheel()
            now = time.monotonic()
            if now - last_in >= 0.05:
                self.poll_inputs()
                last_in = now
            if now - last_tick >= 1.0:
                self.tick()
                last_tick = now
            if self.sim:
                time.sleep(0.01)

    # -- API -------------------------------------------------------------------
    def state(self):
        with self.lock:
            return dict(self.status, buttons=self.cfg["buttons"], actions=self.cfg["actions"],
                        fader=self.cfg["fader"], balance=self.cfg["balance"],
                        learn=self.learner.state if self.learner else None)

    def api(self, path, data):
        with self.lock:
            if path == "/learn/start":
                self.learner = swc.Learner()
            elif path == "/learn/skip" and self.learner:
                self.learner.skip()
            elif path == "/learn/cancel":
                self.learner = None
            elif path == "/fader":
                self.cfg["fader"] = max(-1.0, min(1.0, float(data.get("fader", self.cfg["fader"]))))
                self.cfg["balance"] = max(-1.0, min(1.0, float(data.get("balance", self.cfg["balance"]))))
                self.amp.set_fader(self.cfg["fader"], self.cfg["balance"])
                save_config(self.cfg, self.sim)
            elif path == "/actions":
                self.cfg["actions"].update({k: v for k, v in data.items() if k in swc.LEARN_ORDER})
                save_config(self.cfg, self.sim)
            else:
                return None
        return self.state()


def serve(board):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/state":
                self._json(200, board.state())
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._json(400, {"error": "bad json"})
            out = board.api(self.path, data)
            self._json(200 if out is not None else 404, out or {"error": "not found"})

    srv = ThreadingHTTPServer(("127.0.0.1", API_PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="simulated hardware")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    board = Board(sim=args.sim)
    serve(board)

    def quit_(signum, frame):
        # systemd stop / halt: mute and park the amp before power goes
        log.info("signal %d: amp to standby", signum)
        board.stop.set()
        board.amp.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, quit_)
    signal.signal(signal.SIGINT, quit_)
    board.run()


if __name__ == "__main__":
    main()
