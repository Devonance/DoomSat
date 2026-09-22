#!/bin/bash
cd /mnt/c/Users/Kevin/Genai/doom-mission/payload
timeout 12 /root/doom/payload-venv/bin/python doom_payload.py --fps 10 --quality 45 --wad doom1.wad --map E1M1 --map-png /mnt/c/Users/Kevin/Genai/doom-mission/out/payload_map.png 2>&1 | tail -15
