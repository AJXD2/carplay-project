# Sourced by deploy scripts to show an update view on the Pi's screen
# (xsplash.py progress): full screen at first, shrinking to a small card
# when tapped, with a short chime at the start. It tells whoever is in the
# car an update is running and not to cut the power. Every call is best
# effort: no X, no sound, no view, and the deploy carries on.
#
#   onscreen_start <host> <title> <done title>
#   onscreen <pct> <target> <seconds> <message>   see xsplash.py for the fields
#   onscreen_fail_on_error                        red card if the script dies
#
# The view runs from a copy in /tmp (with the chime WAVs beside it) so the
# launcher deploy's pkill of /home/ajxd2/launcher/* can't take it down.
# Messages must not contain '.

_ONSCREEN_STATE=/tmp/xsplash-progress
_ONSCREEN_HOST=

onscreen_start() {
  _ONSCREEN_HOST="$1"
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  ssh "$_ONSCREEN_HOST" "cat > /tmp/xsplash.py" < "$here/xsplash.py" || return 0
  # The chimes are optional: xsplash.py skips any that aren't there.
  tar -C "$here" -cf - update-chime.wav update-done.wav 2>/dev/null |
    ssh "$_ONSCREEN_HOST" "tar -C /tmp -xf -" || true
  # The card closes when it finds no state file, so seed one before it
  # starts; deleting it here let a fast card exit before the first onscreen.
  ssh "$_ONSCREEN_HOST" "printf '%s\n' '0 2 1 Starting.' > $_ONSCREEN_STATE; DISPLAY=:0 setsid python3 /tmp/xsplash.py progress $_ONSCREEN_STATE '$2' '$3' </dev/null >/tmp/xsplash-progress.log 2>&1 &" || true
}

onscreen() {
  [[ -n "$_ONSCREEN_HOST" ]] || return 0
  ssh "$_ONSCREEN_HOST" "printf '%s\n' '$1 $2 $3 $4' > $_ONSCREEN_STATE.new && mv $_ONSCREEN_STATE.new $_ONSCREEN_STATE" || true
}

onscreen_fail_on_error() {
  trap 'onscreen -1 0 1 "Nothing was changed after the failed step."' ERR
}
