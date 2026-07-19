#!/usr/bin/env python3
import pygame, subprocess, sys, time, re

W, H = 800, 480
pygame.init()
pygame.display.set_caption("info")
screen = pygame.display.set_mode((W, H), pygame.NOFRAME)
pygame.mouse.set_visible(False)
clock = pygame.time.Clock()
title_font = pygame.font.SysFont("dejavusans", 27, bold=True)
row_font = pygame.font.SysFont("dejavusans", 17)
mono_font = pygame.font.SysFont("dejavusansmono", 17)

# matches launcher.py / pi-monitor/dunstrc's "Refined Card" palette
BG = (19, 19, 19)
TILE_BORDER = (58, 58, 58)
TEXT_PRIMARY = (240, 240, 240)
TEXT_MUTED = (160, 160, 168)


def sh(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "?"


def get_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return f"{int(f.read().strip()) / 1000:.1f}°C"
    except Exception:
        return "?"


def get_throttled():
    out = sh("vcgencmd get_throttled")
    m = re.search(r"0x([0-9a-fA-F]+)", out)
    if not m:
        return "?"
    bits = int(m.group(1), 16)
    flags = []
    if bits & 0x1:
        flags.append("UNDERVOLTAGE NOW")
    if bits & 0x2:
        flags.append("FREQ CAPPED NOW")
    if bits & 0x4:
        flags.append("THROTTLED NOW")
    if bits & 0x10000:
        flags.append("undervoltage occurred")
    if bits & 0x20000:
        flags.append("freq capped occurred")
    if bits & 0x40000:
        flags.append("throttled occurred")
    return ", ".join(flags) if flags else "OK"


def get_ip(iface):
    out = sh(f"ip -4 -o addr show {iface}")
    m = re.search(r"inet (\S+)/", out)
    return m.group(1) if m else "not connected"


def get_uptime():
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
        h, rem = divmod(int(secs), 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m}m {s}s"
    except Exception:
        return "?"


def get_mem():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                info[k.strip()] = int(v.strip().split()[0])
        total = info["MemTotal"] / 1024 / 1024
        avail = info["MemAvailable"] / 1024 / 1024
        used = total - avail
        return f"{used:.2f} / {total:.2f} GB"
    except Exception:
        return "?"


def get_disk():
    out = sh("df -h / --output=used,size,pcent | tail -1")
    return " / ".join(out.split()) if out != "?" else "?"


def get_load():
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()[:3]
        return " ".join(parts)
    except Exception:
        return "?"


def get_volume():
    out = sh("pactl get-sink-volume @DEFAULT_SINK@")
    m = re.search(r"(\d+)%", out)
    return f"{m.group(1)}%" if m else "?"


def rows():
    return [
        ("Hostname", sh("hostname")),
        ("Uptime", get_uptime()),
        ("CPU Temp", get_temp()),
        ("Throttle Status", get_throttled()),
        ("Load Average", get_load()),
        ("Memory Used", get_mem()),
        ("Disk Used", get_disk()),
        ("Ethernet IP", get_ip("eth0")),
        ("Wi-Fi IP", get_ip("wlan0")),
        ("Volume", get_volume()),
    ]


last_refresh = 0
data = rows()

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False

    now = time.time()
    if now - last_refresh >= 1.0:
        data = rows()
        last_refresh = now

    screen.fill(BG)
    title = title_font.render("Pi Status", True, TEXT_PRIMARY)
    screen.blit(title, (28, 24))
    pygame.draw.line(screen, TILE_BORDER, (28, 66), (W - 28, 66), 1)

    y = 84
    for label, value in data:
        label_surf = row_font.render(label, True, TEXT_MUTED)
        value_surf = mono_font.render(str(value), True, TEXT_PRIMARY)
        screen.blit(label_surf, (36, y))
        screen.blit(value_surf, (300, y))
        pygame.draw.line(screen, (32, 32, 40), (36, y + 30), (W - 36, y + 30), 1)
        y += 38

    pygame.display.flip()
    clock.tick(15)

pygame.quit()
sys.exit()
