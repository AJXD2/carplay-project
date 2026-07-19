#!/bin/bash
# Polls CPU temp + eth0 connectivity and pops up dunst notifications.
# Runs inside the X session (started from openbox autostart), so it
# inherits DISPLAY and DBUS_SESSION_BUS_ADDRESS for notify-send.

set -u

POLL_INTERVAL=10
TEMP_WARN_C=70
TEMP_CRIT_C=80
RENOTIFY_INTERVAL=300      # re-alert every 5 min while still hot (warning)
RENOTIFY_INTERVAL_CRIT=60  # re-alert every 1 min while critical, harder to ignore
THERMAL_FILE=/sys/class/thermal/thermal_zone0/temp
IFACE=eth0
ALERT_SOUND="$(dirname "$0")/assets/critical-beep.wav"
ALERT_VOLUME=150%   # boost the beep itself above unity gain
ICON_DIR="$(dirname "$0")/assets/icons"
ICON_INFO="$ICON_DIR/info.png"
ICON_WARNING="$ICON_DIR/warning.png"

# Fully mute the CarPlay audio stream, play the alert beep over it, then
# unmute. A partial duck still lets the beep get lost in the music; a
# critical alert needs to actually interrupt, not compete.
play_critical_alert() {
  [ -r "$ALERT_SOUND" ] || return 0

  local carplay_idx
  carplay_idx=$(pactl list sink-inputs 2>/dev/null | awk '
    /^Sink Input #/ { idx=$3; sub("#","",idx) }
    /application.process.binary = "react-carplay"/ { print idx }
  ' | head -n1)

  if [ -n "$carplay_idx" ]; then
    pactl set-sink-input-mute "$carplay_idx" 1 2>/dev/null
  fi

  paplay --volume=$(( 65536 * ${ALERT_VOLUME%\%} / 100 )) "$ALERT_SOUND" >/dev/null 2>&1

  if [ -n "$carplay_idx" ]; then
    pactl set-sink-input-mute "$carplay_idx" 0 2>/dev/null
  fi
}

notify() {
  local urgency="$1" title="$2" body="$3" icon="$4"
  notify-send -a "Pi Monitor" -u "$urgency" -i "$icon" -t 8000 "$title" "$body"
  if [ "$urgency" = "critical" ]; then
    play_critical_alert &
  fi
}

temp_state="ok"
last_temp_notify=0
last_ip=""

while true; do
  # --- temperature ---
  if [ -r "$THERMAL_FILE" ]; then
    raw=$(cat "$THERMAL_FILE")
    temp_c=$(( raw / 1000 ))
    now=$(date +%s)

    if [ "$temp_c" -ge "$TEMP_CRIT_C" ]; then
      new_state="crit"
    elif [ "$temp_c" -ge "$TEMP_WARN_C" ]; then
      new_state="warn"
    else
      new_state="ok"
    fi

    if [ "$new_state" = "crit" ]; then
      if [ "$new_state" != "$temp_state" ] || [ $(( now - last_temp_notify )) -ge "$RENOTIFY_INTERVAL_CRIT" ]; then
        notify critical "Thermal Critical" "CPU at ${temp_c}°C. Throttling likely above ${TEMP_CRIT_C}°C." "$ICON_WARNING"
        last_temp_notify=$now
      fi
    elif [ "$new_state" = "warn" ]; then
      if [ "$new_state" != "$temp_state" ] || [ $(( now - last_temp_notify )) -ge "$RENOTIFY_INTERVAL" ]; then
        notify normal "Thermal Warning" "CPU at ${temp_c}°C, above ${TEMP_WARN_C}°C threshold." "$ICON_WARNING"
        last_temp_notify=$now
      fi
    elif [ "$temp_state" != "ok" ]; then
      notify normal "Temperature Normal" "CPU back to ${temp_c}°C." "$ICON_INFO"
    fi
    temp_state="$new_state"
  fi

  # --- ethernet IP ---
  cur_ip=$(ip -4 -o addr show "$IFACE" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1)
  if [ -n "$cur_ip" ] && [ "$cur_ip" != "$last_ip" ]; then
    notify normal "Ethernet Connected" "${IFACE}: ${cur_ip}" "$ICON_INFO"
  fi
  last_ip="$cur_ip"

  sleep "$POLL_INTERVAL"
done
