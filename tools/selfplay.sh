#!/bin/bash
cd /mnt/c/Users/Kevin/Genai/DoomSat/payload && DOOM_DEBUG_PLAN=${DEBUG:-} DOOM_DEBUG_TRACE=${TRACE:-} /root/doom/payload-venv/bin/python selfplay.py "$@"
