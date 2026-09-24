#!/bin/bash
# The shareware Doom IWAD (doom1.wad, episode 1) from the Debian doom-wad-shareware package.
. "$(dirname "$0")/../scripts/common.sh"
mkdir -p "$WADS" && cd "$WADS" || exit 1
rm -f doom1.wad
TMP="$(mktemp -d)"; cd "$TMP" || exit 1
for u in "https://deb.debian.org/debian/pool/non-free/d/doom-wad-shareware/doom-wad-shareware_1.9.fixed-2_all.deb" ; do
  curl -sSL -o dws.deb "$u" && ls -la dws.deb && (ar x dws.deb && tar xf data.tar.* && find . -name "doom1.wad" -exec cp {} "$WADS/doom1.wad" \; ) && break
done
cd "$WADS" && rm -rf "$TMP"
ls -la "$WADS/doom1.wad"
