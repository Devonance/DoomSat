"""Check the ruler before trusting it: what the grader thinks each level demands.

A progress score is only as good as the walkability model behind it, and that model is a guess about an
engine (see the caveats in wad.py). Run this on any WAD before it joins a set, and read the two things
that matter: every map must have at least one normal exit line, and every map must have a route to it
from the player start. A map that fails either can still be scored on `completed`, but its `progress` is
noise and the ledger should not average it in.

    python research/grader/survey.py /root/doom/wads/doom1.wad
    python research/grader/survey.py /root/doom/wads/freedoom1.wad E1M1 E1M2
"""
import argparse
import os
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from grader import wad
else:
    from . import wad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wad_path")
    ap.add_argument("maps", nargs="*", help="default: every map in the WAD")
    a = ap.parse_args(argv)
    names = a.maps or wad.maps(a.wad_path)
    print("%-8s %-16s %5s %5s %9s %9s %s" % ("map", "start", "exits", "tele", "to exit", "cells", "build"))
    bad = 0
    for name in names:
        t0 = time.time()
        try:
            level = wad.Level(a.wad_path, name)
            field = wad.DistanceField(level)
        except Exception as e:                                   # noqa: BLE001 - a survey reports, never raises
            print("%-8s FAILED: %s" % (name, e))
            bad += 1
            continue
        start = level.start()
        d = field.at(*start)
        walkable = sum(1 for v in field.dist if v != float("inf"))
        note = ""
        if not level.exit_lines():
            note, bad = "NO NORMAL EXIT LINE: score this map on completed only", bad + 1
        elif d is None:
            note, bad = "NO ROUTE from the start: progress is meaningless here", bad + 1
        elif level.has_teleport():
            note = "has teleports, which the model does not follow"
        print("%-8s %-16s %5d %5s %9s %9d %5.1fs %s"
              % (name, "%d,%d" % start, len(level.exit_lines()), "yes" if level.has_teleport() else "no",
                 "-" if d is None else "%d" % d, walkable, time.time() - t0, note))
    print("\n%d of %d maps are usable for a progress score" % (len(names) - bad, len(names)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
