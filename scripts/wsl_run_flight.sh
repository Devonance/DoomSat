#!/bin/bash
# Start (or restart) the flight side inside WSL: Doom payload + Yamcs (fprime-yamcs) + the DoomSat binary.
# Usage: wsl_run_flight.sh [start|stop|status|payload]   (payload = restart only the game process)
RUN=/root/doom/run
PROJ=/root/doom/DoomSat
REPO=/mnt/c/Users/Kevin/Genai/DoomSat
# GEOMETRY=on   exact lines, gated on the automap having drawn them (payload/seen_geometry.py)
# ORACLE=L0|L1  the diagnostic ladder. Never on a shareware level, and never scored.
# WAD=, MAP=    which level. A dev flight is WAD=freedoom1.wad.
mkdir -p $RUN
stop() {
  pkill -f "doom_payloa[d].py --fps" 2>/dev/null
  pkill -f "fprime_yamc[s]" 2>/dev/null
  pkill -f "YamcsServe[r]" 2>/dev/null
  pkill -f "bin/DoomSa[t]" 2>/dev/null
  sleep 1
}
case "${1:-start}" in
  stop) stop; echo stopped ;;
  payload)
    pkill -f "doom_payloa[d].py --fps" 2>/dev/null; sleep 1
    cd $PROJ
    setsid -f bash -c "/root/doom/payload-venv/bin/python $REPO/payload/doom_payload.py --fps ${FPS:-10} --quality ${QUALITY:-45} --skill ${SKILL:-3} --wad ${WAD:-doom1.wad} --map ${MAP:-E1M1} --geometry ${GEOMETRY:-off} --oracle ${ORACLE:-off} --map-png /mnt/c/Users/Kevin/Genai/DoomSat/out/payload_map.png > $RUN/payload.log 2>&1" < /dev/null
    echo "payload restarted" ;;
  status)
    ps aux | grep -E "doom_payloa[d]|fprime_yamc[s]|YamcsServe[r]|bin/DoomSa[t]" | awk '{print $11, $12, $13}' | sort | uniq -c
    curl -s http://localhost:8090/api/instances | grep -c '"name": "fprime-project"' ;;
  start)
    stop
    cd $PROJ
    # --skill must match research/levels.yaml run.skill, or the bench and the flight stack are playing
    # different games and their numbers cannot be compared. tests/test_runner.py pins the two together.
    setsid -f bash -c "/root/doom/payload-venv/bin/python $REPO/payload/doom_payload.py --fps ${FPS:-10} --quality ${QUALITY:-45} --skill ${SKILL:-3} --wad ${WAD:-doom1.wad} --map ${MAP:-E1M1} --geometry ${GEOMETRY:-off} --oracle ${ORACLE:-off} --map-png /mnt/c/Users/Kevin/Genai/DoomSat/out/payload_map.png > $RUN/payload.log 2>&1" < /dev/null
    . fprime-venv/bin/activate
    export FPRIME_DOWNLINK_DIR=$RUN/downlink
    setsid -f bash -c "cd $PROJ && . fprime-venv/bin/activate && export FPRIME_DOWNLINK_DIR=$RUN/downlink && fprime-yamcs --deployment build-artifacts/Linux/DoomSat --skip-browser-open --yamcs-config-dir $REPO/ground/yamcs --yamcs-data-dir $RUN/yamcs-data --yamcs-realtime-only-channels DoomSat.doom.FRAME_CHUNK > $RUN/yamcs.log 2>&1" < /dev/null
    echo "started; logs in $RUN" ;;
esac
