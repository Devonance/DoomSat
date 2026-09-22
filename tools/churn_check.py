"""How much does a sector's description change between consecutive decisions, and why?

The audit's second live run walked worse than the first, and the reason turned out to be that the state
jev reads was being re-rolled almost every tick. This measures that directly from a decision log, split
into the two causes that matter:

  relabelling   the sectors are egocentric, so a turn slides every reading to a neighbouring label
  real change   the reading for one world direction actually changed

and compares the raw payload words against the smoothed ones `build_state` now produces, so the effect of
`select.confirm_ticks` can be seen without flying anything.

    python tools/churn_check.py runs/2026-09-22/decisions_newgraph_run1.jsonl
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ground"))

import decision_graph as dg          # noqa: E402
import graph_config as gc            # noqa: E402

FIELDS = ("space", "ground", "door")


def rebuild(rows, cfg, smooth):
    """The sector words this log would produce now, with or without the world-frame smoothing."""
    mem = dg.NavMemory(cfg) if smooth else None
    out = []
    for r in rows:
        t = dict(r["raw"])
        if mem is not None:
            mem.step()
        out.append((t, dg.build_state(t, "EXPLORE", cfg, mem)["sectors"]))
    return out


def churn(built, turning=None):
    """Mean sectors (of 8) whose word changed between consecutive ticks, per field."""
    totals = {f: 0 for f in FIELDS}
    pairs = 0
    for (ta, sa), (tb, sb) in zip(built, built[1:]):
        aa, ab = ta.get("ANGLE"), tb.get("ANGLE")
        if aa is None or ab is None:
            continue
        turned = abs((ab - aa + 180) % 360 - 180) >= 1.0
        if turning is not None and turned != turning:
            continue
        pairs += 1
        for d in set(sa) & set(sb):
            for f in FIELDS:
                totals[f] += sa[d].get(f) != sb[d].get(f)
    return pairs, {f: totals[f] / max(1, pairs) for f in FIELDS}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "runs/2026-09-22/decisions_newgraph_run1.jsonl"
    cfg = gc.validate(gc.DEFAULT)
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if r.get("kind") == "control" and (r.get("raw") or {}).get("CLEAR_FWD") is not None]
    print("%s: %d control rows, confirm_ticks=%d" % (path, len(rows), cfg["select"]["confirm_ticks"]))
    print()
    print("%-22s %-8s %s" % ("", "pairs", "  ".join("%-7s" % f for f in FIELDS)))
    for label, smooth in (("raw payload words", False), ("smoothed, world frame", True)):
        built = rebuild(rows, cfg, smooth)
        for sub, turning in (("all ticks", None), ("heading steady", False), ("heading turned", True)):
            pairs, m = churn(built, turning)
            print("%-22s %-8d %s   <- %s" % (label if sub == "all ticks" else "", pairs,
                                             "  ".join("%-7.2f" % m[f] for f in FIELDS), sub))
        print()
    print("sectors of 8 whose word differs from the previous decision; lower is steadier evidence")


if __name__ == "__main__":
    main()
