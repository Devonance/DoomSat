#!/bin/bash
# Sync the flight sources and build the DoomSat deployment (run inside WSL).
set -e
bash /mnt/c/Users/Kevin/Genai/doom-mission/scripts/wsl_sync.sh
cd /root/doom/doom-mission
. fprime-venv/bin/activate
fprime-util build -j 24 2>&1 | grep -v "^\s*$" | grep -i -E "error|warning: unused|FAILED|Doom\.cpp|BUILD_DONE|Installing: .*DoomSat/bin" | grep -v "fprime-gds has unexpected" | head -60
echo "BUILD_EXIT ${PIPESTATUS[0]}"
ls -la build-artifacts/Linux/DoomSat/bin/DoomSat build-artifacts/Linux/DoomSat/dict/DoomSatTopologyDictionary.json
