"""Register-level models of the board's I2C chips, for tests and --sim."""
from board import swc, tas6424


class SimTAS6424:
    """Register file with the reset values from SLOSE73A section 9.6. Faults
    can be injected; they latch until CLEAR FAULT (0x21 bit 7), as on the
    real part."""

    RESET = {0x00: 0x00, 0x01: 0x32, 0x02: 0x62, 0x03: 0x04, 0x04: 0x55, 0x05: 0xCF,
             0x06: 0xCF, 0x07: 0xCF, 0x08: 0xCF, 0x10: 0, 0x11: 0, 0x12: 0, 0x13: 0x20,
             0x14: 0, 0x21: 0, 0x28: 0x0A}

    def __init__(self):
        self.regs = dict(self.RESET)
        self.writes = []
        self.pending_faults = {}                       # reg -> bits that come back after a clear

    def inject(self, reg, bits, sticky=False):
        self.regs[reg] = self.regs.get(reg, 0) | bits
        if sticky:
            self.pending_faults[reg] = bits

    def write(self, reg, data):
        for i, b in enumerate(data):
            r = reg + i
            self.writes.append((r, b))
            if r == 0x00 and b & 0x80:
                self.regs = dict(self.RESET)
                continue
            if r == 0x21 and b & 0x80:
                for f in (0x10, 0x11, 0x12):
                    self.regs[f] = self.pending_faults.get(f, 0)
                self.regs[0x13] &= ~0x20
                continue
            self.regs[r] = b

    def read(self, reg, n):
        return bytes(self.regs.get(reg + i, 0) for i in range(n))


class SimADS1115:
    """Two ladder inputs. Set .volts[ch] to what the wheel presents."""

    def __init__(self):
        self.volts = [3.3, 3.3]
        self.cfg = 0x8583
        self.last = 0

    def write(self, reg, data):
        if reg == swc.REG_CFG:
            self.cfg = (data[0] << 8) | data[1]
            ch = ((self.cfg >> 12) & 0b111) - 0b100
            raw = round(self.volts[ch] / swc.FSR * 32768)
            self.last = max(-32768, min(32767, raw))

    def read(self, reg, n):
        if reg == swc.REG_CFG:
            return bytes([(self.cfg >> 8) | 0x80, self.cfg & 0xFF])
        v = self.last & 0xFFFF
        return bytes([v >> 8, v & 0xFF])


def devices():
    return {tas6424.ADDR: SimTAS6424(), swc.ADDR: SimADS1115()}
