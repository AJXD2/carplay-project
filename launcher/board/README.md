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

Not part of `deploy.sh` yet, since nothing here should run without the board.

1. Append `system/config.txt` to `/boot/firmware/config.txt`.
2. `sudo apt install device-tree-compiler`, then
   `sudo dtc -@ -I dts -O dtb -o /boot/firmware/overlays/carrier-audio.dtbo system/carrier-audio-overlay.dts`.
3. PulseAudio must run at the board's fixed 48 kHz: in `/etc/pulse/daemon.conf`
   set `default-sample-rate = 48000` and `alternate-sample-rate = 48000`.
4. Copy `board/` to `/home/ajxd2/launcher/board`, install
   `system/carrierd.service` to `/etc/systemd/system/`, `systemctl enable carrierd`.
5. Persist all of the above to `/media/root-ro` (see INFO.md), reboot.
6. Learn the steering wheel: `curl -X POST 127.0.0.1:8735/learn/start`, press
   each button as `GET /state` prompts (`/learn/skip` for buttons the wheel
   lacks). A launcher screen for this comes with the board bring-up.

Things to confirm on the real hardware: the CarPlay window class used for
key injection (`carplay_window_class`, default `react-carplay`) and the
wheel's button readings.
