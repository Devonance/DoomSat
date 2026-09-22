#!/bin/bash
# Create the DoomSat deployment (TcpClient com driver) inside the bootstrapped F´ project and run a baseline build.
set -e
cd /root/doom/DoomSat
. fprime-venv/bin/activate
if [ ! -d DoomSat ]; then
  printf "DoomSat\n\n1\nyes\n" | fprime-util new --deployment
fi
ls DoomSat DoomSat/Top
grep -n "DoomSat" CMakeLists.txt project.cmake 2>/dev/null || true
fprime-util generate 2>&1 | tail -3
echo GENERATE_DONE
fprime-util build -j 24 2>&1 | tail -5
echo BUILD_DONE
ls build-artifacts/Linux/DoomSat/bin build-artifacts/Linux/DoomSat/dict
