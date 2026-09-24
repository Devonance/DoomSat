#!/bin/bash
# Sourced by the other scripts. Works out where things live, the same way on Linux, macOS and inside WSL.
#
#   DOOMSAT_REPO   this checkout (worked out from the script's own path)
#   DOOMSAT_HOME   where the flight side is installed: the F´ project, the ViZDoom venv, the WADs,
#                  the run logs. Default ~/doom, which is /root/doom for a root shell in WSL.
#   DOOMSAT_OS     the F´ platform name the build writes into build-artifacts/ (Linux or Darwin)
#
# DOOMSAT_* lines in the repo's .env are read here, so one file configures every script.
DOOMSAT_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$DOOMSAT_REPO/.env" ]; then
  while IFS='=' read -r k v || [ -n "$k" ]; do
    case "$k" in DOOMSAT_*) [ -z "${!k:-}" ] && export "$k=$(printf '%s' "$v" | tr -d "\"'\r")" ;; esac
  done < "$DOOMSAT_REPO/.env"
fi
export DOOMSAT_REPO
export DOOMSAT_HOME="${DOOMSAT_HOME:-$HOME/doom}"
export DOOMSAT_OS="$(uname -s)"
PROJ="$DOOMSAT_HOME/DoomSat"          # the F´ project (fprime-bootstrap output)
PAYLOAD_PY="$DOOMSAT_HOME/payload-venv/bin/python"
WADS="$DOOMSAT_HOME/wads"
RUN="$DOOMSAT_HOME/run"
DEPLOY="build-artifacts/$DOOMSAT_OS/DoomSat"
