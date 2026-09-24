#!/bin/sh
# Rebuild carrier.kicad_pcb from the schematic: placement, planes and hand
# routes, Freerouting for the rest, then DRC. Takes a few minutes.
#   tools/build_board.sh            full chain
#   tools/build_board.sh noauto     stop before the autorouter
set -e
cd "$(dirname "$0")/.."
KPY="flatpak run --command=python3 org.kicad.KiCad"
FR="$HOME/.local/share/freerouting/freerouting-2.4.1.jar"
$KPY tools/gen_pcb.py 2>&1 | grep -v Warn | tail -1
$KPY tools/route.py 2>&1 | grep -v Warn | tail -1
if [ "$1" != noauto ]; then
    $KPY tools/autoroute.py export 2>&1 | grep -v Warn | tail -1
    java -jar "$FR" -de out/route/carrier.dsn -do out/route/carrier.ses -mp ${PASSES:-40} \
        --gui.enabled=false > out/route/freerouting.log 2>&1
    tail -3 out/route/freerouting.log
    $KPY tools/autoroute.py import 2>&1 | grep -v Warn | tail -1
    cp carrier.kicad_pcb out/route/imported.kicad_pcb
fi
kicad-cli pcb drc --schematic-parity --format json -o out/drc.json carrier.kicad_pcb > /dev/null
if [ "$1" != noauto ]; then
    for pass in 1 2 3; do
        $KPY tools/finish.py repair 2>&1 | grep "finish:"
        kicad-cli pcb drc --schematic-parity --format json -o out/drc.json carrier.kicad_pcb > /dev/null
        $KPY tools/finish.py 2>&1 | grep "finish:"
        kicad-cli pcb drc --schematic-parity --format json -o out/drc.json carrier.kicad_pcb > /dev/null
    done
fi
python3 tools/drc_summary.py
