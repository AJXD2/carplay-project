#!/usr/bin/env python3
"""Talk to the Carlinkit CPC200-CCPA dongle's web admin panel from the
launcher backend, and manage the wlan0 connection needed to reach it.

The dongle's paired-device list can only be edited through its HTTP panel
at http://192.168.43.1/cgi-bin/server.cgi (the USB wire protocol has no
remove command -- see INFO.md). That panel is only reachable over the
dongle's own WiFi AP `AutoKit-8169`, so this module also knows how to
temporarily borrow wlan0 to join it and hand it back afterward.

Request signing was reverse-engineered from the panel's PublicV2.js and
verified against captured traffic:
    sign = md5( "k1=v1&k2=v2&..."(all fields incl ts, keys sorted) + SALT )
See launcher/tools/ccpa_panel.py for the standalone CLI version.
"""
import hashlib
import json
import socket
import subprocess
import threading
import time
import urllib.request
import uuid

HOST = "192.168.43.1"
AP_SSID = "AutoKit-8169"
AP_PSK = "12345678"
SALT = "HweL*@M@JEYUnvPw9G36MVB9X6u@2qxK"
IFACE = "wlan0"


# ---- CGI protocol -------------------------------------------------------

def _sign(fields):
    base = "&".join(f"{k}={fields[k]}" for k in sorted(fields))
    return hashlib.md5((base + SALT).encode()).hexdigest()


def cgi(cmd, item=None, val=None, timeout=6):
    """POST one signed command to the panel. Returns parsed JSON (dict/list)
    or the raw string. Raises on network error."""
    fields = {"cmd": cmd}
    # the panel omits empty item/val entirely; mirror that or the sign fails
    if item not in (None, ""):
        fields["item"] = item
        fields["val"] = "" if val is None else str(val)
    fields["ts"] = str(int(time.time() * 1000))
    fields["sign"] = _sign(fields)

    boundary = "----wb" + uuid.uuid4().hex
    body = "".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
        for k, v in fields.items()
    ) + f"--{boundary}--\r\n"
    req = urllib.request.Request(
        f"http://{HOST}/cgi-bin/server.cgi", data=body.encode(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def reachable(timeout=1.5):
    try:
        with socket.create_connection((HOST, 80), timeout=timeout):
            return True
    except OSError:
        return False


# ---- wlan0 management ---------------------------------------------------

def _wpa(*args):
    return subprocess.run(["sudo", "wpa_cli", "-i", IFACE, *args],
                          capture_output=True, text=True, timeout=15)


def current_ssid():
    try:
        out = _wpa("status").stdout
        for line in out.splitlines():
            if line.startswith("ssid="):
                return line[5:]
    except Exception:
        pass
    return None


def _network_ids():
    """Return (autokit_id_or_None, current_id_or_None) from list_networks."""
    autokit = current = None
    try:
        out = _wpa("list_networks").stdout
        for line in out.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            nid, ssid = parts[0], parts[1]
            flags = parts[3] if len(parts) > 3 else ""
            if ssid == AP_SSID:
                autokit = nid
            if "[CURRENT]" in flags:
                current = nid
    except Exception:
        pass
    return autokit, current


def join_ap(poll_timeout=20, cancelled=lambda: False):
    """Join wlan0 to the dongle AP. Returns True once the panel is reachable.
    Idempotent: returns immediately if already reachable. `cancelled` is
    checked before wlan0 is switched over and while polling, so a caller
    that gave up (the user left the Devices view) never leaves wlan0
    parked on the dongle's AP."""
    if reachable():
        return True
    if cancelled():
        return False
    autokit, _ = _network_ids()
    if autokit is None:
        autokit = _wpa("add_network").stdout.strip().splitlines()[-1].strip()
        _wpa("set_network", autokit, "ssid", f'"{AP_SSID}"')
        _wpa("set_network", autokit, "psk", f'"{AP_PSK}"')
    if cancelled():
        return False
    _wpa("enable_network", autokit)
    _wpa("select_network", autokit)  # disables the others until reconfigure
    deadline = time.time() + poll_timeout
    while time.time() < deadline and not cancelled():
        if reachable():
            return True
        time.sleep(1)
    return reachable()


def restore_wifi():
    """Hand wlan0 back to its configured (home) networks. reconfigure reloads
    from wpa_supplicant.conf, dropping the un-saved temp AutoKit network."""
    try:
        _wpa("reconfigure")
        return True
    except Exception:
        return False


# ---- stateful manager used by the launcher backend ----------------------

class DongleManager:
    """Owns the connect lifecycle so the frontend can poll a simple state.

    States: idle -> connecting -> ready (or error). Connecting happens on a
    background thread so the HTTP handler returns instantly and the UI can
    show a skeleton.

    Every connect attempt and every disconnect bumps a generation counter.
    A worker whose generation is stale (the user left the view while it was
    still joining) hands wlan0 back instead of reporting ready -- otherwise
    a quick open-then-back would strand wlan0 on the dongle's AP.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.state = "idle"      # idle | connecting | ready | error
        self.error = None
        self._thread = None
        self._gen = 0

    def _connect_worker(self, gen):
        stale = lambda: self._gen != gen  # noqa: E731
        try:
            ok = join_ap(cancelled=stale)
        except Exception as e:  # noqa: BLE001 - surface any failure to the UI
            ok, err = False, str(e)
        else:
            err = None if ok else "could not reach dongle Wi-Fi"
        with self._lock:
            if stale():
                restore_wifi()
                return
            if ok:
                self.state, self.error = "ready", None
            else:
                self.state, self.error = "error", err

    def ensure_connecting(self):
        """Kick off (or reuse) a connect attempt. Non-blocking."""
        with self._lock:
            if self.state == "ready" and reachable():
                return self.state
            if self.state == "connecting":
                return self.state
            self._gen += 1
            self.state, self.error = "connecting", None
            self._thread = threading.Thread(
                target=self._connect_worker, args=(self._gen,), daemon=True)
            self._thread.start()
            return self.state

    def reset_on_startup(self):
        """If a previous server run died with wlan0 still on the dongle's AP,
        give it back to the home network."""
        if current_ssid() == AP_SSID:
            return restore_wifi()
        return True

    def status(self):
        with self._lock:
            # a previously-ready link can drop if wlan0 roamed away
            if self.state == "ready" and not reachable():
                self.state = "idle"
            return {"state": self.state, "error": self.error}

    def devices(self):
        data = cgi("infos")
        return data.get("DevList", []) if isinstance(data, dict) else []

    def monitor(self):
        data = cgi("BoxMonitor")
        return data.get("BoxMonitor", {}) if isinstance(data, dict) else {}

    def remove(self, mac):
        res = cgi("set", "delDev", mac)
        return isinstance(res, dict) and res.get("err") == 0

    def disconnect(self):
        with self._lock:
            self._gen += 1
            self.state, self.error = "idle", None
        return restore_wifi()
