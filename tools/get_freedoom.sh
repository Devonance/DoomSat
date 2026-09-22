#!/usr/bin/env bash
# Fetch the dev set (charter 2.5). Freedoom Phase 1 is a free, BSD-licensed IWAD built for the Doom 1
# engine, so the knowledge file applies to it unchanged and it is NOT part of the test set -- which is the
# whole point: tuning on the levels you also score on teaches the graph those levels through its
# parameters, even with no map stored.
#
#   scripts: run inside the WSL distro that runs ViZDoom
#   usage:   bash tools/get_freedoom.sh [dest_dir]
set -euo pipefail
DEST="${1:-/root/doom/wads}"
VER="0.13.0"
URL="https://github.com/freedoom/freedoom/releases/download/v${VER}/freedoom-${VER}.zip"

mkdir -p "$DEST"
if [ -f "$DEST/freedoom1.wad" ]; then
  echo "already have $DEST/freedoom1.wad"
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "fetching $URL"
curl -fsSL "$URL" -o "$TMP/freedoom.zip"
# python's zipfile rather than unzip: the WSL distro that runs ViZDoom has python and no unzip
python3 -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$TMP/freedoom.zip" "$TMP"
find "$TMP" -name 'freedoom1.wad' -exec cp {} "$DEST/" \;
find "$TMP" -name 'freedoom2.wad' -exec cp {} "$DEST/" \;
ls -l "$DEST"/freedoom*.wad
