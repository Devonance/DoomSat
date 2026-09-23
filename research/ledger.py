"""The experiment ledger. Charter 6.

One row per experiment, appended only by this script, never by hand. That is the whole discipline: the
thing that decides keep or discard is not the person or the agent who wrote the change, and the record of
what was decided is written by the same code that decided it.

    # after running the parent and the child on the same maps and seeds
    python research/ledger.py --exp EXP-0001 --author claude-code --area harness \\
        --hypothesis "..." --change "..." \\
        --parent research/out/<parent-run> --new research/out/<child-run>

It prints the verdict the keep rule gives and appends the row. `--decision` overrides the verdict, which
is sometimes right and always has to be justified in `--notes`; the row records both, so an override is
visible forever.
"""
import argparse
import csv
import glob
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LEDGER = HERE / "ledger.tsv"
NOISE = HERE / "noise_floor.json"

COLUMNS = ["exp_id", "date", "track", "parent_commit", "commit", "author", "area", "hypothesis", "change",
           "tier", "levels", "seeds", "score_parent", "score_new", "delta", "noise_se", "paired_wins",
           "paired_losses", "guardrails", "decision", "jev_usd", "sonnet_usd", "wall_min", "notes"]

try:
    import yaml
except ImportError:                                            # noqa: BLE001
    raise SystemExit("PyYAML is needed to read research/levels.yaml: pip install pyyaml")


def load_run(run_dir):
    """Graded attempts and the summary for one run directory."""
    graded = [json.load(open(p, encoding="utf-8"))
              for p in sorted(glob.glob(os.path.join(run_dir, "graded-*.json")))]
    if not graded:
        raise SystemExit("%s has no graded-*.json: run research/grade.py on it first" % run_dir)
    summary_path = os.path.join(run_dir, "summary.json")
    summary = json.load(open(summary_path, encoding="utf-8")) if os.path.isfile(summary_path) else {}
    return graded, summary


def pair(parent, child):
    """Match attempts on (map, seed). Charter 6.3 step 4: the same levels and the same seeds, or nothing."""
    a = {(r["map"], r["seed"]): r for r in parent}
    b = {(r["map"], r["seed"]): r for r in child}
    keys = sorted(set(a) & set(b))
    if not keys:
        raise SystemExit("the two runs share no (map, seed) pair, so they cannot be compared")
    skipped = sorted(set(a) ^ set(b))
    # Every attempt on a side must have run from the same code, or the row is comparing two mixtures.
    for side, name in ((parent, "parent"), (child, "new")):
        commits = {r.get("commit") for r in side if r.get("commit")}
        if len(commits) > 1:
            raise SystemExit("the %s run spans %d commits (%s): the bench starts a fresh payload per "
                             "attempt, so an edit mid-run lands in the later attempts only. Re-run with "
                             "--pin." % (name, len(commits), ", ".join(sorted(commits))))
        if any(r.get("dirty") for r in side):
            print("  ! the %s run was measured from an uncommitted tree; it cannot be re-run" % name)
    return keys, [(a[k], b[k]) for k in keys], skipped


def noise_se(pairs):
    """Standard error of the paired mean difference.

    Prefer the measured noise floor: the spread of repeats of the same level with nothing changed. That is
    the honest denominator, because the spread between a parent and a child on one seed contains both the
    change and the noise. Falls back to the spread of the differences themselves, which is the usual
    paired t-test denominator and is fine when the noise floor has not been measured yet.
    """
    n = len(pairs)
    if NOISE.exists():
        floor = json.load(open(NOISE, encoding="utf-8"))
        sds = [v["sd"] for v in floor.get("per_level", {}).values() if v.get("sd")]
        if sds:
            # two independent runs, so the difference has sqrt(2) times the sd of one
            return statistics.fmean(sds) * (2 ** 0.5) / (n ** 0.5), "measured noise floor (%d levels)" % len(sds)
    diffs = [b["score"] - a["score"] for a, b in pairs]
    if n < 2:
        return float("inf"), "one pair only: no spread to estimate from"
    return statistics.stdev(diffs) / (n ** 0.5), "spread of the paired differences"


def verdict(pairs, parent_sum, child_sum, conf):
    diffs = [b["score"] - a["score"] for a, b in pairs]
    mean = statistics.fmean(diffs)
    se, se_from = noise_se(pairs)
    rule = conf["keep_rule"]
    guard_ok = child_sum.get("guardrails_pass", False)
    completed_ok = (not rule["completed_must_not_drop"]
                    or child_sum.get("completed", 0) >= parent_sum.get("completed", 0))
    big_enough = mean > rule["min_gain_in_noise_se"] * se
    if not guard_ok:
        d, why = "discard", "a guardrail failed"
    elif not completed_ok:
        d, why = "discard", "fewer levels completed (%s -> %s)" % (parent_sum.get("completed"), child_sum.get("completed"))
    elif big_enough:
        d, why = "keep", "gain %.4f is over %.1f standard errors (se %.4f, %s)" % (mean, rule["min_gain_in_noise_se"], se, se_from)
    elif mean > 0:
        d, why = "inconclusive", "gain %.4f is inside %.1f standard errors (se %.4f, %s): rerun with %s" % (
            mean, rule["min_gain_in_noise_se"], se, se_from, conf["run"]["seeds_wide"])
    else:
        d, why = "discard", "no gain (%.4f)" % mean
    return {"decision": d, "why": why, "delta": mean, "se": se,
            "wins": sum(1 for x in diffs if x > 0), "losses": sum(1 for x in diffs if x < 0)}


