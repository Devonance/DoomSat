#!/bin/bash
# Start (or restart) the flight side: Doom payload + Yamcs (fprime-yamcs) + the DoomSat binary.
# Linux, macOS or inside WSL; on Windows call scripts/flight.sh, which forwards here.
# Usage: wsl_run_flight.sh [start|yamcs|stop|status|payload]
#   start    payload + F´ + Yamcs
#   yamcs    F´ + Yamcs only, no game (for Yamcs / Open MCT on their own; the Doom channels stay still)
#   payload  restart only the game process (after editing the payload)
. "$(dirname "$0")/common.sh"
REPO=$DOOMSAT_REPO
# GEOMETRY=on   exact lines, gated on the automap having drawn them (payload/seen_geometry.py)
# ORACLE=L0|L1  the diagnostic ladder. Never on a shareware level, and never scored.
# WAD=, MAP=    which level. A dev flight is WAD=freedoom1.wad.
mkdir -p "$RUN" "$REPO/out"
stop() {
  pkill -f "doom_payloa[d].py --fps" 2>/dev/null
  pkill -f "fprime_yamc[s]" 2>/dev/null
  pkill -f "YamcsServe[r]" 2>/dev/null
  pkill -f "bin/DoomSa[t]" 2>/dev/null
  pkill -f "fprime-gd[s] " 2>/dev/null; pkill -f "fprime_gds[.]executables" 2>/dev/null   # flight.sh gds
  sleep 1
}
# Detached, so it outlives this shell. setsid -f in WSL: anything started with plain nohup inside a
# `wsl bash -c` call dies when that call returns. macOS has no setsid; nohup is enough there.
detach() {
  if command -v setsid >/dev/null; then setsid -f bash -c "$1" < /dev/null
  else nohup bash -c "$1" < /dev/null > /dev/null 2>&1 & fi
}
start_payload() {
  # --skill must match research/levels.yaml run.skill, or the bench and the flight stack are playing
  # different games and their numbers cannot be compared. tests/test_runner.py pins the two together.
  cd "$PROJ" || exit 1
  detach "'$PAYLOAD_PY' '$REPO'/payload/doom_payload.py --fps ${FPS:-10} --quality ${QUALITY:-45} --skill ${SKILL:-3} --wad ${WAD:-doom1.wad} --map ${MAP:-E1M1} --geometry ${GEOMETRY:-off} --oracle ${ORACLE:-off} --map-png '$REPO/out/payload_map.png' > '$RUN/payload.log' 2>&1"
}
start_yamcs() {
  cd "$PROJ" || exit 1
  detach "cd '$PROJ' && . fprime-venv/bin/activate && export FPRIME_DOWNLINK_DIR='$RUN/downlink' && fprime-yamcs --deployment $DEPLOY --skip-browser-open --yamcs-config-dir '$REPO/ground/yamcs' --yamcs-data-dir '$RUN/yamcs-data' --yamcs-realtime-only-channels DoomSat.doom.FRAME_CHUNK > '$RUN/yamcs.log' 2>&1"
}
case "${1:-start}" in
  stop) stop; echo stopped ;;
  payload)
    pkill -f "doom_payloa[d].py --fps" 2>/dev/null; sleep 1
    start_payload; echo "payload restarted" ;;
  status)
    ps aux | grep -E "doom_payloa[d]|fprime_yamc[s]|YamcsServe[r]|bin/DoomSa[t]" | awk '{print $11, $12, $13}' | sort | uniq -c
    curl -s http://localhost:8090/api/instances | grep -c '"name": "fprime-project"' ;;
  start) stop; start_payload; start_yamcs; echo "started; logs in $RUN; Yamcs on http://localhost:8090 in ~30 s" ;;
  yamcs) stop; start_yamcs; echo "F´ + Yamcs started (no game); logs in $RUN; Yamcs on http://localhost:8090 in ~30 s" ;;
  *) echo "usage: $0 [start|yamcs|stop|status|payload]"; exit 2 ;;
esac
