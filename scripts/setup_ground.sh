#!/bin/bash
# Install the ground side: the Python venv for the pilot/dashboard/tests, and Open MCT with the Yamcs plugin.
# Linux, macOS, inside WSL, or Git Bash on Windows. Safe to re-run.
#
#   scripts/setup_ground.sh            both
#   scripts/setup_ground.sh python     ground/.venv only
#   scripts/setup_ground.sh openmct    Open MCT only (needs Node.js 24.14.1+ and npm)
#
# Open MCT and the plugin are pinned to the commits this project was verified with.
set -e
. "$(dirname "$0")/common.sh"
OPENMCT_YAMCS_REF=869740b     # akhenry/openmct-yamcs, "Feature execution monitoring provider (#560)"
OPENMCT_REF=e1a65cd           # nasa/openmct master, "Add support for telemetry driven execution monitoring (#8427)"
say() { printf '\n== %s\n' "$*"; }

python_env() {
  say "ground/.venv"
  cd "$DOOMSAT_REPO/ground"
  PY=python3; command -v python3 >/dev/null 2>&1 && python3 -c '' 2>/dev/null || PY=python
  [ -d .venv ] || "$PY" -m venv .venv
  VPY=.venv/bin/python; [ -x "$VPY" ] || VPY=.venv/Scripts/python
  "$VPY" -m pip install -q --upgrade pip
  "$VPY" -m pip install -q -r requirements.txt
  echo "ground venv ready: $VPY"
}

openmct() {
  command -v node >/dev/null || { echo "missing: node (Node.js 24.14.1+; see README)"; exit 1; }
  node -e 'const [a,b,c]=process.versions.node.split(".").map(Number); process.exit(a>24||(a==24&&(b>14||(b==14&&c>=1)))?0:1)' \
    || echo "warning: Node $(node --version) is older than the 24.14.1 the plugin asks for; continuing with engine-strict off"
  export npm_config_engine_strict=false
  D="$DOOMSAT_REPO/external/openmct-yamcs"
  if [ ! -d "$D/.git" ]; then
    say "openmct-yamcs @ $OPENMCT_YAMCS_REF"
    mkdir -p "$DOOMSAT_REPO/external"
    git -c core.longpaths=true clone -q --no-checkout https://github.com/akhenry/openmct-yamcs "$D"
    git -C "$D" -c core.longpaths=true checkout -q "$OPENMCT_YAMCS_REF"
  fi
  cd "$D"
  [ -d node_modules/webpack ] || { say "npm ci (openmct-yamcs)"; npm ci --no-audit --no-fund; }
  if [ ! -f node_modules/openmct/dist/openmct.js ]; then
    say "Open MCT @ $OPENMCT_REF (clone + production build, a few minutes)"
    rm -rf node_modules/openmct
    # core.longpaths: Open MCT's test snapshots have paths past Windows' 260-character limit
    git -c core.longpaths=true clone -q --no-checkout https://github.com/nasa/openmct.git node_modules/openmct
    git -C node_modules/openmct -c core.longpaths=true checkout -q "$OPENMCT_REF"
    (cd node_modules/openmct && npm ci --no-audit --no-fund && npm run build:prod)
  fi
  echo "Open MCT ready. Run: scripts/start_openmct.sh  (needs Yamcs on :8090)"
}

case "${1:-all}" in
  python)  python_env ;;
  openmct) openmct ;;
  all)     python_env; openmct ;;
  *) echo "usage: $0 [all|python|openmct]"; exit 2 ;;
esac