def git(*a):
    try:
        return subprocess.check_output(["git"] + list(a), cwd=str(ROOT), text=True).strip()
    except Exception:                                          # noqa: BLE001
        return ""


def append(row):
    new = not LEDGER.exists()
    with open(LEDGER, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter="\t", extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def next_exp_id():
    if not LEDGER.exists():
        return "EXP-0001"
    ids = [r["exp_id"] for r in csv.DictReader(open(LEDGER, encoding="utf-8"), delimiter="\t")
           if r.get("exp_id", "").startswith("EXP-")]
    return "EXP-%04d" % (max([int(i.split("-")[1]) for i in ids] or [0]) + 1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parent", required=True, help="the run directory of the commit being improved on")
    ap.add_argument("--new", required=True, help="the run directory of the change")
    ap.add_argument("--exp", default=None)
    ap.add_argument("--author", default="claude-code",
                    choices=["kevin", "claude-code", "system-two"])
    ap.add_argument("--area", default="graph",
                    choices=["executor", "world-model", "graph", "knowledge", "sensing", "planner", "harness"])
    ap.add_argument("--hypothesis", required=True)
    ap.add_argument("--change", required=True)
    ap.add_argument("--decision", default=None, choices=["keep", "discard", "inconclusive", "crash"],
                    help="override the keep rule; say why in --notes")
    ap.add_argument("--jev-usd", type=float, default=0.0)
    ap.add_argument("--sonnet-usd", type=float, default=0.0)
    ap.add_argument("--wall-min", type=float, default=0.0)
    ap.add_argument("--notes", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    conf = yaml.safe_load(open(HERE / "levels.yaml", encoding="utf-8"))
    p_graded, p_sum = load_run(a.parent)
    c_graded, c_sum = load_run(a.new)
    keys, pairs, skipped = pair(p_graded, c_graded)
    v = verdict(pairs, p_sum, c_sum, conf)
    decision = a.decision or v["decision"]

    print("%d paired attempts on %s" % (len(pairs), ", ".join(sorted({k[0] for k in keys}))))
    if skipped:
        print("  ignored, present in only one run: %s" % ", ".join("%s/%s" % k for k in skipped))
    print("  parent %.4f -> new %.4f   delta %+.4f   se %.4f   %d wins / %d losses"
          % (p_sum.get("suite_score", 0), c_sum.get("suite_score", 0), v["delta"], v["se"], v["wins"], v["losses"]))
    print("  guardrails: %s" % ("pass" if c_sum.get("guardrails_pass") else "FAIL"))
    print("  keep rule says %s -- %s" % (v["decision"], v["why"]))
    if a.decision and a.decision != v["decision"]:
        print("  OVERRIDDEN to %s" % a.decision)

    row = {
        "exp_id": a.exp or next_exp_id(), "date": time.strftime("%Y-%m-%d"), "track": conf["track"],
        "parent_commit": (p_graded[0].get("versions") or {}).get("commit") or "",
        "commit": (c_graded[0].get("versions") or {}).get("commit") or git("rev-parse", "--short", "HEAD"),
        "author": a.author, "area": a.area, "hypothesis": a.hypothesis, "change": a.change,
        "tier": c_graded[0].get("tier"), "levels": ",".join(sorted({k[0] for k in keys})),
        "seeds": ",".join(str(s) for s in sorted({k[1] for k in keys})),
        "score_parent": round(p_sum.get("suite_score", 0), 4), "score_new": round(c_sum.get("suite_score", 0), 4),
        "delta": round(v["delta"], 4), "noise_se": round(v["se"], 4),
        "paired_wins": v["wins"], "paired_losses": v["losses"],
        "guardrails": "pass" if c_sum.get("guardrails_pass") else "fail",
        "decision": decision, "jev_usd": a.jev_usd, "sonnet_usd": a.sonnet_usd, "wall_min": a.wall_min,
        "notes": (a.notes + (" [override: rule said %s]" % v["decision"] if a.decision and a.decision != v["decision"] else "")
                  + " | " + v["why"]).strip(),
    }
    if a.dry_run:
        print("\ndry run, not appended:\n  " + "\t".join(str(row[c]) for c in COLUMNS))
    else:
        append(row)
        print("\nappended %s to %s" % (row["exp_id"], LEDGER))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
