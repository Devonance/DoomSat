"""How many of the sensor's doors are real doors, checked against the WAD. Diagnostic; never flown.

`seen_geometry` calls a line a door when the sector on one side has no headroom and its flat is at the
neighbouring floor. This asks the level file how many of those are linedefs the engine would actually
open, and how many real doors the rule misses. Precision and recall for the door sensor, in one number
each, on any map.

    python payload/door_probe.py --wad freedoom1.wad --map E1M1
"""
import argparse
import importlib.util
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vizdoom as vzd                                          # noqa: E402
import seen_geometry as sg                                     # noqa: E402


def wad_module():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "research", "grader", "wad.py")
    spec = importlib.util.spec_from_file_location("door_probe_wad", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wad", default="freedoom1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--within", type=float, default=48.0, help="how near counts as the same door")
    a = ap.parse_args()
    path = a.wad if os.path.isfile(a.wad) else os.path.join("/root/doom/wads", a.wad)

    g = vzd.DoomGame()
    g.set_doom_game_path(path)
    g.set_doom_map(a.map)
    g.set_window_visible(False)
    g.set_screen_resolution(vzd.ScreenResolution.RES_320X240)
    g.set_sectors_info_enabled(True)
    g.set_mode(vzd.Mode.PLAYER)
    g.init()
    g.new_episode()
    sectors = g.get_state().sectors

    owners = {}
    for s in sectors:
        for ln in s.lines:
            owners.setdefault(sg.line_key(ln), []).append((s, ln))
    mine = []
    for key, group in owners.items():
        if sg.SeenGeometry._kind(group) == sg.DOOR:
            (x1, y1), (x2, y2) = key
            mine.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
    g.close()

    wad = wad_module()
    level = wad.Level(path, a.map)
    real = []
    for line in level.lines:
        if line[3] in wad.DOOR or line[3] in wad.KEY_DOOR:
            p, q = level.verts[line[0]], level.verts[line[1]]
            real.append(((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0))

    hit = sum(1 for m in mine if any(math.hypot(m[0] - r[0], m[1] - r[1]) <= a.within for r in real))
    found = sum(1 for r in real if any(math.hypot(m[0] - r[0], m[1] - r[1]) <= a.within for m in mine))
    print("%s %s: sensor says %d door lines, the level file has %d" % (a.wad, a.map, len(mine), len(real)))
    print("   precision %.2f (%d of %d within %.0f units of a real door)"
          % (hit / len(mine) if mine else 0.0, hit, len(mine), a.within))
    print("   recall    %.2f (%d of %d real doors found)"
          % (found / len(real) if real else 0.0, found, len(real)))
    for m in mine:
        if not any(math.hypot(m[0] - r[0], m[1] - r[1]) <= a.within for r in real):
            print("   false positive at (%.0f,%.0f)" % m)


if __name__ == "__main__":
    main()
