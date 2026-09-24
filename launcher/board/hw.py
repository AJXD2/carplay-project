"""Hardware access for the carrier board, standard library only.

I2C goes through /dev/i2c-N with the I2C_RDWR ioctl (combined write/read
transactions, so register reads use a repeated start). GPIO uses the Linux
character-device uAPI v2 (/dev/gpiochipN); PWM uses sysfs. Struct sizes and
ioctl numbers were checked against <linux/gpio.h> and <linux/i2c-dev.h>:

    gpio_v2_line_request 592 bytes (consumer @256, config @288,
    num_lines @560, event_buffer_size @564, fd @588), line event 48 bytes,
    GPIO_V2_GET_LINE_IOCTL 0xc250b407, GET/SET_VALUES 0xc010b40e/f,
    I2C_RDWR 0x707.

Every class has a Sim* twin with the same interface so the services can be
exercised on a desktop (test_board.py).
"""
import ctypes
import fcntl
import os
import select
import struct
import threading
import time

# ------------------------------------------------------------------ I2C ----

I2C_RDWR = 0x0707
I2C_M_RD = 0x0001


class _I2cMsg(ctypes.Structure):
    _fields_ = [("addr", ctypes.c_uint16), ("flags", ctypes.c_uint16),
                ("len", ctypes.c_uint16), ("buf", ctypes.c_void_p)]


class _I2cRdwr(ctypes.Structure):
    _fields_ = [("msgs", ctypes.POINTER(_I2cMsg)), ("nmsgs", ctypes.c_uint32)]


class I2CBus:
    """Register-oriented I2C master (8-bit register addresses)."""

    def __init__(self, bus=1):
        self.path = f"/dev/i2c-{bus}"
        self.fd = os.open(self.path, os.O_RDWR)
        self.lock = threading.Lock()

    def _xfer(self, *msgs):
        arr = (_I2cMsg * len(msgs))()
        keep = []
        for m, (addr, flags, data) in zip(arr, msgs):
            buf = ctypes.create_string_buffer(bytes(data), len(data))
            keep.append(buf)
            m.addr, m.flags, m.len, m.buf = addr, flags, len(data), ctypes.addressof(buf)
        req = _I2cRdwr(arr, len(msgs))
        with self.lock:
            fcntl.ioctl(self.fd, I2C_RDWR, req)
        return keep

    def write(self, addr, reg, data):
        self._xfer((addr, 0, bytes([reg]) + bytes(data)))

    def read(self, addr, reg, n):
        bufs = self._xfer((addr, 0, bytes([reg])), (addr, I2C_M_RD, bytes(n)))
        return bufs[1].raw[:n]

    def write_u8(self, addr, reg, value):
        self.write(addr, reg, [value & 0xFF])

    def read_u8(self, addr, reg):
        return self.read(addr, reg, 1)[0]


class SimI2CBus:
    """In-memory devices: {addr: device} where a device has read(reg, n)
    and write(reg, data)."""

    def __init__(self, devices=None):
        self.devices = devices or {}

    def write(self, addr, reg, data):
        self.devices[addr].write(reg, bytes(data))

    def read(self, addr, reg, n):
        return self.devices[addr].read(reg, n)

    def write_u8(self, addr, reg, value):
        self.write(addr, reg, [value & 0xFF])

    def read_u8(self, addr, reg):
        return self.read(addr, reg, 1)[0]


# ----------------------------------------------------------------- GPIO ----

GPIO_V2_GET_LINE_IOCTL = 0xC250B407
GPIO_V2_LINE_GET_VALUES_IOCTL = 0xC010B40E
GPIO_V2_LINE_SET_VALUES_IOCTL = 0xC010B40F
F_ACTIVE_LOW, F_INPUT, F_OUTPUT = 1 << 1, 1 << 2, 1 << 3
F_EDGE_RISING, F_EDGE_FALLING = 1 << 4, 1 << 5
F_PULL_UP, F_PULL_DOWN = 1 << 8, 1 << 9
ATTR_OUTPUT_VALUES, ATTR_DEBOUNCE = 2, 3
EVENT_SIZE = 48


