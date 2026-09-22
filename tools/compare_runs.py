"""Compare two pilots on the walk, over matched windows, with a spread rather than a single number.

One three-minute run per side is one sample, and the first comparison of the rewritten graph against the
one it replaced was exactly that: it read as a large regression, and most of the gap turned out to be the
tick-window spin metric counting a design that waits out its turns. This slices both logs into windows of
the same wall-clock length and reports the distribution, so a difference has to survive the spread before
anyone calls it a difference.

    python tools/compare_runs.py old=runs/2026-09-22/decisions.jsonl new=out/decisions.jsonl
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ground"))

import metrics                       # noqa: E402

WINDOW = 150.0


def control_rows(path):
    out = []
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("kind") == "control" and (r.get("raw") or {}).get("POS_X") is not None:
            out.append(r)
    return out


def windows(rows, seconds=WINDOW):
    """Consecutive non-overlapping windows of `seconds`, never crossing an episode boundary."""
    out, cur, start = [], [], None
    for r in rows:
        if start is None:
            start = r["t"]
        if r["t"] - start > seconds or (cur and r.get("episode") != cur[-1].get("episode")):
            if len(cur) >= 20:
                out.append(cur)
            cur, start = [], r["t"]
        cur.append(r)
    if len(cur) >= 20:
        out.append(cur)
    return out


def measure(win):
    s = metrics.samples(win)
    span = max(1e-6, win[-1]["t"] - win[0]["t"])
    tok = sorted((r.get("usage") or {}).get("input_tokens", 0) for r in win if r.get("usage"))
    return {"decisions": len(win), "seconds": span,
            "spin_per_s": metrics.spin_rate(s),
            "cells": len(metrics.cells(s)),
            "units_per_s": metrics.path_units(s) / span,
            "tokens": tok[len(tok) // 2] if tok else 0}


def spread(vals):
    vals = sorted(vals)
    if not vals:
        return (0, 0, 0)
    return (vals[0], vals[len(vals) // 2], vals[-1])


def main():
    args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
    if not args:
        args = {"old": "runs/2026-09-22/decisions.jsonl", "new": "out/decisions.jsonl"}
    print("windows of %.0f s, never crossing an episode boundary" % WINDOW)
    print()
    print("%-8s %-8s %-22s %-22s %-22s %s" % ("run", "windows", "spin windows/s", "cells per window",
                                              "units walked/s", "tokens"))
    rows = {}
    for label, path in args.items():
        wins = [measure(w) for w in windows(control_rows(path))]
        if not wins:
            print("%-8s no complete window in %s" % (label, path))
            continue
        rows[label] = wins
        fmt = lambda key, p="%.3f": "%s / %s / %s" % tuple(p % v for v in spread([w[key] for w in wins]))
        print("%-8s %-8d %-22s %-22s %-22s %d"
              % (label, len(wins), fmt("spin_per_s"), fmt("cells", "%.0f"), fmt("units_per_s", "%.0f"),
                 sorted(w["tokens"] for w in wins)[len(wins) // 2]))
    print()
    print("each cell is worst / median / best across that run's windows")
    if len(rows) == 2:
        (la, a), (lb, b) = rows.items()
        print()
        print("with so few windows a rank comparison says more than a mean: for each measure, how many of")
        print("one run's windows the other run's median beats, and whether the worst of one clears the")
        print("median of the other.")
        for key, higher_is_better, name in (("spin_per_s", False, "spin windows per second"),
                                            ("cells", True, "cells per window"),
                                            ("units_per_s", True, "units walked per second")):
            va, vb = [w[key] for w in a], [w[key] for w in b]
            ma, mb = spread(va)[1], spread(vb)[1]
            better = (lambda x, y: x > y) if higher_is_better else (lambda x, y: x < y)
            beaten = sum(1 for v in va if better(mb, v))
            worst_b = max(vb) if not higher_is_better else min(vb)
            clears = better(worst_b, ma)
            print("  %-24s %s median %.3f beats %d of %d %s windows%s"
                  % (name, lb, mb, beaten, len(va), la,
                     "; its worst window still clears %s's median" % la if clears else ""))


if __name__ == "__main__":
    main()
