#!/usr/bin/env python3
"""carrierd: runs the carrier board (hardware/carrier).

  - brings the TAS6424 amp up once the audio clocks run, applies fader,
    watches FAULT/WARN, recovers latched faults, trims volume when hot
  - reads the steering-wheel ladders (ADS1115) and turns presses into
    CarPlay keys / launcher volume; learn mode maps a new wheel
  - key off for 8 s -> mute, standby, poweroff (gpio-poweroff then drops
    PI_HOLD and the board switches itself off)
  - headlights -> launcher night mode; reverse -> duck the music
  - fans at full speed while the amp runs (SoC temperature curve otherwise),
    tach readback; a notice on the launcher when the amp runs hot or a fan
    stops
  - battery voltage (ADS1115 AIN2) and dash temperature (DS3231) for the
    launcher's Info view

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
FAN_STALL_S = 5                                       # 0 rpm this many ticks while driven -> stopped

# BCM GPIO numbers (hardware/carrier/tools/gen_sch.py PI_GPIO)
GPIO = dict(acc=17, lights=27, reverse=7, amp_stby=22, amp_mute=23, amp_fault=24,
            amp_warn=25, adc_alert=6, fan1_tach=16, fan2_tach=4)
PWM_CH = dict(fan1=0, fan2=1)                         # GPIO12 / GPIO13
# ADS1115 AIN2: battery through R2 95.3k over R3 5.11k + R4 3.74k (R4 is
# shared with the LM74800's OV divider), so volts at AIN2 x 11.77.
BATT_CH, BATT_SCALE = 2, (95.3 + 5.11 + 3.74) / (5.11 + 3.74)


def board_temp():
    """DS3231 die temperature (rtc-ds1307 exposes it as hwmon): the air
    inside the dash, near enough. None without the RTC driver."""
    import glob
    for d in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            if open(f"{d}/name").read().strip() == "ds3231":
                return int(open(f"{d}/temp1_input").read()) / 1000
        except (OSError, ValueError):
            pass
    return None

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


CDP_PORT = 9229                                       # react-carplay's DevTools port (server.py)


def ws_send(url, text, timeout=2.0):
    """One text message over a WebSocket (RFC 6455, client side, no
    extensions) and the first reply. Enough for one DevTools command."""
    import base64
    import socket
    import struct
    import urllib.parse
    u = urllib.parse.urlparse(url)
    with socket.create_connection((u.hostname, u.port or 80), timeout=timeout) as s:
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = s.recv(1024)
            if not chunk:
                return None
            resp += chunk
        if b" 101 " not in resp.split(b"\r\n", 1)[0]:
            return None
        data, mask = text.encode(), os.urandom(4)
        n = len(data)
        head = struct.pack("!BB", 0x81, 0x80 | n) if n < 126 else struct.pack("!BBH", 0x81, 0x80 | 126, n)
        s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        reply = resp.split(b"\r\n\r\n", 1)[1]
        while len(reply) < 2:
            reply += s.recv(4096)
        return reply.decode("utf-8", "replace")


def cdp_key(key):
    """Fire react-carplay's keydown handler for `key` through its DevTools
    port: works whether or not CarPlay is on screen or has focus. False when
    the port isn't there (CarPlay started without it, or not running)."""
    code = f"Key{key.upper()}" if len(key) == 1 and key.isalpha() else key
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=1) as r:
            targets = json.load(r)
        page = next(t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl"))
        expr = f"document.dispatchEvent(new KeyboardEvent('keydown', {{code: '{code}', key: '{key}'}}))"
        reply = ws_send(page["webSocketDebuggerUrl"],
                        json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expr}}))
        return bool(reply and '"result"' in reply)
    except (OSError, ValueError, StopIteration):
        return False


