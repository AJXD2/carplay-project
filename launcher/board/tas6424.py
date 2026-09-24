"""TAS6424E-Q1 control (SLOSE73A). The kernel has no codec driver for it, so
the Pi's I2S port runs as a plain stereo DAC and this configures the amp.

Audio path: the board's PCM1808 generates BCK/LRCK from a 12.288 MHz
oscillator that also drives MCLK (256 fs); SDIN1 and SDIN2 both carry the
Pi's stereo pair, so channels 1/2 (front) and 3/4 (rear) play the same
audio and the per-channel volume registers do fader and balance.

Channel map (hardware/carrier/tools/gen_sch.py): CH1 RL, CH2 RR, CH3 FL,
CH4 FR. Odd channels take the left I2S slot, even the right; the order
keeps the speaker tracks from crossing on the board.
"""
import logging
import time

log = logging.getLogger("tas6424")

ADDR = 0x6A                      # I2C_ADDR1 = I2C_ADDR0 = 0 (table 9-8: 0xD4 >> 1)

MODE_CTRL, MISC1, MISC2, SAP, CH_STATE = 0x00, 0x01, 0x02, 0x03, 0x04
VOL_BASE = 0x05                  # 0x05..0x08, 0xCF = 0 dB, 0.5 dB/step, < 0x07 = mute
CH_FAULTS, GLOBAL_FAULTS1, GLOBAL_FAULTS2, WARNINGS = 0x10, 0x11, 0x12, 0x13
PIN_CTRL, MISC3, MISC5 = 0x14, 0x21, 0x28

# Misc Control 1: HPF on, OTW at 120 C, OC level 2, volume ramp 1 step per
# 4 FSYNC (smooth fader moves), gain level 2 = 15 V peak (full scale just
# reaches a 14.4 V rail instead of clipping hard).
MISC1_VALUE = (0 << 7) | (0b10 << 5) | (1 << 4) | (0b10 << 2) | 0b01
# Misc Control 2: 2.11 MHz PWM (44 fs), 64x OSR, phase LSBs 10 (with MISC5
# PHASE_SEL = 1 -> 0/225/90/315 degrees).
MISC2_VALUE = 0x62
# SAP: 48 kHz, I2S input.
SAP_VALUE = (0b01 << 6) | 0b100
# Misc Control 5: PHASE_SEL must be 1 before leaving standby (9.6.32).
MISC5_VALUE = 0x0A | (1 << 5)
PLAY = 0x00                      # all four channels PLAY
HIZ = 0x55
MUTE_ALL = 0xAA

CHANNELS = ("RL", "RR", "FL", "FR")           # amp channel 1..4


def db_to_reg(db):
    """Volume register for a gain in dB (0 dB = 0xCF), clamped to -100..+24."""
    if db is None or db <= -100.0:
        return 0x00                                  # below 0x07: mute
    return max(0x07, min(0xFF, 0xCF + round(db * 2)))


def fader_gains(fader=0.0, balance=0.0, trim_db=0.0):
    """Per-channel gain in dB. fader -1 = rear only .. +1 = front only;
    balance -1 = left only .. +1 = right only. The far side ramps down
    40 dB, and fully off at the end stop."""
    def side(x):
        if x >= 0.999:
            return None
        return 40.0 * -x if x > 0 else 0.0
    front, rear = side(-fader), side(fader)
    left, right = side(balance), side(-balance)
    out = {}
    for ch in CHANNELS:
        fb = front if ch[0] == "F" else rear
        lr = left if ch[1] == "L" else right
        out[ch] = None if fb is None or lr is None else trim_db + fb + lr
    return out


