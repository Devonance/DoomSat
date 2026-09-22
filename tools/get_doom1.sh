#!/bin/bash
cd /root/doom/wads
rm -f doom1.wad
for u in "https://deb.debian.org/debian/pool/non-free/d/doom-wad-shareware/doom-wad-shareware_1.9.fixed-2_all.deb" ; do
  curl -sSL -o dws.deb "$u" && ls -la dws.deb && (ar x dws.deb && tar xf data.tar.* && find . -name "doom1.wad" -exec cp {} ./doom1.wad \; ) && break
done
ls -la /root/doom/wads/doom1.wad && md5sum /root/doom/wads/doom1.wad
PY=/root/doom/payload-venv/bin/python
$PY /mnt/c/Users/Kevin/Genai/DoomSat/tools/wad_stats.py /root/doom/wads/doom1.wad E1M1 E1M2 E1M3
