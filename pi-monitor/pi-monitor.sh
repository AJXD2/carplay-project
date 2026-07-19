#!/bin/bash
# Polls CPU temp + eth0 connectivity and pops up dunst notifications.
# Runs inside the X session (started from openbox autostart), so it
# inherits DISPLAY and DBUS_SESSION_BUS_ADDRESS for notify-send.

set -u

POLL_INTERVAL=10
TEMP_WARN_C=70
TEMP_CRIT_C=80
RENOTIFY_INTERVAL=300   # re-alert every 5 min while still hot
THERMAL_FILE=/sys/class/thermal/thermal_zone0/temp
IFACE=eth0

notify() {
  local urgency="$1" title="$2" body="$3"
  notify-send -a "Pi Monitor" -u "$urgency" -t 8000 "$title" "$body"
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

    if [ "$new_state" != "ok" ]; then
      if [ "$new_state" != "$temp_state" ] || [ $(( now - last_temp_notify )) -ge "$RENOTIFY_INTERVAL" ]; then
        if [ "$new_state" = "crit" ]; then
          notify critical "Pi overheating: ${temp_c}°C" "Above ${TEMP_CRIT_C}°C — throttling likely."
        else
          notify normal "Pi running hot: ${temp_c}°C" "Above ${TEMP_WARN_C}°C warning threshold."
        fi
        last_temp_notify=$now
      fi
    elif [ "$temp_state" != "ok" ]; then
      notify normal "Pi temp back to normal" "${temp_c}°C"
    fi
    temp_state="$new_state"
  fi

  # --- ethernet IP ---
  cur_ip=$(ip -4 -o addr show "$IFACE" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1)
  if [ -n "$cur_ip" ] && [ "$cur_ip" != "$last_ip" ]; then
    notify normal "Ethernet connected" "${IFACE}: ${cur_ip}"
  fi
  last_ip="$cur_ip"

  sleep "$POLL_INTERVAL"
done
