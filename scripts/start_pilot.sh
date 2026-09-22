#!/bin/bash
# Run the ground pilot on Windows (Git Bash). Extra arguments are passed to pilot.py (see --help).
cd "$(dirname "$0")/../ground" || exit 1
exec .venv/Scripts/python pilot.py "$@"
