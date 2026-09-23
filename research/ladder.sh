#!/bin/bash
# The oracle ladder of the 23 September brief, section 5. Diagnostic only: every attempt is stamped with
# its rung, grade.py refuses to summarise it, and no row ever reaches the ledger.
#
# Dev maps only. An oracle run on a shareware level would put level knowledge into a record that is
# supposed to be scored, and the brief forbids it for that reason.
#
#   L0  true geometry for the whole level, plus the exit. Tests the executor, the INTENT loop, the path.
#   L1  true geometry for seen lines only, exit revealed once in view within 256 units. Tests exploring.
#   L2  the stack as flown.
#
#   bash research/ladder.sh <out-prefix> [seeds]
set -u
REPO=/mnt/c/Users/Kevin/Genai/DoomSat
PY=/root/doom/payload-venv/bin/python
PREFIX=${1:-ladder}
SEEDS=${2:-"1 2 3"}
cd "$REPO" || exit 1
export DOOMSAT_HARNESS=$REPO
for RUNG in L0 L1 L2; do
  OUT=research/out/${PREFIX}-${RUNG}
  echo "=== $RUNG -> $OUT ==="
  $PY research/runner.py bench --set dev --maps E1M1 E1M2 --seeds $SEEDS \
      --decider code --oracle "$RUNG" --out "$OUT" --allow-dirty --grade \
      > "/root/doom/run/night/${PREFIX}-${RUNG}.log" 2>&1
  echo "exit $? -- $(grep -c 'game s,' "/root/doom/run/night/${PREFIX}-${RUNG}.log") attempts"
done