def line_request(offset, mode="in", pull=None, value=0, debounce_us=0, consumer="carrierd"):
    """Pack a struct gpio_v2_line_request for one line."""
    flags = {"in": F_INPUT, "out": F_OUTPUT, "edge": F_INPUT | F_EDGE_RISING | F_EDGE_FALLING}[mode]
    flags |= {"up": F_PULL_UP, "down": F_PULL_DOWN, None: 0}[pull]
    req = bytearray(592)
    struct.pack_into("<I", req, 0, offset)
    struct.pack_into("32s", req, 256, consumer.encode()[:31])
    attrs = []
    if mode == "out":
        attrs.append((ATTR_OUTPUT_VALUES, struct.pack("<Q", 1 if value else 0)))
    if debounce_us:
        attrs.append((ATTR_DEBOUNCE, struct.pack("<I4x", debounce_us)))
    struct.pack_into("<QI", req, 288, flags, len(attrs))
    for i, (aid, payload) in enumerate(attrs):
        base = 288 + 32 + i * 24                    # attrs[] after flags/num_attrs/padding
        struct.pack_into("<I4x8s", req, base, aid, payload)
        struct.pack_into("<Q", req, base + 16, 1)   # mask: line 0 of this request
    struct.pack_into("<II", req, 560, 1, 16 if mode == "edge" else 0)
    return req


class GpioLine:
    """One GPIO line requested through the v2 chardev uAPI.

    mode: "in", "out" or "edge" (input with both-edge events).
    """

    def __init__(self, offset, mode="in", pull=None, value=0, debounce_us=0,
                 chip="/dev/gpiochip0", consumer="carrierd"):
        self.offset, self.mode = offset, mode
        req = line_request(offset, mode, pull, value, debounce_us, consumer)
        chip_fd = os.open(chip, os.O_RDWR)
        try:
            fcntl.ioctl(chip_fd, GPIO_V2_GET_LINE_IOCTL, req)
        finally:
            os.close(chip_fd)
        self.fd = struct.unpack_from("<i", req, 588)[0]

    def get(self):
        buf = bytearray(struct.pack("<QQ", 0, 1))
        fcntl.ioctl(self.fd, GPIO_V2_LINE_GET_VALUES_IOCTL, buf)
        return struct.unpack_from("<Q", buf)[0] & 1

    def set(self, value):
        fcntl.ioctl(self.fd, GPIO_V2_LINE_SET_VALUES_IOCTL,
                    bytearray(struct.pack("<QQ", 1 if value else 0, 1)))

    def events(self, timeout):
        """Edge events within `timeout` s: list of (timestamp_ns, rising)."""
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return []
        data = os.read(self.fd, EVENT_SIZE * 16)
        out = []
        for i in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
            ts, eid = struct.unpack_from("<QI", data, i)
            out.append((ts, eid == 1))              # GPIO_V2_LINE_EVENT_RISING_EDGE = 1
        return out

    def close(self):
        os.close(self.fd)


class SimGpioLine:
    def __init__(self, offset, mode="in", pull=None, value=0, **_):
        self.offset, self.mode = offset, mode
        self.value = value if mode == "out" else (1 if pull == "up" else 0)
        self.pending = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = 1 if value else 0

    def drive(self, value):
        """Test hook: change an input and queue an edge event."""
        value = 1 if value else 0
        if value != self.value:
            self.pending.append((time.monotonic_ns(), bool(value)))
        self.value = value

    def events(self, timeout):
        out, self.pending = self.pending, []
        return out

    def close(self):
        pass


# ------------------------------------------------------------------ PWM ----

class Pwm:
    """sysfs PWM channel (dtoverlay=pwm-2chan puts GPIO12/13 on pwmchip0
    channels 0/1)."""

    def __init__(self, channel, freq_hz=25000, chip="/sys/class/pwm/pwmchip0"):
        self.base = f"{chip}/pwm{channel}"
        if not os.path.isdir(self.base):
            with open(f"{chip}/export", "w") as f:
                f.write(str(channel))
            for _ in range(50):                      # udev fixes permissions
                if os.access(f"{self.base}/period", os.W_OK):
                    break
                time.sleep(0.02)
        self.period = int(1e9 / freq_hz)
        self._w("period", self.period)
        self._w("enable", 1)

    def _w(self, name, value):
        with open(f"{self.base}/{name}", "w") as f:
            f.write(str(value))

    def duty(self, fraction):
        self._w("duty_cycle", int(self.period * min(max(fraction, 0.0), 1.0)))


class SimPwm:
    def __init__(self, channel, freq_hz=25000, **_):
        self.channel, self.fraction = channel, 0.0

    def duty(self, fraction):
        self.fraction = min(max(fraction, 0.0), 1.0)
