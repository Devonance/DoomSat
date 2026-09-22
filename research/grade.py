"""Grade a run directory: every attempt, then the suite score and the guardrails. Charter 6.4.

Run as its own process, which is the point: this is the only place the WAD is opened, and the runner --
which is a pilot -- cannot import it.

    python research/grade.py research/out/20260922T191455-code-ab12
"""
import argparse
import glob
import json
import os
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

if os.environ.get("DOOMSAT_ROLE") == "pilot":
    raise SystemExit("grade.py reads the level file and must not run inside a pilot process")

from grader import score as gscore     # noqa: E402

try:
    import yaml
except ImportError:                                            # noqa: BLE001
    raise SystemExit("PyYAML is needed to read research/levels.yaml: pip install pyyaml")


def guardrails(graded, conf):
    """Charter 6.4: failing any one of these means discard, whatever the score."""
    g = conf["guardrails"]
    out, tier = {}, (graded[0].get("tier") if graded else None)
    crashes = sum(1 for r in graded if r["end_reason"] == "crash")
    out["crashes"] = (crashes <= g["crashes_allowed"], "%d" % crashes)
    # Only meaningful when a model was in the loop. The code baseline has no model to take a share of the
    # decisions, and holding it to a jev floor would fail every baseline run by construction.
    shares = [r["metrics"]["jev_share"] for r in graded
              if r.get("decider") == "jev" and r["metrics"]["jev_share"] is not None]
    if shares:
        mean = statistics.fmean(shares)
        out["jev_share"] = (mean >= g["jev_share_min"], "%.2f (floor %.2f)" % (mean, g["jev_share_min"]))
    elif graded and graded[0].get("decider") == "code":
        out["jev_share"] = (True, "n/a: code baseline, no model in the loop")
    p95 = [r["metrics"]["decision_age_p95_ms"] for r in graded if r["metrics"]["decision_age_p95_ms"]]
    if tier == "flight" and p95:
        worst = max(p95)
        out["decision_age_p95"] = (worst <= g["decision_age_p95_ms"],
                                   "%.0f ms (budget %d)" % (worst, g["decision_age_p95_ms"]))
    elif p95:
        out["decision_age_p95"] = (True, "%.0f ms (bench: latency is injected, not measured)" % max(p95))
    return out


def summarise(graded, conf):
    scores = [r["score"] for r in graded]
    usable = [r for r in graded if r["exit_reachable_from_start"]]
    return {
        "attempts": len(graded),
        "suite_score": round(statistics.fmean(scores), 4) if scores else 0.0,
        "score_sd": round(statistics.stdev(scores), 4) if len(scores) > 1 else 0.0,
        "completed": sum(1 for r in graded if r["completed"]),
        "deaths": sum(r["deaths"] for r in graded),
        "mean_progress": round(statistics.fmean([r["progress"] for r in usable]), 4) if usable else None,
        "maps_without_a_usable_progress_score": [r["map"] for r in graded if not r["exit_reachable_from_start"]],
        "guardrails": {k: {"pass": v[0], "value": v[1]} for k, v in guardrails(graded, conf).items()},
        "guardrails_pass": all(v[0] for v in guardrails(graded, conf).values()),
    }


def per_level_sd(graded):
    """The noise floor, charter phase 1: the spread of repeats of the same level."""
    by = {}
    for r in graded:
        by.setdefault(r["map"], []).append(r["score"])
    return {m: {"n": len(v), "mean": round(statistics.fmean(v), 4),
                "sd": round(statistics.stdev(v), 4) if len(v) > 1 else None}
            for m, v in sorted(by.items())}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--write-noise-floor", action="store_true",
                    help="this run is repeats of the same levels with nothing changed: record its "
                         "per-level spread as the noise floor the keep rule divides by (charter phase 1)")
    a = ap.parse_args(argv)
    conf = yaml.safe_load(open(HERE / "levels.yaml", encoding="utf-8"))
    paths = sorted(glob.glob(os.path.join(a.run_dir, "attempt-*.json")))
    if not paths:
        raise SystemExit("no attempt-*.json in %s" % a.run_dir)
    graded = []
    for p in paths:
        g = gscore.grade(json.load(open(p, encoding="utf-8")))
        json.dump(g, open(os.path.join(a.run_dir, "graded-%s-%s.json" % (g["map"], g["seed"])), "w",
                          encoding="utf-8"), indent=1)
        graded.append(g)
        if not a.quiet:
            m = g["metrics"]
            print("%-7s seed %-3s score %.3f  %-9s progress %.2f (best %.2f)  cells %-4d  %.0f u/s  jev %s"
                  % (g["map"], g["seed"], g["score"], g["end_reason"], g["progress"], g["progress_best"],
                     m["cells"], m["speed_explore"],
                     "-" if m["jev_share"] is None else "%.0f%%" % (100 * m["jev_share"])))
            if g.get("warning"):
                print("        ! %s" % g["warning"])
    summary = summarise(graded, conf)
    summary["per_level"] = per_level_sd(graded)
    summary["run_dir"] = a.run_dir
    json.dump(summary, open(os.path.join(a.run_dir, "summary.json"), "w", encoding="utf-8"), indent=1)
    print("\nsuite score %.4f over %d attempts (sd %.4f), %d completed, %d deaths"
          % (summary["suite_score"], summary["attempts"], summary["score_sd"],
             summary["completed"], summary["deaths"]))
    for name, v in summary["guardrails"].items():
        print("  guardrail %-18s %-4s %s" % (name, "pass" if v["pass"] else "FAIL", v["value"]))
    sds = [v["sd"] for v in summary["per_level"].values() if v["sd"] is not None]
    if sds:
        print("  per-level score sd: %s  (noise floor: mean %.4f)"
              % (", ".join("%s %.3f" % (m, v["sd"]) for m, v in summary["per_level"].items() if v["sd"] is not None),
                 statistics.fmean(sds)))
    print("wrote %s" % os.path.join(a.run_dir, "summary.json"))
    if a.write_noise_floor:
        thin = [m for m, v in summary["per_level"].items() if v["n"] < 3]
        if thin:
            print("  refusing: %s have fewer than 3 repeats, which is not a spread" % ", ".join(thin))
            return 1
        floor = {"measured": summary["run_dir"], "when": summary.get("when"),
                 "decider": graded[0].get("decider"), "tier": graded[0].get("tier"),
                 "track": (graded[0].get("versions") or {}).get("track"),
                 "commit": (graded[0].get("versions") or {}).get("commit"),
                 "per_level": summary["per_level"],
                 "note": ("the spread of repeats of the same level with nothing changed. ledger.py divides "
                          "by this, so a change has to beat the harness before it counts as a change.")}
        json.dump(floor, open(HERE / "noise_floor.json", "w", encoding="utf-8"), indent=1)
        print("  wrote %s" % (HERE / "noise_floor.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
