#!/usr/bin/env python3
"""Install a patched copy of react-carplay with a jitter-buffered audio player.

react-carplay 4.0.5's audio worklet starts playing the moment 128 frames
(~3 ms) of audio exist and goes silent for one render quantum whenever the
next packet from the dongle is even slightly late. Wireless CarPlay delivers
audio unevenly, so that plays as constant crackling. The replacement worklet
(carplay_audio_worklet.js next to this script) waits for 120 ms of audio
before (re)starting and trims slow clock drift so latency stays bounded.

The AppImage is a read-only squashfs, so this extracts it once to
~/react-carplay on the real ext4 partition (/media/root-ro, persists across
reboots), then swaps audio.worklet.js inside resources/app.asar in place.
The new file is padded to the original's exact size, so no other offsets in
the archive move, and the archive header's integrity hash is updated.

Idempotent and conservative: it only patches the exact upstream file it
expects (checked by SHA-256), does nothing if already patched, and never
touches the original AppImage, which server.py falls back to if the
extracted copy is missing.

Run on the Pi as root (deploy.sh does this):
    sudo python3 patch_carplay_audio.py
"""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys

LOWER = "/media/root-ro"
APPIMAGE = "/home/ajxd2/react-carplay.AppImage"
DEST = "/home/ajxd2/react-carplay"
WORKLET_PATH = ["out", "renderer", "audio.worklet.js"]
# audio.worklet.js as shipped in react-carplay v4.0.5
UPSTREAM_SHA256 = "659719ea01d685c67eef9cd4a38c4e2e8bc5c517fe486763e2c8fdf6b0b567a1"
NEW_WORKLET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "carplay_audio_worklet.js")


def sh(*args, **kw):
    return subprocess.run(args, check=True, **kw)


def extract(lower_dest):
    work = lower_dest + ".extracting"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    print(f"extracting {APPIMAGE} (takes a minute)...")
    sh(LOWER + APPIMAGE, "--appimage-extract", cwd=work, stdout=subprocess.DEVNULL)
    os.rename(os.path.join(work, "squashfs-root"), lower_dest)
    os.rmdir(work)
    sh("chown", "-R", "ajxd2:ajxd2", lower_dest)


def read_header(f):
    # asar: pickle(uint32 size=4, uint32 header_size) + pickle(uint32 payload,
    # uint32 json_len, json...) ; file data starts at 8 + header_size
    f.seek(0)
    _, header_size, _, json_len = struct.unpack("<IIII", f.read(16))
    raw = f.read(json_len)
    return json.loads(raw), json_len, 8 + header_size


def patch_asar(asar_path):
    new = open(NEW_WORKLET, "rb").read()
    with open(asar_path, "r+b") as f:
        header, json_len, data_start = read_header(f)
        entry = header
        for part in WORKLET_PATH:
            entry = entry["files"][part]
        size, offset = entry["size"], int(entry["offset"])
        f.seek(data_start + offset)
        current = f.read(size)
        cur_sha = hashlib.sha256(current).hexdigest()

        if len(new) > size:
            sys.exit(f"patched worklet is {len(new)} bytes, must fit in {size}")
        padded = new + b" " * (size - len(new))
        new_sha = hashlib.sha256(padded).hexdigest()

        if cur_sha == new_sha:
            print("audio worklet already patched")
            return
        if cur_sha != UPSTREAM_SHA256:
            sys.exit(f"unexpected audio.worklet.js (sha256 {cur_sha}); refusing to patch "
                     "an unknown react-carplay version")

        f.seek(data_start + offset)
        f.write(padded)

        # keep the header's integrity metadata truthful (same-length hex, so
        # the header size doesn't change)
        integ = entry.get("integrity")
        if integ:
            integ["hash"] = new_sha
            integ["blocks"] = [new_sha]
        raw = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode()
        if len(raw) != json_len:
            # re-serialize to the original length is not guaranteed; if it
            # differs, leave the (non-enforced on Linux) hash alone instead
            print("note: header re-serialization changed length; integrity hash left as-is")
        else:
            f.seek(16)
            f.write(raw)
        f.flush()
        os.fsync(f.fileno())

    with open(asar_path, "rb") as f:
        header, _, data_start = read_header(f)
        entry = header
        for part in WORKLET_PATH:
            entry = entry["files"][part]
        f.seek(data_start + int(entry["offset"]))
        if hashlib.sha256(f.read(entry["size"])).hexdigest() != new_sha:
            sys.exit("verification failed after write")
    print("audio worklet patched and verified")


def main():
    if os.geteuid() != 0:
        sys.exit("run as root: sudo python3 patch_carplay_audio.py")
    lower_dest = LOWER + DEST
    subprocess.run(["mount", "-o", "remount,rw", LOWER])
    try:
        if not os.path.exists(os.path.join(lower_dest, "resources", "app.asar")):
            extract(lower_dest)
        patch_asar(os.path.join(lower_dest, "resources", "app.asar"))
        sh("sync")
    finally:
        subprocess.run(["mount", "-o", "remount,ro", LOWER], stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
