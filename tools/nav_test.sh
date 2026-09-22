#!/bin/bash
# Code-only navigation test inside WSL: a second payload instance (port 4243, no frames) driven by nav_probe.
# Usage: nav_test.sh <seconds> [wad] [map]
SECS=${1:-300}; WAD=${2:-doom1.wad}; MAP=${3:-E1M1}
PY=/root/doom/payload-venv/bin/python
REPO=/mnt/c/Users/Kevin/Genai/DoomSat
mkdir -p /root/doom/run $REPO/out
fuser -k 4243/tcp >/dev/null 2>&1; sleep 0.5
cd $REPO/payload
$PY doom_payload.py --port 4243 --fps 0 --wad $WAD --map $MAP --map-png $REPO/out/nav_test_map.png > /root/doom/run/nav_payload.log 2>&1 &
PID=$!
sleep 6
$PY nav_probe.py 4243 $SECS 2>&1 | tee $REPO/out/nav_test.log | grep -E "LEVEL|episode|levels finished|Traceback|Error" 
echo "--- payload log tail:"; tail -5 /root/doom/run/nav_payload.log
kill $PID 2>/dev/null