def carplay_window(env, cls):
    """The visible CarPlay window (largest viewable window of the class), or
    None when the launcher has it hidden."""
    run = lambda *a: subprocess.run(a, env=env, capture_output=True, text=True, timeout=3).stdout
    best, area = None, 0
    for w in run("xdotool", "search", "--class", cls).split():
        info = run("xwininfo", "-id", w)
        if "IsViewable" not in info:
            continue
        dims = dict(line.strip().split(": ", 1) for line in info.splitlines()
                    if line.strip().startswith(("Width:", "Height:")))
        a = int(dims.get("Width", 0)) * int(dims.get("Height", 0))
        if a > area:
            best, area = w, a
    return best


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
        self.wheel_v = [None, None]                  # pin 8 (KEY1), pin 18 (KEY2) volts
        self.amp_retry_at = 0.0
        self.amp_backoff = 2.0
        self.amp_hot = False
        self.amp_hot_count = 0                        # overtemp warnings since start
        self.fan_stalled = [0, 0]                     # ticks at 0 rpm while driven
        self.check_fans = not sim                     # the sim's tach lines never pulse
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
        """Send `key` to CarPlay. react-carplay reads keydown in its page
        (bindings in its config.json). First choice: its DevTools port, which
        reaches the page even behind the launcher. Fallback: Chromium only
        takes real key events in the focused window (`xdotool key --window`
        is ignored, and the first window of the class is a hidden helper),
        so find the visible CarPlay window, focus it, type."""
        if self.sim:
            log.info("(sim) key %s", key)
            return
        if cdp_key(key):                              # works with CarPlay hidden too
            return
        env = dict(os.environ, DISPLAY=os.environ.get("DISPLAY", ":0"))
        win = carplay_window(env, self.cfg["carplay_window_class"])
        if not win:
            log.info("key %s: CarPlay is not on screen", key)
            return
        subprocess.run(["xdotool", "windowfocus", "--sync", win, "key", "--clearmodifiers", key],
                       env=env, capture_output=True, timeout=3)

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
            self.wheel_v[ch] = round(v, 3)               # live, for /state (wiring checks)
            with self.lock:
                if self.learner:
                    self.learner.feed(ch, v)
                    if self.learner.done:
                        if self.learner.learned:          # all skipped: keep the old set
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
        try:
            st["battery_v"] = round(self.adc.read(BATT_CH) * BATT_SCALE, 2)
        except OSError:
            st["battery_v"] = None
        st["board_temp"] = None if self.sim else board_temp()
        hot = bool(amp.get("overtemp_warning"))
        if hot and not self.amp_hot:
            # with the fans at full speed this should only happen with dust,
            # a dead fan or a very hot dash: say so where the driver sees it
            self.amp_hot_count += 1
            log.warning("amp overtemp warning (%d since start)", self.amp_hot_count)
            launcher_post("/api/notice", {"text": "Amp ran hot. Check fans and vents"})
        self.amp_hot = hot
        temp = fans.cpu_temp()
        duty = fans.fan_duty(temp, hot, self.amp.playing)
        rpm = []
        for f in self.fans:
            f.set(duty)
            rpm.append(f.poll_tach())
        self.watch_fans(rpm, duty)
        st.update(amp=amp, amp_playing=self.amp.playing, amp_hot_count=self.amp_hot_count,
                  cpu_temp=temp, fan_duty=round(duty, 2), fan_rpm=rpm)

    def watch_fans(self, rpm, duty):
        """A driven fan reading 0 rpm for FAN_STALL_S ticks: tell the launcher
        once. The amp shuts down in a hot car without fan 1's air."""
        if not self.check_fans:
            return
        for i, r in enumerate(rpm):
            self.fan_stalled[i] = self.fan_stalled[i] + 1 if duty > 0 and r == 0 else 0
            if self.fan_stalled[i] == FAN_STALL_S:
                log.warning("fan %d stopped", i + 1)
                launcher_post("/api/notice", {"text": f"Fan {i + 1} stopped. Check its plug"})

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
            return dict(self.status, wheel_v=list(self.wheel_v), buttons=self.cfg["buttons"], actions=self.cfg["actions"],
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
