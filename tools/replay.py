"""Replay logged states through candidate pilots without the game, Yamcs or the flight stack.

This is the gate a new graph has to pass before it is flown (verification plan, step 3). Three pilots see
exactly the same states:

  code    a scoring function that encodes the rubric as an exact rule -- no model, no latency, no cost
  jev     the live System One model with the current graph, repeated --passes times because answers can
          flip between identical passes
  logged  what the run actually did, read back out of the log

The comparison that matters is `code` against `jev`. If a ten-line function matches jev on replayed
states, jev is not earning its latency on this state yet, and the honest move is to keep the code rule
and bring jev back when the state carries softer evidence (the planned surface classifier's labels, a
description of the frame) that no exact rule can read.

    python tools/replay.py --log runs/2026-09-22/decisions.jsonl --cases 200
    python tools/replay.py --log out/decisions.jsonl --pilots code,jev --passes 3
"""
import argparse
import copy
import json
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ground"))

import decision_graph as dg          # noqa: E402
from decision_graph import frontier_fallback   # noqa: E402
import graph_config as gc            # noqa: E402
import metrics                       # noqa: E402


# ---------------------------------------------------------------- the code-only baseline
def code_score(sector, levels=4):
    """The sector rubric written as an exact rule, level for level.

    Keep this in step with cfg["questions"]["sector"]["criteria"]: it is the null hypothesis the model has
    to beat, and a baseline that drifts from the rubric is not a baseline.
    """
    if sector.get("data") == dg.UNKNOWN:
        return 0.0
    if sector.get("exit_here") == "yes" or sector.get("key_here") == "yes" or sector.get("ground") == "never explored":
        return float(levels - 1)
    if sector.get("ground") == "new" or sector.get("door") in ("point blank", "close") or sector.get("hint_here") == "yes":
        return float(levels - 2)
    if sector.get("ground") in ("walked before", "partly walked") and sector.get("space") in dg.ROOMY:
        return 1.0
    return 0.0


class CodePilot:
    """No model at all: the rubric as a function."""
    name = "code"

    def __init__(self, cfg):
        self.cfg, self.levels = cfg, dg.levels_of(cfg)

    def answer(self, state, questions):
        out = {}
        for qid in questions:
            if qid.startswith("s_"):
                out[qid] = {"type": "score", "score": code_score(state["sectors"][qid[2:]], self.levels),
                            "confidence": 1.0}
            elif qid == "danger":
                hurt = state["player"]["health"] in ("critical", "low")
                close = state["combat"]["enemy_distance"] in ("point blank", "close")
                out[qid] = {"type": "score", "score": float(2 * close + hurt), "confidence": 1.0}
            elif qid == "goal":
                out[qid] = {"type": "choice", "choice": "Explore", "confidence": 1.0}
        return {"answers": out, "latency_ms": 0, "usage": {"input_tokens": 0}, "model": "code",
                "state_chars": len(json.dumps(state)) + len(json.dumps(questions))}


class JevPilot:
    name = "jev"

    def __init__(self, cfg, env_files):
        from providers import TypeSafeSystemOne, load_env_key
        key = load_env_key("TYPESAFE_API_KEY", env_files)
        if not key:
            raise SystemExit("TYPESAFE_API_KEY not set (env or ground/.env)")
        self.one = TypeSafeSystemOne(key, cfg["model"])       # pinned, so passes are comparable

    def answer(self, state, questions):
        return self.one.ask(state, questions)


# ---------------------------------------------------------------- replay
def load_cases(path, limit=None, boundary=None):
    """Control rows with enough telemetry to rebuild the state. Old logs replay too: the sectors that had
    a door in them come back as `ground: unknown`, which is what the overloaded channel actually left."""
    cases = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("kind") != "control" or not r.get("raw") or r["raw"].get("CLEAR_FWD") is None:
                continue
            cases.append(r)
    if boundary:
        keep = set(boundary)
        cases = [c for c in cases if c.get("request_id") in keep or str(c.get("t")) in keep]
    if limit and len(cases) > limit:
        step = len(cases) / limit
        cases = [cases[int(i * step)] for i in range(limit)]
    return cases