class Amp:
    """Owns the amp's GPIOs (STANDBY, MUTE outputs; FAULT, WARN inputs) and
    its registers."""

    def __init__(self, bus, standby, mute, fault, warn, sleep=time.sleep):
        self.bus, self.standby, self.mute, self.fault, self.warn = bus, standby, mute, fault, warn
        self.sleep = sleep
        self.gains = fader_gains()
        self.duck_db = 0.0
        self.thermal_db = 0.0
        self.playing = False
        self.last_fault = {}

    # -- bring-up / teardown ----------------------------------------------
    def start(self):
        """Datasheet order: muted and in standby, release standby, program,
        clear faults, check, PLAY, unmute."""
        self.mute.set(0)
        self.standby.set(0)
        self.sleep(0.02)
        self.standby.set(1)
        self.sleep(0.01)
        w = self.bus.write_u8
        w(ADDR, MODE_CTRL, 0x80)                     # soft reset, self-clearing
        self.sleep(0.005)
        w(ADDR, MISC5, MISC5_VALUE)
        w(ADDR, MISC1, MISC1_VALUE)
        w(ADDR, MISC2, MISC2_VALUE)
        w(ADDR, SAP, SAP_VALUE)
        self._write_volumes()
        w(ADDR, MISC3, 0x80)                         # CLEAR FAULT
        self.sleep(0.01)
        faults = self.read_faults()
        if faults:
            log.warning("amp faults at start: %s", faults)
            self.last_fault = faults
            w(ADDR, CH_STATE, HIZ)
            return False
        w(ADDR, CH_STATE, PLAY)
        self.sleep(0.02)
        self.mute.set(1)
        self.playing = True
        log.info("amp playing")
        return True

    def stop(self):
        """Mute, Hi-Z, then STANDBY low for >= 15 ms before power goes
        (9.3.10.1.2)."""
        self.mute.set(0)
        try:
            self.bus.write_u8(ADDR, CH_STATE, HIZ)
        except OSError:
            pass
        self.standby.set(0)
        self.sleep(0.02)
        self.playing = False

    # -- volume / fader ----------------------------------------------------
    def set_fader(self, fader=0.0, balance=0.0):
        self.gains = fader_gains(fader, balance)
        self._write_volumes()

    def set_duck(self, db):
        """Temporary cut (reverse gear): 0 = none, e.g. -12."""
        self.duck_db = db
        self._write_volumes()

    def _write_volumes(self):
        extra = self.duck_db + self.thermal_db
        for i, ch in enumerate(CHANNELS):
            g = self.gains[ch]
            self.bus.write_u8(ADDR, VOL_BASE + i, db_to_reg(None if g is None else g + extra))

    # -- health ------------------------------------------------------------
    def read_faults(self):
        names = {}
        chf = self.bus.read_u8(ADDR, CH_FAULTS)
        g1 = self.bus.read_u8(ADDR, GLOBAL_FAULTS1)
        g2 = self.bus.read_u8(ADDR, GLOBAL_FAULTS2)
        for i, ch in enumerate(CHANNELS):
            if chf & (0x80 >> i):
                names[f"{ch} overcurrent"] = True
            if chf & (0x08 >> i):
                names[f"{ch} DC"] = True
        for bit, name in ((4, "clock"), (3, "PVDD over-voltage"), (2, "VBAT over-voltage"),
                          (1, "PVDD under-voltage"), (0, "VBAT under-voltage")):
            if g1 & (1 << bit):
                names[name] = True
        if g2 & 0x1F:
            names["over-temperature shutdown"] = True
        return names

    def check(self):
        """Poll from the service loop. Returns a status dict; recovers from
        latched faults with backoff handled by the caller."""
        fault = not self.fault.get()                 # FAULT is active low
        warn = not self.warn.get()
        status = {"playing": self.playing, "fault": fault, "warn": warn}
        if warn:
            w = self.bus.read_u8(ADDR, WARNINGS)
            status["overtemp_warning"] = bool(w & 0x1F)
        if fault:
            self.last_fault = self.read_faults()
            status["faults"] = self.last_fault
        return status

    def set_thermal_cut(self, db):
        if db != self.thermal_db:
            self.thermal_db = db
            self._write_volumes()
