#!/bin/bash
# One measurement, start to finish, with the machine cleared first. Written because every run tonight
# that was taken without reaping first was taken on a machine with thirty-odd orphaned games on it.
#
#   bash research/night.sh <out-name> <decider> <geometry> [extra runner args...]
#
#   bash research/night.sh t3-geom-code code on
#   bash research/night.sh t3-geom-jev  jev  on --maps E1M1 E1M2 E1M3
set -u
REPO=/mnt/c/Users/Kevin/Genai/DoomSat
PY=/root/doom/payload-venv/bin/python
NAME=${1:?out name}
DECIDER=${2:-code}
GEOM=${3:-off}
shift 3 || true
cd "$REPO" || exit 1
export DOOMSAT_HARNESS=$REPO
$PY research/reap.py --keep-younger-than 120
LOG=/root/doom/run/night/${NAME}.log
$PY research/runner.py bench --set dev --seeds 1 2 3 --decider "$DECIDER" --geometry "$GEOM" \
    --out "research/out/${NAME}" --allow-dirty --grade "$@" > "$LOG" 2>&1
echo "exit $?"
grep -E "^E1M|^suite score|guardrail|decisions by reason" "$LOG" | tail -20