def judge_one(pilot, row, cfg, no_band=False):
    """One logged state through one pilot, from a fresh memory so the cases stay independent."""
    t = dict(row["raw"])
    mem = dg.NavMemory(cfg)
    state = dg.build_state(t, row.get("goal", "EXPLORE"), cfg, mem)
    mode = dg.next_mode(state, t, mem, cfg)
    offered = dg.offered_sectors(state)
    questions = dg.questions_for(state, cfg, mode, ask_goal=False, offered=offered)
    if not questions:
        return None
    reply = pilot.answer(dg.state_for(state, questions), questions)
    if mode not in dg.JUDGED_MODES:
        return {"pick": None, "raw_pick": None, "gap": None, "confidence": None, "fallback": None,
                "tokens": (reply.get("usage") or {}).get("input_tokens", 0),
                "latency": reply.get("latency_ms", 0)}
    # `raw_pick` is jev's own ranking with the unsure band switched off: calibrating the band needs to see
    # what the model would have done, not what the fallback did on its behalf.
    bare = copy.deepcopy(cfg)
    bare["select"]["unsure_gap"], bare["select"]["unsure_conf"] = 0.0, 0.0
    raw_pick, _ = dg.pick_sector(reply["answers"], state, bare, dg.NavMemory(bare),
                                 float(t.get("ANGLE", 0.0) or 0.0), row.get("goal", "EXPLORE"),
                                 offered, (t.get("POS_X"), t.get("POS_Y")))
    pick, detail = dg.pick_sector(reply["answers"], state, cfg, mem, float(t.get("ANGLE", 0.0) or 0.0),
                                  row.get("goal", "EXPLORE"), offered, (t.get("POS_X"), t.get("POS_Y")))
    return {"pick": pick, "raw_pick": raw_pick,
            # what the deterministic rule would have chosen, so any unsure_gap can be re-cut from the saved
            # cases (`--sweep`) without paying for the model calls again
            "fallback_pick": frontier_fallback(state, offered),
            "gap": detail.get("gap"), "confidence": detail.get("confidence"),
            "fallback": detail.get("fallback"), "tokens": (reply.get("usage") or {}).get("input_tokens", 0),
            "latency": reply.get("latency_ms", 0)}


def run_pilot(pilot, cases, cfg, passes=1):
    results = []
    for p in range(passes):
        out = []
        for row in cases:
            judged = judge_one(pilot, row, cfg)
            if judged is not None:
                out.append(judged)
        results.append({"pass": p, "cases": out,
                        "picks": [c["pick"] for c in out],
                        "tokens": [c["tokens"] for c in out],
                        "latency": [c["latency"] for c in out],
                        "fallbacks": dict(Counter(c["fallback"] for c in out if c["fallback"])),
                        "gaps": [c["gap"] for c in out if c["gap"] is not None]})
    return results


def calibrate(runs, cfg):
    """How often jev's own ranking changes between identical passes, bucketed by the top-two gap.

    This is how the unsure band gets its number instead of a guess: below the gap where the ranking stops
    being reproducible, the answer is not a preference, and code should fall back to the rule.
    """
    if len(runs) < 2:
        return None
    n = min(len(r["cases"]) for r in runs)
    buckets, table = [0.0, 0.05, 0.1, 0.2, 0.4, 0.8, 99.0], []
    for lo, hi in zip(buckets, buckets[1:]):
        rows = [i for i in range(n) if runs[0]["cases"][i]["gap"] is not None and lo <= runs[0]["cases"][i]["gap"] < hi]
        if not rows:
            continue
        flips = sum(1 for i in rows if len({r["cases"][i]["raw_pick"] for r in runs}) > 1)
        table.append({"gap_from": lo, "gap_to": hi, "states": len(rows), "ranking_flipped": flips,
                      "flip_rate": round(flips / len(rows), 2)})
    overall = sum(t["ranking_flipped"] for t in table), sum(t["states"] for t in table)
    return {"buckets": table, "flipped": overall[0], "states": overall[1],
            "flip_rate": round(overall[0] / max(1, overall[1]), 3),
            "current_unsure_gap": cfg["select"]["unsure_gap"],
            "sweep": sweep(runs)}


