"""Draw what actually happened: the true map, the path walked, and every candidate the pilot was offered.

Grader-side, human-only, after the fact. It reads the WAD, so it can never be on the flight path -- the
package guard refuses to load in a pilot process (honesty test 6), and nothing the pilot sees comes from
here. That is exactly what makes it useful: the picture can show the truth next to what the pilot
believed, which is the one comparison the pilot itself must never be able to make.

It exists because of a bug that took two flights and a hand-written histogram to find. ZDoom's
`am_cdwallcolor` is the "ceiling height changes" category, and the payload read that colour as DOOR, so
every step, window frame and ledge became a door candidate -- 1,336 of 2,899 across one flight. On a
picture of the level with the candidates drawn on it, that is obvious in one glance.

    python research/grader/overlay.py research/out/flight-status-2/attempt-E1M1-0.json
"""
import argparse
import json
import math
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from grader import wad
else:
    from . import wad

from PIL import Image, ImageDraw          # noqa: E402

BG = (16, 16, 20)
WALL = (90, 90, 100)
DOOR_LINE = (80, 160, 255)
EXIT_LINE = (255, 140, 0)
PATH = (120, 220, 140)
START = (255, 255, 255)
END = (255, 90, 90)
KIND_COLOUR = {"frontier": (90, 200, 255), "door": (255, 210, 80), "exit": (255, 140, 0),
               "key": (255, 80, 255), "item": (160, 255, 160), "switch": (255, 255, 120),
               "enemy": (255, 60, 60)}


def draw(attempt, dest, scale=0.12):
    level = wad.Level(attempt["wad_path"], attempt["map"])
    x0, y0, x1, y1 = level.bbox()
    pad = 40
    w = int((x1 - x0) * scale) + pad * 2
    h = int((y1 - y0) * scale) + pad * 2
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    P = lambda x, y: ((x - x0) * scale + pad, (y1 - y) * scale + pad)

    # the true map, which only this side of the fence is allowed to know
    for line in level.lines:
        a, b = level.verts[line[0]], level.verts[line[1]]
        special = line[3]
        if special in wad.NORMAL_EXIT or special in wad.SECRET_EXIT:
            col, wd = EXIT_LINE, 3
        elif special in wad.DOOR or special in wad.KEY_DOOR:
            col, wd = DOOR_LINE, 2
        elif level.blocks(line):
            col, wd = WALL, 1
        else:
            continue
        d.line([P(*a), P(*b)], fill=col, width=wd)

    rows = [r for r in (attempt.get("decisions") or []) if r.get("kind") == "control"]
    pts = [(r["raw"]["POS_X"], r["raw"]["POS_Y"]) for r in rows
           if (r.get("raw") or {}).get("POS_X") is not None]
    if len(pts) > 1:
        d.line([P(*p) for p in pts], fill=PATH, width=2)

    # every candidate the pilot was offered, where it was offered, coloured by what the pilot thought
    # it was. A cloud of "door" markers along a plain wall is the bug this file was written for.
    seen = {}
    for r in rows:
        for c in r.get("cand_xy") or []:
            key = (c["kind"], round(c["x"] / 64), round(c["y"] / 64))
            seen[key] = seen.get(key, 0) + 1
    for (kind, kx, ky), n in seen.items():
        px, py = P(kx * 64.0, ky * 64.0)
        rad = 2 + min(4, n // 20)
        col = KIND_COLOUR.get(kind, (200, 200, 200))
        d.ellipse([px - rad, py - rad, px + rad, py + rad], outline=col)
        if kind == "door" and not _near_a_real_door(level, kx * 64.0, ky * 64.0):
            # offered as a door where the level has none: a ceiling change wearing a door's colour
            d.line([(px - rad - 2, py - rad - 2), (px + rad + 2, py + rad + 2)], fill=(255, 60, 60))
            d.line([(px - rad - 2, py + rad + 2), (px + rad + 2, py - rad - 2)], fill=(255, 60, 60))

    if pts:
        for p, col, r_ in ((pts[0], START, 4), (pts[-1], END, 4)):
            cx, cy = P(*p)
            d.ellipse([cx - r_, cy - r_, cx + r_, cy + r_], fill=col)
    d.text((pad, 8), "%s  %s  %d decisions  green: path   red X: offered as a door, level has none"
           % (attempt.get("map"), attempt.get("run_id", ""), len(rows)), fill=(200, 200, 200))
    img.save(dest)
    fake = sum(1 for (kind, kx, ky) in seen
               if kind == "door" and not _near_a_real_door(level, kx * 64.0, ky * 64.0))
    return {"image": dest, "candidate_places": len(seen),
            "door_places": sum(1 for k in seen if k[0] == "door"), "door_places_with_no_real_door": fake}


def _near_a_real_door(level, x, y, within=128.0):
    for line in level.lines:
        if line[3] not in wad.DOOR and line[3] not in wad.KEY_DOOR:
            continue
        for v in (level.verts[line[0]], level.verts[line[1]]):
            if math.hypot(v[0] - x, v[1] - y) <= within:
                return True
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("attempt", help="an attempt JSON written by the runner")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    attempt = json.load(open(a.attempt, encoding="utf-8"))
    dest = a.out or os.path.join(os.path.dirname(os.path.abspath(a.attempt)),
                                 "overlay-%s-%s.png" % (attempt["map"], attempt.get("seed", 0)))
    info = draw(attempt, dest)
    print("%s\n  %d places offered as candidates, %d of them as doors, %d of those where the level has "
          "no door within 128 units" % (info["image"], info["candidate_places"], info["door_places"],
                                        info["door_places_with_no_real_door"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
