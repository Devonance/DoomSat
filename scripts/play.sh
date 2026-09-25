#!/bin/bash
# Fly DoomSat without jev and without any key.
#
#   scripts/play.sh              you drive, from the dashboard: your keys go up as CONTROL commands
#                                through Yamcs and F´ to the game, and the picture comes back down
#   scripts/play.sh --autopilot  the code rules fly (the bench's code baseline, no model); you watch
#
# It starts whatever is not already running (the flight side, the dashboard server), opens the dashboard,
# and runs the pilot in the foreground. Ctrl+C stops the pilot and the dashboard server it started; the
# flight side keeps running until `scripts/flight.sh stop`.
#   --no-browser   don't open the dashboard
#   anything else  goes to ground/pilot.py, e.g. --duration 600, --no-reset, --system-two claude-cli
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/common.sh"
MODE=manual BROWSER=1 ARGS=()
for a in "$@"; do
  case "$a" in
    --autopilot) MODE=code ;;
    --no-browser) BROWSER=0 ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) ARGS+=("$a") ;;
  esac
done
Y=http://localhost:8090
DASH=http://localhost:8070
answers() { curl -s -m 2 -o /dev/null -f "$1"; }
link_up() {   # an F´ bool arrives as an enumeration: the engineering value is the string "True"
  curl -s -m 2 "$Y/api/processors/fprime-project/realtime/parameters/DoomSat_DoomSat/DoomSat/doom/PAYLOAD_LINK" \
    | grep -q '"stringValue": *"True"'
}
open_url() {
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) explorer.exe "$1" ;;
    Darwin) open "$1" ;;
    *) if grep -qi microsoft /proc/version 2>/dev/null; then explorer.exe "$1"; else xdg-open "$1"; fi ;;
  esac >/dev/null 2>&1 || true
}

# 1. The flight side: Doom + F´ + Yamcs
if ! answers "$Y/api/processors/fprime-project/realtime"; then
  echo "[play] starting the flight side (Doom + F´ + Yamcs); Yamcs takes about 30 s"
  bash "$HERE/flight.sh" start || exit 1
  printf "[play] waiting for Yamcs"
  for _ in $(seq 1 60); do answers "$Y/api/processors/fprime-project/realtime" && break; printf "."; sleep 2; done
  echo
  answers "$Y/api/processors/fprime-project/realtime" || { echo "[play] Yamcs did not come up: read $RUN/yamcs.log"; exit 1; }
fi
printf "[play] waiting for the game's telemetry"
for _ in $(seq 1 30); do link_up && break; printf "."; sleep 2; done
echo
if link_up; then echo "[play] the game is on the link"
else
  echo "[play] no game on the link yet (PAYLOAD_LINK is not True). If it stays that way, run"
  echo "       scripts/flight.sh payload   (or scripts/flight.sh check to see what is up)"
fi

# 2. The dashboard server (a static page and a proxy to Yamcs)
SERVER=""
mkdir -p "$DOOMSAT_REPO/out"
if ! answers "$DASH/"; then
  PY="$DOOMSAT_REPO/ground/.venv/bin/python"; [ -x "$PY" ] || PY="$DOOMSAT_REPO/ground/.venv/Scripts/python"
  [ -x "$PY" ] || PY=$(command -v python3 || command -v python)
  "$PY" "$DOOMSAT_REPO/tools/serve_dashboard.py" > "$DOOMSAT_REPO/out/dashboard.log" 2>&1 &
  SERVER=$!
  for _ in $(seq 1 20); do answers "$DASH/" && break; sleep 0.5; done
fi
stop_server() {
  [ -n "$SERVER" ] || return 0
  # On Windows a venv's python.exe is a launcher with the real interpreter as its child: end the whole tree.
  if [ -r "/proc/$SERVER/winpid" ]; then taskkill //F //T //PID "$(cat "/proc/$SERVER/winpid")" >/dev/null 2>&1
  else kill "$SERVER" 2>/dev/null; fi
}
trap stop_server EXIT

# 3. The pilot, in the foreground
if [ "$MODE" = manual ]; then
  echo "[play] MANUAL. Open $DASH, click the picture and drive:"
  echo "       W/S or arrows move, A/D turn, Q/E strafe, F or mouse fire, Space use, 2/3 weapon, Esc let go"
else
  echo "[play] AUTOPILOT: the code rules fly, no model. Watch at $DASH"
fi
echo "       Yamcs $Y   Open MCT: scripts/start_openmct.sh, then http://localhost:9000   Ctrl+C stops"
[ "$BROWSER" = 1 ] && open_url "$DASH/"
bash "$HERE/start_pilot.sh" --system-one "$MODE" --system-two none "${ARGS[@]}"
