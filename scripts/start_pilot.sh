#!/bin/bash
# Run the ground pilot on Windows (Git Bash). Extra arguments are passed to pilot.py (see --help).
cd "$(dirname "$0")/../ground" || exit 1
export PYTHONUTF8=1   # Sonnet writes arrows and dashes; the Windows console codepage cannot print them
exec .venv/Scripts/python pilot.py "$@"
