"""What ViZDoom's sectors_info actually contains, on a real level. Diagnostic; never flown.

The charter forbids sectors_info to the pilot (honesty test 2) because it is the whole level at once.
The brief of 23 September approves it as a *source*, filtered inside the sensor to the lines the automap
has already drawn. Before writing that filter it is worth knowing exactly what the engine hands over:
how lines are shared between sectors, what `is_blocking` means for a door, and whether a closed door
sector really reads ceiling == floor.

    python payload/geom_probe.py --wad doom1.wad --map E1M1
"""
import argparse
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vizdoom as vzd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wad", default="doom1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--skill", type=int, default=3)
    a = ap.parse_args()
    wad = a.wad if os.path.isfile(a.wad) else os.path.join("/root/doom/wads", a.wad)
    g = vzd.DoomGame()
    g.set_doom_game_path(wad)
    g.set_doom_map(a.map)
    g.set_doom_skill(a.skill)
    g.set_window_visible(False)
    g.set_screen_resolution(vzd.ScreenResolution.RES_320X240)
    g.set_sectors_info_enabled(True)
    g.set_automap_buffer_enabled(True)
    g.set_automap_mode(vzd.AutomapMode.NORMAL)
    g.set_mode(vzd.Mode.PLAYER)
    g.init()
    g.new_episode()
    st = g.get_state()
    secs = st.sectors
    px = g.get_game_variable(vzd.GameVariable.POSITION_X)
    py = g.get_game_variable(vzd.GameVariable.POSITION_Y)
    print("map %s: %d sectors, player at (%.0f,%.0f)" % (a.map, len(secs), px, py))

    # how many sectors each line belongs to
    owners = defaultdict(list)
    for i, s in enumerate(secs):
        for ln in s.lines:
            key = tuple(round(v, 1) for v in (ln.x1, ln.y1, ln.x2, ln.y2))
            rkey = tuple(round(v, 1) for v in (ln.x2, ln.y2, ln.x1, ln.y1))
            owners[key if key in owners or rkey not in owners else rkey].append((i, ln))
    share = Counter(len(v) for v in owners.values())
    print("lines: %d distinct; sectors per line %s" % (len(owners), dict(share)))

    blocking_by_share = Counter()
    for v in owners.values():
        for _i, ln in v:
            blocking_by_share[(len(v), bool(ln.is_blocking))] += 1
    print("(sectors per line, is_blocking) -> count:", dict(blocking_by_share))

    flat = [s for s in secs if abs(s.ceiling_height - s.floor_height) < 1e-6]
    print("sectors with ceiling == floor (closed doors and the like): %d" % len(flat))
    for s in flat[:6]:
        xs = [c for ln in s.lines for c in (ln.x1, ln.x2)]
        ys = [c for ln in s.lines for c in (ln.y1, ln.y2)]
        print("   floor %7.1f  %2d lines  extent %4.0f x %4.0f  centre (%.0f,%.0f)  blocking %d/%d"
              % (s.floor_height, len(s.lines), max(xs) - min(xs), max(ys) - min(ys),
                 sum(xs) / len(xs), sum(ys) / len(ys),
                 sum(1 for ln in s.lines if ln.is_blocking), len(s.lines)))

    # what is near the player: does the geometry agree with where the player is standing?
    near = []
    for i, s in enumerate(secs):
        for ln in s.lines:
            d = seg_dist(px, py, ln.x1, ln.y1, ln.x2, ln.y2)
            if d < 200:
                near.append((d, i, ln, s))
    near.sort(key=lambda t: t[0])
    print("\nnearest 10 lines to the spawn:")
    for d, i, ln, s in near[:10]:
        print("   %5.0f u  sector %3d floor %6.1f ceil %6.1f  blocking %d  (%.0f,%.0f)-(%.0f,%.0f)"
              % (d, i, s.floor_height, s.ceiling_height, ln.is_blocking, ln.x1, ln.y1, ln.x2, ln.y2))

    heights = Counter(round(s.floor_height) for s in secs)
    print("\nfloor heights (most common): %s" % heights.most_common(8))
    g.close()


def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


if __name__ == "__main__":
    main()