def sweep(runs):
    """What each candidate unsure_gap would have cost and bought, re-cut from the saved cases.

    For each threshold: how many states the model would still decide, and how many of the pilot's final
    commands would have differed between identical passes. The right threshold is the smallest one that
    buys zero.
    """
    n = min(len(r["cases"]) for r in runs)
    out = []
    for gap in (0.0, 0.05, 0.10, 0.20, 0.40, 0.80):
        decided = unstable = 0
        for i in range(n):
            if runs[0]["cases"][i]["gap"] is None:
                continue
            finals = set()
            for r in runs:
                c = r["cases"][i]
                finals.add(c["fallback_pick"] if (c["gap"] is not None and c["gap"] < gap) else c["raw_pick"])
            if runs[0]["cases"][i]["gap"] >= gap:
                decided += 1
            if len(finals) > 1:
                unstable += 1
        out.append({"unsure_gap": gap, "states_the_model_decides": decided,
                    "commands_that_differ_between_identical_passes": unstable})
    return out


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    return xs[len(xs) // 2] if xs else None


def summarise(name, runs):
    picks = runs[0]["picks"]
    flips = 0
    if len(runs) > 1:
        for i in range(len(picks)):
            if len({r["picks"][i] for r in runs}) > 1:
                flips += 1
    return {"pilot": name, "cases": len(picks), "passes": len(runs),
            "median_input_tokens": median(runs[0]["tokens"]),
            "median_latency_ms": median(runs[0]["latency"]),
            "picks": dict(Counter(picks).most_common()),
            "fallbacks": runs[0]["fallbacks"],
            "median_top_two_gap": round(median(runs[0]["gaps"]), 3) if runs[0]["gaps"] else None,
            "gap_under_unsure_gap": sum(1 for g in runs[0]["gaps"] if g < runs[0].get("unsure_gap", 1e9)),
            "cases_that_flipped_between_identical_passes": flips}


def agreement(a, b):
    """Split by whether the model actually decided.

    On a state where the unsure band fired, both pilots hand off to the same deterministic fallback, so
    they agree by construction. Counting those in makes the model look like the code rule when really it
    said nothing. The number that answers "is jev earning its latency" is the one where jev decided.
    """
    both = [(x, y) for x, y in zip(a["cases"], b["cases"]) if x["pick"] and y["pick"]]
    decided = [(x, y) for x, y in both if not y["fallback"]]
    fell_back = [(x, y) for x, y in both if y["fallback"]]
    agree = lambda pairs: round(sum(1 for x, y in pairs if x["pick"] == y["pick"]) / len(pairs), 3) if pairs else None
    return {"compared": len(both), "agreement_overall": agree(both),
            "states_the_model_decided": len(decided), "agreement_where_the_model_decided": agree(decided),
            "states_handed_to_the_fallback": len(fell_back), "agreement_on_those": agree(fell_back)}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--log", default="runs/2026-09-22/decisions.jsonl")
    p.add_argument("--pilots", default="code", help="comma separated: code, jev")
    p.add_argument("--cases", type=int, default=200, help="evenly spaced sample of the log (0 = all)")
    p.add_argument("--passes", type=int, default=1, help="repeats per pilot; jev answers can flip")
    p.add_argument("--boundary", type=Path, default=None, help="a boundary set from tools/boundary_set.py")
    p.add_argument("--env-files", nargs="*", default=[str(HERE.parent / "ground" / ".env"),
                                                      str(HERE.parent / ".env")])
    p.add_argument("--out", type=Path, default=None, help="write the comparison as JSON")
    args = p.parse_args()

    cfg = gc.validate(gc.DEFAULT)
    bad = dg.lint(cfg)
    if bad:
        raise SystemExit("the graph names state fields that do not exist: %s" % ", ".join(bad))
    ids = None
    if args.boundary:
        ids = [json.loads(l)["id"] for l in open(args.boundary, encoding="utf-8")]
    cases = load_cases(args.log, args.cases or None, ids)
    print("replaying %d states from %s against graph v%s (%s)"
          % (len(cases), args.log, cfg["version"], cfg["model"]))

    out = {"log": str(args.log), "graph_version": cfg["version"], "model": cfg["model"],
           "select": cfg["select"],
           "cases": len(cases), "pilots": {}, "metric_definitions": {
               "spin": metrics.SPIN_KEY, "unsure_band": list(metrics.UNSURE_BAND), "cell_units": metrics.CELL_UNITS}}
    raw = {}
    for name in args.pilots.split(","):
        name = name.strip()
        pilot = CodePilot(cfg) if name == "code" else JevPilot(cfg, args.env_files)
        passes = args.passes if name == "jev" else 1        # the code pilot is deterministic
        raw[name] = run_pilot(pilot, cases, cfg, passes)
        out["pilots"][name] = summarise(name, raw[name])
        s = out["pilots"][name]
        print("  %-5s %d cases, median %s input tokens, %s ms; fallbacks %s; flips between passes %d"
              % (name, s["cases"], s["median_input_tokens"], s["median_latency_ms"], s["fallbacks"],
                 s["cases_that_flipped_between_identical_passes"]))
    if "jev" in raw and args.passes > 1:
        cal = calibrate(raw["jev"], cfg)
        out["calibration"] = cal
        print()
        print("  jev's own ranking between identical passes, by top-two gap (rubric levels):")
        for b in cal["buckets"]:
            print("    %4.2f to %4.2f  %3d states  flipped %3d  (%.0f%%)"
                  % (b["gap_from"], b["gap_to"], b["states"], b["ranking_flipped"], 100 * b["flip_rate"]))
        print("    overall %d of %d states flipped (%.0f%%); unsure_gap is %.2f"
              % (cal["flipped"], cal["states"], 100 * cal["flip_rate"], cal["current_unsure_gap"]))
        print("  what each candidate unsure_gap would cost and buy:")
        for w in cal["sweep"]:
            print("    %4.2f  model decides %3d states  commands differing between passes %3d"
                  % (w["unsure_gap"], w["states_the_model_decides"],
                     w["commands_that_differ_between_identical_passes"]))
    if "code" in raw and "jev" in raw:
        out["code_vs_jev"] = agreement(raw["code"][0], raw["jev"][0])
        a = out["code_vs_jev"]
        print()
        print("  code vs jev: same direction on %.0f%% of %d states overall"
              % (100 * (a["agreement_overall"] or 0), a["compared"]))
        print("    where jev actually decided (the band did not fire): %.0f%% of %d states"
              % (100 * (a["agreement_where_the_model_decided"] or 0), a["states_the_model_decided"]))
        print("    where the band fired, both pilots took the same fallback: %d states"
              % a["states_handed_to_the_fallback"])
        print("  If jev agrees with the code rule wherever it decides, it is not earning its latency on this")
        print("  state yet: keep the rule and bring jev back when the state carries evidence no rule can read.")
    if args.out:
        # keep every case, so the comparison can be re-cut without paying for the calls again
        out["per_case"] = {name: runs[0]["cases"] for name, runs in raw.items()}
        args.out.write_text(json.dumps(out, indent=1), encoding="utf-8")
        print("\nwrote %s" % args.out)


if __name__ == "__main__":
    main()
