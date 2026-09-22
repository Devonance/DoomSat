#!/bin/bash
# Start (or restart) the flight side inside WSL: Doom payload + Yamcs (fprime-yamcs) + the DoomSat binary.
# Usage: wsl_run_flight.sh [start|stop|status|payload]   (payload = restart only the game process)
RUN=/root/doom/run
PROJ=/root/doom/doom-mission
REPO=/mnt/c/Users/Kevin/Genai/doom-mission
mkdir -p $RUN
stop() {
  pkill -f "doom_payloa[d].py" 2>/dev/null
  pkill -f "fprime_yamc[s]" 2>/dev/null
  pkill -f "YamcsServe[r]" 2>/dev/null
  pkill -f "bin/DoomSa[t]" 2>/dev/null
  sleep 1
}
case "${1:-start}" in
  stop) stop; echo stopped ;;
  payload)
    pkill -f "doom_payloa[d].py" 2>/dev/null; sleep 1
    cd $PROJ
    nohup /root/doom/payload-venv/bin/python $REPO/payload/doom_payload.py --fps ${FPS:-10} --quality ${QUALITY:-45} --map-png /mnt/c/Users/Kevin/Genai/doom-mission/out/payload_map.png > $RUN/payload.log 2>&1 &
    echo "payload restarted" ;;
  status)
    ps aux | grep -E "doom_payloa[d]|fprime_yamc[s]|YamcsServe[r]|bin/DoomSa[t]" | awk '{print $11, $12, $13}' | sort | uniq -c
    curl -s http://localhost:8090/api/instances | grep -c '"name": "fprime-project"' ;;
  start)
    stop
    cd $PROJ
    nohup /root/doom/payload-venv/bin/python $REPO/payload/doom_payload.py --fps ${FPS:-10} --quality ${QUALITY:-45} --map-png /mnt/c/Users/Kevin/Genai/doom-mission/out/payload_map.png > $RUN/payload.log 2>&1 &
    . fprime-venv/bin/activate
    export FPRIME_DOWNLINK_DIR=$RUN/downlink
    nohup fprime-yamcs --deployment build-artifacts/Linux/DoomSat --skip-browser-open \
        --yamcs-config-dir $REPO/ground/yamcs --yamcs-data-dir $RUN/yamcs-data \
        --yamcs-realtime-only-channels "DoomSat.doom.FRAME_CHUNK" > $RUN/yamcs.log 2>&1 &
    echo "started; logs in $RUN" ;;
esac
