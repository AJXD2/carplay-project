"""Write-through persistence for the overlayroot read-only root.

Anything written to the live filesystem lands in the tmpfs overlay and is
gone on the next power cut. This module copies chosen files through to the
real ext4 partition mounted read-only at /media/root-ro, the same
remount-rw / sudo-write / remount-ro dance deploy.sh uses, but done live
from the running device.

Two entry points:
- write_through(path, data): persist one file right now (launcher config,
  trip state).
- Watcher: a background thread that notices when some *other* program
  rewrites a file (react-carplay saving its settings) and persists it.
"""
import json
import os
import subprocess
import threading
import time

LOWER_ROOT = "/media/root-ro"

_lock = threading.Lock()


def lower_path(live_path):
    return LOWER_ROOT + os.path.abspath(live_path)


def _sudo(*args, **kw):
    return subprocess.run(["sudo", *args], capture_output=True, **kw)


def write_through(live_path, data):
    """Persist `data` (bytes or str) as `live_path` on the real partition,
    and mirror it to the live path too so the running session sees it.
    Returns True on success. The final remount back to ro is best-effort:
    the kernel often refuses it while the overlay is mounted on top (see
    INFO.md), which just leaves the partition writable until next boot."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    target = lower_path(live_path)
    tmp = target + ".tmp"
    with _lock:
        try:
            _sudo("mount", "-o", "remount,rw", LOWER_ROOT, check=True)
            _sudo("mkdir", "-p", os.path.dirname(target), check=True)
            # tee + sync + mv keeps the swap atomic: a power cut mid-write
            # leaves either the old file or the new one, never half of one.
            _sudo("tee", tmp, input=data, check=True)
            _sudo("chown", "ajxd2:ajxd2", tmp, check=True)
            _sudo("sync", tmp, check=True)
            _sudo("mv", "-f", tmp, target, check=True)
            _sudo("sync", os.path.dirname(target), check=True)
            ok = True
        except (subprocess.CalledProcessError, OSError):
            ok = False
        finally:
            _sudo("mount", "-o", "remount,ro", LOWER_ROOT)
    if ok:
        try:
            if _read(live_path) != data:
                with open(live_path, "wb") as f:
                    f.write(data)
        except OSError:
            pass
    return ok


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


class Watcher(threading.Thread):
    """Polls a few JSON files and persists them whenever their live content
    stops matching the copy on the real partition. Only complete, parseable
    JSON is persisted, so a half-written save is skipped and picked up on
    the next poll instead."""

    def __init__(self, paths, interval=3.0, log=None):
        super().__init__(daemon=True)
        self.paths = [os.path.expanduser(p) for p in paths]
        self.interval = interval
        self.log = log or (lambda msg: None)
        self._mtimes = {}

    def check(self, path):
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            return
        if self._mtimes.get(path) == mtime:
            return
        live = _read(path)
        if live is None:
            return
        try:
            json.loads(live)
        except ValueError:
            return  # mid-write; try again next poll
        self._mtimes[path] = mtime
        if live == _read(lower_path(path)):
            return
        ok = write_through(path, live)
        self.log(f"persisted {path}" if ok else f"failed to persist {path}")

    def run(self):
        while True:
            for p in self.paths:
                try:
                    self.check(p)
                except Exception as e:  # noqa: BLE001 - never kill the thread
                    self.log(f"watcher error on {p}: {e}")
            time.sleep(self.interval)
