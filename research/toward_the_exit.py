"""How much of the walking went toward the way out, and how much of it went back. Grader side.

A suite score says an attempt did not finish. `progress_best` says how close it got. Neither says whether
it spent its 180 seconds making slow progress or crossing the same ground in both directions, and those
call for opposite fixes -- the first is a speed problem and the second is a decision problem.

This walks the recorded positions against the grader's distance field and adds up the steps that shortened
the distance to the exit and the steps that lengthened it. A pilot walking a straight line to the exit
scores 1.0. A pilot oscillating scores near 0 however far it travels.

    python research/toward_the_exit.py research/out/<run>
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

if os.environ.get("DOOMSAT_ROLE") == "pilot":
    raise SystemExit("this reads the level file and must not run inside a pilot process")

from grader import wad                                          # noqa: E402

_FIELDS = {}


def field_for(wad_path, map_name):
    key = (os.path.abspath(wad_path), map_name)
    if key not in _FIELDS:
        level = wad.Level(wad_path, map_name)
        _FIELDS[key] = wad.DistanceField(level)
    return _FIELDS[key]


def one(path):
    a = json.load(open(path, encoding="utf-8"))
    field = field_for(a["wad_path"], a["map"])
    pts = [(float(r["raw"]["POS_X"]), float(r["raw"]["POS_Y"]))
           for r in a.get("decisions") or []
           if (r.get("raw") or {}).get("POS_X") is not None]
    closer = further = 0.0
    prev = None
    for x, y in pts:
        d = field.at(x, y)
        if d is None:
            continue
        if prev is not None:
            if d < prev:
                closer += prev - d
            else:
                further += d - prev
        prev = d
    total = closer + further
    return {"map": a["map"], "seed": a.get("seed"), "oracle": a.get("oracle"),
            "closer": round(closer), "further": round(further),
            "net": round(closer - further),
            "toward_fraction": round(closer / total, 3) if total else None,
            "decisions": len(pts)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    a = ap.parse_args()
    rows = [one(p) for p in sorted(glob.glob(os.path.join(a.run_dir, "attempt-*.json")))]
    if not rows:
        raise SystemExit("no attempt-*.json in %s" % a.run_dir)
    print("%-6s %-5s %10s %10s %10s %8s" % ("map", "seed", "toward", "away", "net", "toward%"))
    for r in rows:
        print("%-6s %-5s %10s %10s %10s %8s"
              % (r["map"], r["seed"], r["closer"], r["further"], r["net"],
                 "-" if r["toward_fraction"] is None else "%.0f%%" % (100 * r["toward_fraction"])))
    good = [r for r in rows if r["toward_fraction"] is not None]
    if good:
        print("\nmean toward fraction %.0f%% over %d attempts. Half is a coin toss: every unit walked "
              "toward the exit is matched by one walked away from it."
              % (100 * sum(r["toward_fraction"] for r in good) / len(good), len(good)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
