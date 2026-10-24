# carrierd: carrier board services

Software for `hardware/carrier`: the TAS6424 amp, steering-wheel buttons,
key-off shutdown, headlights/reverse inputs and the fans. Standard library
Python only; the I2C and GPIO access uses the kernel interfaces directly.

| File | What it does |
|---|---|
| `carrierd.py` | Daemon: main loop, actions, local API on `127.0.0.1:8735` |
| `tas6424.py` | Amp bring-up (datasheet order), fader, fault recovery, thermal trim |
| `swc.py` | ADS1115 reader, button decoder with hold-repeat, learn mode |
| `power.py` | Key-off timer (rides out cranking), PWM-dimmer averaging, debounce |
| `fans.py` | Fan curve, tach RPM (the PWM is inverted by the board's FET) |
| `hw.py` | I2C (`I2C_RDWR`), GPIO chardev v2, sysfs PWM, plus simulated twins |
| `sim.py` | Register models of the TAS6424 and ADS1115 |
| `system/` | `config.txt` lines, the I2S overlay, the systemd unit |

Test on any machine (the GPIO test compiles against `<linux/gpio.h>` to
check the struct layout byte for byte):

    cd launcher && python3 -m unittest board.test_board -v
    python3 -m board.carrierd --sim        # runs the loop on simulated hardware

## Install (once the board is built)

Not part of `deploy.sh`, since nothing here should run without the board.
`install.sh [--audio] [--enable] [--reboot] [user@host]` does it with the
progress card on the Pi's screen, writing through `/media/root-ro`:
i2c-tools and hwclock, `i2c-dev` at boot, `board/` and `carrierd.service`,
the audio overlay compiled onto the boot partition, and the lines from
`system/config.txt` as one managed block in `/boot/firmware/config.txt`
(backup `config.txt.carrier-bak`). Stages:

1. Default: I2C, the GPIO26 power hold, the RTC, fan PWM. CarPlay audio
   stays on the USB adapter.
2. `--audio`: adds `dtparam=audio=off` and the carrier-audio overlay. Also
   set PulseAudio to the board's fixed 48 kHz: in `/etc/pulse/daemon.conf`,
   `default-sample-rate = 48000` and `alternate-sample-rate = 48000`.
3. `--enable`: starts carrierd at boot. Until then nothing shuts the Pi
   down on key-off, and the power hold keeps the board on: don't leave it
   in the truck like that.

6. Learn the steering wheel: `curl -X POST 127.0.0.1:8735/learn/start`, press
   each button as `GET /state` prompts (`/learn/skip` for buttons the wheel
   lacks). A launcher screen for this comes with the board bring-up.

Things to confirm on the real hardware: the CarPlay window class used for
key injection (`carplay_window_class`, default `react-carplay`) and the
wheel's button readings.
