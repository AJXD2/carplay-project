# Sourced by deploy scripts to show a progress card on the Pi's screen
# (xsplash.py progress), so whoever is in the car can see an update is
# running and knows not to cut the power. Every call is best effort: no X,
# no card, and the deploy carries on.
#
#   onscreen_start <host> <title> <done title>
#   onscreen <pct> <target> <seconds> <message>   see xsplash.py for the fields
#   onscreen_fail_on_error                        red card if the script dies
#
# The card runs from a copy in /tmp so the launcher deploy's pkill of
# /home/ajxd2/launcher/* can't take it down. Messages must not contain '.

_ONSCREEN_STATE=/tmp/xsplash-progress
_ONSCREEN_HOST=

onscreen_start() {
  _ONSCREEN_HOST="$1"
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  ssh "$_ONSCREEN_HOST" "cat > /tmp/xsplash.py" < "$here/xsplash.py" || return 0
  ssh "$_ONSCREEN_HOST" "rm -f $_ONSCREEN_STATE; DISPLAY=:0 setsid python3 /tmp/xsplash.py progress $_ONSCREEN_STATE '$2' '$3' </dev/null >/tmp/xsplash-progress.log 2>&1 &" || true
}

onscreen() {
  [[ -n "$_ONSCREEN_HOST" ]] || return 0
  ssh "$_ONSCREEN_HOST" "printf '%s\n' '$1 $2 $3 $4' > $_ONSCREEN_STATE.new && mv $_ONSCREEN_STATE.new $_ONSCREEN_STATE" || true
}

onscreen_fail_on_error() {
  trap 'onscreen -1 0 1 "Nothing was changed after the failed step."' ERR
}
