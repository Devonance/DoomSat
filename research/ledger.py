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


def dig(summary, path):
    """Read a dotted path out of a summary, e.g. deaths_by_mode.RETREAT or guardrails.jev_share.value."""
    node = summary
    for key in path.split("."):
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return None
    return node


def fast_verdict(parent_sum, child_sum, watch, direction, conf):
    """The fast lane. Charter 6 with one deliberate exception.

    An obvious bug -- a retreat that does not return fire, a ten-second timeout on a model whose median
    latency is half a second -- does not need thirty paired attempts and two standard errors. It needs
    enough runs to show that the failure mode is gone. The full paired test stays for tuning, where the
    effect is small and the noise is not.

    The bar is: the watched number moved the right way, and no guardrail that passed before now fails.
    A fast-lane row says which number it watched, so nobody has to guess later what "it worked" meant.
    """
    before, after = dig(parent_sum, watch), dig(child_sum, watch)
    if before is None and after is None:
        return {"decision": "inconclusive", "why": "neither run reports %s" % watch,
                "delta": 0.0, "se": float("nan"), "wins": 0, "losses": 0}
    before, after = float(before or 0), float(after or 0)
    moved = (after < before) if direction == "down" else (after > before)
    # a guardrail that passed before and fails now is a regression, whatever the watched number did
    broke = [k for k, v in (child_sum.get("guardrails") or {}).items()
             if not v.get("pass") and (parent_sum.get("guardrails", {}).get(k, {}) or {}).get("pass")]
    if broke:
        d, why = "discard", "%s went the right way but %s now fails" % (watch, ", ".join(broke))
    elif moved:
        d, why = "keep", "%s %s %.4f -> %.4f (fast lane: the failure mode is gone, not a score gain)" % (
            watch, direction, before, after)
    else:
        d, why = "discard", "%s did not move %s (%.4f -> %.4f)" % (watch, direction, before, after)
    return {"decision": d, "why": why, "delta": after - before, "se": float("nan"),
            "wins": int(moved), "losses": int(not moved)}


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
    ap.add_argument("--parent", required=False, default=None,
                    help="the run directory of the commit being improved on. Not needed with "
                         "--decision history, where there is nothing to compare against.")
    ap.add_argument("--new", required=True, help="the run directory of the change")
    ap.add_argument("--exp", default=None)
    ap.add_argument("--author", default="claude-code",
                    choices=["kevin", "claude-code", "system-two"])
    ap.add_argument("--area", default="graph",
                    choices=["executor", "world-model", "graph", "knowledge", "sensing", "planner", "harness"])
    ap.add_argument("--hypothesis", required=True)
    ap.add_argument("--change", required=True)
    ap.add_argument("--decision", default=None,
                    choices=["keep", "discard", "inconclusive", "crash", "history"],
                    help="override the keep rule; say why in --notes. `history` is for a run recorded "
                         "after the fact on a track that no longer exists: the numbers are written down "
                         "so the change is not invisible, and nothing is claimed for them.")
    ap.add_argument("--jev-usd", type=float, default=0.0)
    ap.add_argument("--sonnet-usd", type=float, default=0.0)
    ap.add_argument("--wall-min", type=float, default=0.0)
    ap.add_argument("--notes", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fast", metavar="METRIC", default=None,
                    help="fast lane: judge on whether this number moved, not on a paired score gain. "
                         "A dotted path into summary.json, e.g. deaths_by_mode.RETREAT, freezes, "
                         "mode_share.OPERATE. For obvious bugs; use the paired test for tuning.")
    ap.add_argument("--direction", default="down", choices=["down", "up"],
                    help="which way the watched number should move")
    a = ap.parse_args(argv)

    conf = yaml.safe_load(open(HERE / "levels.yaml", encoding="utf-8"))
    c_graded, c_sum = load_run(a.new)
    if a.decision == "history" and not a.parent:
        # A run recorded after the fact, on a track that no longer exists. There is nothing to pair it
        # against and nothing is being claimed for it -- the row exists so the change is not invisible,
        # and so that "this constant was set by an experiment that has never been repeated on t3" is a
        # fact anyone can look up rather than a thing you have to remember.
        p_graded, p_sum = c_graded, {}
        keys, pairs, skipped = [], [], []
        v = {"decision": "history", "why": "recorded after the fact; not paired, not compared",
             "delta": 0.0, "se": float("nan"), "wins": 0, "losses": 0}
        print("history row for %s: suite %.4f over %d attempts"
              % (a.new, c_sum.get("suite_score", 0.0), c_sum.get("attempts", 0)))
        return _write(a, conf, keys, v, p_graded, p_sum, c_graded, c_sum)
    if not a.parent:
        raise SystemExit("--parent is required unless --decision history")
    p_graded, p_sum = load_run(a.parent)
    if a.fast:
        keys, pairs, skipped = [], [], []
        v = fast_verdict(p_sum, c_sum, a.fast, a.direction, conf)
        print("fast lane, watching %s (%d attempts against %d)"
              % (a.fast, c_sum.get("attempts", 0), p_sum.get("attempts", 0)))
        print("  %s: %s -> %s" % (a.fast, dig(p_sum, a.fast), dig(c_sum, a.fast)))
    else:
        keys, pairs, skipped = pair(p_graded, c_graded)
        v = verdict(pairs, p_sum, c_sum, conf)
        print("%d paired attempts on %s" % (len(pairs), ", ".join(sorted({k[0] for k in keys}))))
        if skipped:
            print("  ignored, present in only one run: %s" % ", ".join("%s/%s" % k for k in skipped))
        print("  parent %.4f -> new %.4f   delta %+.4f   se %.4f   %d wins / %d losses"
              % (p_sum.get("suite_score", 0), c_sum.get("suite_score", 0), v["delta"], v["se"],
                 v["wins"], v["losses"]))
    print("  guardrails: %s" % ("pass" if c_sum.get("guardrails_pass") else "FAIL"))
    print("  keep rule says %s -- %s" % (v["decision"], v["why"]))
    if a.decision and a.decision != v["decision"]:
        print("  OVERRIDDEN to %s" % a.decision)

    return _write(a, conf, keys, v, p_graded, p_sum, c_graded, c_sum)


