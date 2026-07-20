#!/usr/bin/env python3
"""Set the custom OEM icon + label shown for this box on the phone's
CarPlay home screen, by talking directly to the dongle's own USB
protocol (the same one node-carplay/react-carplay use).

Requires the dongle's USB interface to be free -- stop react-carplay
first (`pkill -9 -f react-carplay`, or use the launcher's /api/launch
to switch away from CarPlay) before running this, then relaunch it
afterwards.

Depends on `python3-usb` (install persistently via
`sudo overlayroot-chroot apt-get install -y python3-usb`).

Usage:
    python3 set_dongle_icon.py <label> <icon.png>

<icon.png> should be a square image (256x256 or so recommended). It's
written verbatim to all three icon sizes CarPlay requests -- the phone
scales as needed, matching how node-carplay's own scripts/configIcon.ts
does it.

After running, the change may not show up live: this writes to /etc/
on the dongle's own embedded filesystem, which in testing only took
effect after a physical power-cycle of the dongle (unplug/replug the
USB cable). A CarPlay app restart alone was not enough.
"""
import struct
import sys
import time

import usb.core
import usb.util

VENDOR_ID = 0x1314
PRODUCT_ID = 0x1521
MAGIC = 0x55AA55AA
HEADER_LEN = 16

TYPE_OPEN = 0x01
TYPE_CLOSE_DONGLE = 0x15
TYPE_SEND_FILE = 0x99

ICON_PATHS = (
    "/etc/icon_120x120.png",
    "/etc/icon_180x180.png",
    "/etc/icon_256x256.png",
    "/etc/oem_icon.png",
)
AIRPLAY_CONFIG = "/etc/airplay.conf"


def build_header(msg_type, payload_len):
    type_check = (~msg_type) & 0xFFFFFFFF
    return struct.pack("<IIII", MAGIC, payload_len, msg_type, type_check)


def build_open_payload(width=800, height=480, fps=20, fmt=5,
                        packet_max=49152, ibox_version=2, phone_work_mode=2):
    return struct.pack("<IIIIIII", width, height, fps, fmt, packet_max,
                        ibox_version, phone_work_mode)


def build_sendfile_payload(content: bytes, filename: str) -> bytes:
    name_bytes = (filename + "\0").encode("ascii")
    name_len = struct.pack("<I", len(name_bytes))
    content_len = struct.pack("<I", len(content))
    return name_len + name_bytes + content_len + content


def build_airplay_conf(label: str) -> bytes:
    value_map = {
        "oemIconVisible": 1,
        "name": "AutoBox",
        "model": "Magic-Car-Link-1.00",
        "oemIconPath": "/etc/oem_icon.png",
    }
    if label:
        value_map["oemIconLabel"] = label
    lines = [f"{k} = {v}" for k, v in value_map.items()]
    return ("\n".join(lines) + "\n").encode("ascii")


class Dongle:
    def __init__(self):
        self.dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if self.dev is None:
            raise SystemExit("Dongle not found -- is it plugged in and is react-carplay stopped?")
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except (NotImplementedError, usb.core.USBError):
            pass
        try:
            self.dev.set_configuration()
        except usb.core.USBError:
            pass
        cfg = self.dev.get_active_configuration()
        self.intf = cfg[(0, 0)]
        usb.util.claim_interface(self.dev, self.intf.bInterfaceNumber)
        self.ep_out = usb.util.find_descriptor(
            self.intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)

    def send_open(self):
        payload = build_open_payload()
        self.ep_out.write(build_header(TYPE_OPEN, len(payload)) + payload)

    def send_file(self, content: bytes, filename: str):
        payload = build_sendfile_payload(content, filename)
        self.ep_out.write(build_header(TYPE_SEND_FILE, len(payload)) + payload)

    def close(self):
        try:
            self.ep_out.write(build_header(TYPE_CLOSE_DONGLE, 0))
        except usb.core.USBError:
            pass
        usb.util.release_interface(self.dev, self.intf.bInterfaceNumber)
        usb.util.dispose_resources(self.dev)


def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <label> <icon.png>", file=sys.stderr)
        sys.exit(1)

    label = sys.argv[1]
    icon_bytes = open(sys.argv[2], "rb").read()

    dongle = Dongle()
    try:
        dongle.send_open()
        time.sleep(0.5)

        print(f"Writing icon label {label!r} to {AIRPLAY_CONFIG}")
        dongle.send_file(build_airplay_conf(label), AIRPLAY_CONFIG)
        time.sleep(0.3)

        print(f"Writing icon ({len(icon_bytes)} bytes) to {len(ICON_PATHS)} paths")
        for path in ICON_PATHS:
            dongle.send_file(icon_bytes, path)
            time.sleep(0.3)

        print("Done. Power-cycle the dongle (unplug/replug USB) for it to take effect.")
    finally:
        dongle.close()


if __name__ == "__main__":
    main()
