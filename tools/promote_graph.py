"""Replay a System Two candidate against the graph in use, and promote it only if it wins.

The old loop made every review current the moment it came back, off a single three-minute episode. The
review is now written to ground/graph/candidates/ and has to get through here first: both graphs judge the
same logged states, several times each, and the candidate is promoted only if it is at least as steady and
no more reliant on the fallback than the graph it would replace.

    python tools/promote_graph.py --list
    python tools/promote_graph.py ground/graph/candidates/graph_c1.json --cases 120 --passes 3
    python tools/promote_graph.py ground/graph/candidates/graph_c1.json --promote        # after reading it
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ground"))
sys.path.insert(0, str(HERE))

import graph_config as gc            # noqa: E402
import decision_graph as dg          # noqa: E402
from replay import JevPilot, load_cases, run_pilot, summarise, median   # noqa: E402


def score(runs):
    """What a graph is judged on: does its pilot command the same thing twice, and how often does it have
    to fall back to the rule because jev could not tell?"""
    cases = runs[0]["cases"]
    decided = [c for c in cases if c["pick"] and not c["fallback"]]
    unstable = 0
    for i in range(min(len(r["cases"]) for r in runs)):
        if len({r["cases"][i]["pick"] for r in runs}) > 1:
            unstable += 1
    return {"states": len(cases), "model_decided": len(decided),
            "fallback_rate": round(1 - len(decided) / max(1, len([c for c in cases if c["pick"]])), 3),
            "unstable_commands": unstable,
            "median_gap": round(median([c["gap"] for c in cases if c["gap"] is not None]) or 0, 3),
            "median_tokens": median([c["tokens"] for c in cases])}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("candidate", nargs="?", help="a file in ground/graph/candidates/")
    p.add_argument("--list", action="store_true", help="show the candidates waiting")
    p.add_argument("--log", default="runs/2026-09-22/decisions_newgraph_run1.jsonl")
    p.add_argument("--cases", type=int, default=120)
    p.add_argument("--passes", type=int, default=3)
    p.add_argument("--promote", action="store_true", help="apply it if it passes")
    p.add_argument("--env-files", nargs="*", default=[str(HERE.parent / "ground" / ".env")])
    args = p.parse_args()

    box = gc.GRAPH_DIR / "candidates"
    if args.list or not args.candidate:
        found = sorted(box.glob("graph_c*.json")) if box.exists() else []
        if not found:
            print("no candidates waiting in %s" % box)
            return
        for f in found:
            d = json.loads(f.read_text(encoding="utf-8"))
            print("%-14s from v%s (%s): %s" % (f.name, d.get("from_version"), d.get("model"),
                                               str(d.get("rationale", ""))[:120].replace("\n", " ")))
        return

    current = gc.load()
    candidate, meta = gc.load_candidate(args.candidate)
    print("current  : v%s" % current["version"])
    print("candidate: %s" % Path(args.candidate).name)
    for line in gc.diff(current, candidate):
        print("   - %s" % line)
    print()

    cases = load_cases(args.log, args.cases or None)
    print("replaying %d logged states through both, %d passes each" % (len(cases), args.passes))
    results = {}
    for name, cfg in (("current", current), ("candidate", candidate)):
        bad = dg.lint(cfg)
        if bad:
            print("%s names state fields that do not exist: %s" % (name, ", ".join(bad)))
            return
        runs = run_pilot(JevPilot(cfg, args.env_files), cases, cfg, args.passes)
        results[name] = score(runs)
        r = results[name]
        print("  %-10s %d states, model decided %d, fallback %.0f%%, unstable commands %d, "
              "median gap %.2f, tokens %s"
              % (name, r["states"], r["model_decided"], 100 * r["fallback_rate"],
                 r["unstable_commands"], r["median_gap"], r["median_tokens"]))

    c, n = results["current"], results["candidate"]
    checks = [("no more unstable commands", n["unstable_commands"] <= c["unstable_commands"]),
              ("does not lean on the fallback more", n["fallback_rate"] <= c["fallback_rate"] + 0.02),
              ("jev still decides at least as often", n["model_decided"] >= c["model_decided"])]
    print()
    for label, ok in checks:
        print("  [%s] %s" % ("pass" if ok else "FAIL", label))
    passed = all(ok for _, ok in checks)
    print()
    if not passed:
        print("candidate does not beat the graph in use; leaving v%s current" % current["version"])
        return
    if not args.promote:
        print("candidate passes. Re-run with --promote to apply it.")
        return
    saved = gc.save(candidate, meta.get("rationale", ""), meta.get("issues"),
                    "%s, promoted after replay" % (meta.get("model") or "system two"))
    print("promoted to graph v%d" % saved["version"])


if __name__ == "__main__":
    main()
