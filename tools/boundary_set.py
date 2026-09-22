"""Pick the logged states worth arguing about, so a graph is judged where it actually fails.

Test cases at the boundary between two neighbouring options are where a System One graph fails first, so
this pulls three kinds of state out of a run's decision log:

  close    the top two sectors are within one rubric level by the code rule: the call could go either way
  door     a door is point blank or close in some sector: the door-versus-new-ground trade-off
  stuck    the player is stuck, or the way ahead is blocked: the recovery path

The output is a JSONL boundary set that tools/replay.py reads with --boundary, and a short summary of how
many of each kind it found. Hand-label the picks in the `label` field to turn it into a scored set.

    python tools/boundary_set.py --log runs/2026-09-22/decisions.jsonl --out runs/boundary_set.jsonl
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ground"))

import decision_graph as dg          # noqa: E402
import graph_config as gc            # noqa: E402
from replay import code_score        # noqa: E402


def classify(state, t, cfg):
    """Which boundary this state sits on, or None."""
    offered = dg.offered_sectors(state)
    if state["here"]["stuck"] == "yes" or state["sectors"].get("ahead", {}).get("space") == "blocked":
        return "stuck"
    if any(state["sectors"][d].get("door") in ("point blank", "close") for d in offered):
        return "door"
    scores = sorted((code_score(state["sectors"][d], dg.levels_of(cfg)) for d in offered), reverse=True)
    if len(scores) > 1 and scores[0] - scores[1] < 1.0:
        return "close"
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--log", default="runs/2026-09-22/decisions.jsonl")
    p.add_argument("--out", type=Path, default=Path("runs/boundary_set.jsonl"))
    p.add_argument("--per-kind", type=int, default=34, help="cases of each kind (about 100 in total)")
    args = p.parse_args()

    cfg = gc.validate(gc.DEFAULT)
    found = {"close": [], "door": [], "stuck": []}
    total = 0
    with open(args.log, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("kind") != "control" or not r.get("raw") or r["raw"].get("CLEAR_FWD") is None:
                continue
            total += 1
            t = dict(r["raw"])
            state = dg.build_state(t, r.get("goal", "EXPLORE"), cfg)
            kind = classify(state, t, cfg)
            if kind:
                found[kind].append({"id": r.get("request_id") or str(r.get("t")), "kind": kind,
                                    "t": r.get("t"), "episode": r.get("episode"),
                                    "graph_version": r.get("graph_version"),
                                    "offered": dg.offered_sectors(state), "logged_pick": r.get("pick"),
                                    "label": None, "state": state, "raw": t})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    picked = []
    for kind, rows in found.items():
        if not rows:
            continue
        step = max(1, len(rows) // args.per_kind)
        picked += rows[::step][:args.per_kind]      # spread over the run, not all from one stretch
    with open(args.out, "w", encoding="utf-8") as f:
        for row in picked:
            f.write(json.dumps(row) + "\n")
    print("read %d control states from %s" % (total, args.log))
    print("found: " + ", ".join("%s %d" % (k, len(v)) for k, v in found.items()))
    print("wrote %d cases to %s (%s)" % (len(picked), args.out, dict(Counter(r["kind"] for r in picked))))
    print("Next: fill in `label` with the direction a person would take, then")
    print("  python tools/replay.py --boundary %s --pilots code,jev --passes 3" % args.out)


if __name__ == "__main__":
    main()