def _write(a, conf, keys, v, p_graded, p_sum, c_graded, c_sum):
    decision = a.decision or v["decision"]
    # The track the run was MEASURED on, not the track the repo is on today. For a history row those are
    # different by definition, and writing today's track on a run from a fortnight ago is exactly the
    # confusion the track column exists to prevent.
    track = (c_graded[0].get("versions") or {}).get("track") or conf["track"]
    row = {
        "exp_id": a.exp or next_exp_id(), "date": time.strftime("%Y-%m-%d"), "track": track,
        "parent_commit": (p_graded[0].get("versions") or {}).get("commit") or "",
        "commit": (c_graded[0].get("versions") or {}).get("commit") or git("rev-parse", "--short", "HEAD"),
        "author": a.author, "area": a.area, "hypothesis": a.hypothesis, "change": a.change,
        "tier": c_graded[0].get("tier"),
        "levels": ",".join(sorted({k[0] for k in keys})) or ",".join(sorted({r["map"] for r in c_graded})),
        "seeds": (",".join(str(s) for s in sorted({k[1] for k in keys}))
                  or ",".join(str(s) for s in sorted({r["seed"] for r in c_graded}))),
        "score_parent": round(p_sum.get("suite_score", 0), 4), "score_new": round(c_sum.get("suite_score", 0), 4),
        "delta": round(v["delta"], 4), "noise_se": round(v["se"], 4),
        "paired_wins": v["wins"], "paired_losses": v["losses"],
        "guardrails": "pass" if c_sum.get("guardrails_pass") else "fail",
        "decision": decision, "jev_usd": a.jev_usd, "sonnet_usd": a.sonnet_usd, "wall_min": a.wall_min,
        "notes": (("fast lane on %s; " % a.fast if a.fast else "") + a.notes
                  + (" [override: rule said %s]" % v["decision"] if a.decision and a.decision != v["decision"] else "")
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
