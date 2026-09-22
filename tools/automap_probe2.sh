#!/bin/bash
cd /mnt/c/Users/Kevin/Genai/DoomSat/payload
W=$(/root/doom/payload-venv/bin/python -c 'import vizdoom,os;print(os.path.dirname(vizdoom.__file__))')
/root/doom/payload-venv/bin/python automap_probe2.py $W/freedoom2.wad MAP01 fd2m1 "216,-720,90" "216,-560,270" "-192,-192,0"
/root/doom/payload-venv/bin/python automap_probe2.py $W/freedoom1.wad E1M1 fd1m1 "-400,1200,90" "-416,256,0"
