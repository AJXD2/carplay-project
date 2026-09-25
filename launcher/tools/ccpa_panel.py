#!/usr/bin/env python3
"""Headless client for the Carlinkit CPC200-CCPA dongle's web admin panel.

The dongle runs a WiFi AP `AutoKit-8169` (WPA2, password `12345678`).
Join it and you land on 192.168.43.0/24 with a Vue admin panel at
http://192.168.43.1 whose entire backend is one endpoint:

    POST http://192.168.43.1/cgi-bin/server.cgi   (multipart/form-data)

Every request is signed. Reversed from the panel's PublicV2.js
`signFormData` and verified byte-for-byte against captured requests:

    ts   = current time in milliseconds
    sign = md5( "k1=v1&k2=v2&..."  + SALT )
           where the pairs are ALL other fields (cmd/item/val/ts...),
           keys sorted ascending, joined by '&'. Empty item/val are
           omitted (never sent). If a field literally named `sign` is
           already present (only the activation `cmd=a` call), it is
           renamed to `sg` before signing.

This is the ONLY known way to edit the dongle's paired-device list
(`cmd=set item=delDev val=<MAC>`) -- the USB wire protocol has no such
command. See INFO.md.

Usage (run from a machine on the AutoKit AP, or tunnel via SOCKS):
    ccpa_panel.py infos                 # full state (CarInfo/BoxInfo/Settings/DevList)
    ccpa_panel.py monitor               # live CPU%/temp/freq/mem/wifi of the dongle
    ccpa_panel.py listdev               # just the paired-device list
    ccpa_panel.py deldev <MAC>          # remove one paired device  (WRITE)
    ccpa_panel.py get <settingKey>      # read one Settings value
    ccpa_panel.py set <settingKey> <v>  # change one Settings value  (WRITE)
    ccpa_panel.py upgradestate          # firmware-update progress
    ccpa_panel.py raw <cmd> [item] [val]

    --host 192.168.43.1   override panel host
    --proxy socks5h://127.0.0.1:1080   route through an SSH -D tunnel
"""
import argparse, hashlib, http.client, json, socket, struct, sys, time, uuid, urllib.parse

SALT = "HweL*@M@JEYUnvPw9G36MVB9X6u@2qxK"


def _sign(fields: dict) -> str:
    base = "&".join(f"{k}={fields[k]}" for k in sorted(fields))
    return hashlib.md5((base + SALT).encode()).hexdigest()


def call(cmd, item=None, val=None, *, host="192.168.43.1", proxy=None,
         timeout=8, extra=None):
    fields = {"cmd": cmd}
    # panel omits item/val entirely when empty; mirror that so the sign matches
    if item not in (None, ""):
        fields["item"] = item
        fields["val"] = "" if val is None else str(val)
    if extra:
        fields.update(extra)
    fields["ts"] = str(int(time.time() * 1000))
    fields["sign"] = _sign(fields)

    boundary = "----wb" + uuid.uuid4().hex
    body = "".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
        for k, v in fields.items()
    ) + f"--{boundary}--\r\n"
    conn = (SocksHTTPConnection(host, proxy, timeout=timeout) if proxy
            else http.client.HTTPConnection(host, timeout=timeout))
    try:
        conn.request("POST", "/cgi-bin/server.cgi", body=body.encode(),
                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", "replace")
    finally:
        conn.close()
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def socks5_connect(proxy, host, port, timeout):
    """Open a TCP connection to host:port through a SOCKS5 proxy (no auth),
    e.g. an `ssh -D` tunnel. urllib has no SOCKS support, and this tool stays
    stdlib-only so it runs on the Pi as-is. The hostname is resolved by the
    proxy side (socks5h), since 192.168.43.x only exists there."""
    u = urllib.parse.urlparse(proxy)
    if u.scheme not in ("socks5", "socks5h"):
        raise SystemExit(f"unsupported proxy {proxy!r}: use socks5h://host:port")
    s = socket.create_connection((u.hostname, u.port or 1080), timeout=timeout)
    s.sendall(b"\x05\x01\x00")                       # v5, 1 method: no auth
    if s.recv(2) != b"\x05\x00":
        raise ConnectionError("SOCKS proxy refused no-auth")
    name = host.encode()
    s.sendall(b"\x05\x01\x00\x03" + bytes([len(name)]) + name + struct.pack(">H", port))
    head = s.recv(4)
    if len(head) < 4 or head[1] != 0:
        raise ConnectionError(f"SOCKS connect to {host}:{port} failed (code {head[1] if len(head) > 1 else '?'})")
    # skip the bound address in the reply
    skip = {1: 4, 4: 16}.get(head[3])
    if skip is None:
        skip = s.recv(1)[0]
    s.recv(skip + 2)
    return s


class SocksHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, proxy, **kw):
        super().__init__(host, **kw)
        self.proxy = proxy

    def connect(self):
        self.sock = socks5_connect(self.proxy, self.host, self.port, self.timeout)


def main():
    p = argparse.ArgumentParser(description="Carlinkit CPC200-CCPA panel client")
    p.add_argument("--host", default="192.168.43.1")
    p.add_argument("--proxy", default=None,
                   help="e.g. socks5h://127.0.0.1:1080 for an ssh -D tunnel")
    p.add_argument("action")
    p.add_argument("args", nargs="*")
    a = p.parse_args()
    kw = dict(host=a.host, proxy=a.proxy)

    def show(x):
        print(json.dumps(x, ensure_ascii=False, indent=2)
              if isinstance(x, (dict, list)) else x)

    act = a.action.lower()
    if act == "infos":
        show(call("infos", **kw))
    elif act == "monitor":
        show(call("BoxMonitor", **kw))
    elif act == "upgradestate":
        show(call("upgradeState", **kw))
    elif act == "listdev":
        show(call("infos", **kw).get("DevList"))
    elif act == "deldev":
        show(call("set", "delDev", a.args[0], **kw))
    elif act == "get":
        show(call("infos", **kw).get("Settings", {}).get(a.args[0]))
    elif act == "set":
        show(call("set", a.args[0], a.args[1], **kw))
    elif act == "raw":
        show(call(a.args[0], a.args[1] if len(a.args) > 1 else None,
                  a.args[2] if len(a.args) > 2 else None, **kw))
    else:
        p.error(f"unknown action {a.action!r}")


if __name__ == "__main__":
    main()
