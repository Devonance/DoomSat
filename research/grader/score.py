"""Turn one attempt into one graded row. Charter 6.4 and 7.

Input is the attempt JSON the runner writes (`research/runner.py` builds it; the schema is documented in
`attempt_schema()` below). Output is a graded JSON with the score, the progress the score rests on, and
every frozen metric, so a ledger row never has to recompute anything.

The grader is the only thing that opens the WAD, and it does so only to answer "how much farther was it".
"""
import argparse
import importlib.util
import json
import os

from . import wad

_FM = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frozen_metrics.py")
_spec = importlib.util.spec_from_file_location("doomsat_frozen_metrics", _FM)
fm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fm)

_FIELDS = {}


def field_for(wad_path, map_name):
    """Distance fields are expensive and pure, so one per (wad, map) per process."""
    key = (os.path.abspath(wad_path), map_name)
    if key not in _FIELDS:
        level = wad.Level(wad_path, map_name)
        _FIELDS[key] = (level, wad.DistanceField(level))
    return _FIELDS[key]


def attempt_schema():
    return {
        "run_id": "string, one per invocation of the runner",
        "tier": "bench | flight",
        "wad_path": "absolute path to the IWAD, read by the grader only",
        "map": "map name, e.g. E1M1",
        "seed": "int",
        "skill": "int",
        "budget_s": "float, the level budget this attempt was run under",
        "start_xy": "[x, y] the player 1 start the attempt actually began at",
        "end_xy": "[x, y] where it stopped, or where it died",
        "end_reason": "exit | timeout | death | crash",
        "game_seconds": "float, level start to end",
        "deaths": "int",
        "decisions": "list of control rows in the shape ground/pilot.py logs",
        "versions": "dict: commit, graph_version, model, levels_sha, knowledge_sha, track",
    }


def grade(attempt):
    rows = attempt.get("decisions") or []
    level, field = field_for(attempt["wad_path"], attempt["map"])
    start = attempt.get("start_xy") or list(level.start())
    start_d = field.at(*start)

    end = attempt.get("end_xy")
    if end is None:
        pos = [(r["raw"]["POS_X"], r["raw"]["POS_Y"]) for r in rows
               if (r.get("raw") or {}).get("POS_X") is not None]
        end = list(pos[-1]) if pos else start
    remaining = field.at(*end)

    # The closest the attempt ever came. Not what the score uses -- charter 6.4 scores where it ended, so
    # walking away from the exit costs -- but the gap between the two is how you see thrashing.
    best = start_d
    for r in rows:
        raw = r.get("raw") or {}
        if raw.get("POS_X") is None:
            continue
        d = field.at(float(raw["POS_X"]), float(raw["POS_Y"]))
        if d is not None and (best is None or d < best):
            best = d

    budget = float(attempt.get("budget_s") or fm.LEVEL_BUDGET_S)
    level_time = attempt.get("game_seconds")
    completed = attempt.get("end_reason") == "exit" and level_time is not None and level_time <= budget
    prog = fm.progress(start_d, remaining)

    out = {
        "map": attempt["map"], "seed": attempt.get("seed"), "tier": attempt.get("tier"),
        "decider": attempt.get("decider"),
        "run_id": attempt.get("run_id"), "versions": attempt.get("versions", {}),
        "commit": attempt.get("commit"), "dirty": attempt.get("dirty"),
        "score": round(fm.attempt_score(completed, level_time, prog, budget), 4),
        "completed": bool(completed),
        "level_time": level_time,
        "end_reason": attempt.get("end_reason"),
        "deaths": int(attempt.get("deaths") or 0),
        "deaths_per_minute": round(fm.deaths_per_minute(int(attempt.get("deaths") or 0), level_time), 3),
        # charter phase 2: a freeze is only ever visible as the onboard watchdog having had to step in
        "watchdog_trips": attempt.get("watchdog_trips") or {},
        "freezes": sum((attempt.get("watchdog_trips") or {}).values()),
        "executor_stats": attempt.get("executor_stats") or {},
        "cache_hit_rate": attempt.get("cache_hit_rate"),
        "progress": round(prog, 4),
        "progress_best": round(fm.progress(start_d, best), 4),
        "start_distance": None if start_d is None else round(start_d, 1),
        "remaining_distance": None if remaining is None else round(remaining, 1),
        # the grader's own caveats, so a number is never read without them
        "exit_reachable_from_start": start_d is not None,
        "level_has_teleport": level.has_teleport(),
        "exit_lines": len(level.exit_lines()),
        "metrics": metrics_of(rows),
    }
    if start_d is None:
        out["warning"] = ("no walkable route from the start to a normal exit in the grader's model, so "
                          "progress is meaningless for this map: score on completed only")
    elif level.has_teleport():
        out.setdefault("warning", "this map has teleports, which the grader does not model: progress may "
                                  "understate a route that goes through one")
    return out


def metrics_of(rows):
    ctl = [r for r in rows if r.get("kind") == "control"]
    ages = fm.decision_age_ms(ctl)
    return {
        "decisions": len(ctl),
        "decisions_per_s": round(fm.decisions_per_s(ctl), 3),
        "decision_age_p50_ms": fm.percentile(ages, 0.50),
        "decision_age_p95_ms": fm.percentile(ages, 0.95),
        "decision_age_complete": round(fm.decision_age_complete(ctl), 3),
        "jev_share": None if fm.jev_share(ctl) is None else round(fm.jev_share(ctl), 4),
        "fallback_rate": None if fm.fallback_rate(ctl) is None else round(fm.fallback_rate(ctl), 4),
        "speed_explore": round(fm.speed_explore(ctl), 2),
        "coverage_rate": round(fm.coverage_rate(ctl), 2),
        "revisit_fraction": round(fm.revisit_fraction(ctl), 4),
        "spin_rate": round(fm.spin_rate(fm.samples(ctl)), 5),
        "idle_fraction": round(fm.idle_fraction(ctl), 4),
        "watchdog_trips": fm.watchdog_trips(ctl),
        "mode_share": fm.mode_share(rows),
        "deaths_by_mode": fm.deaths_by_mode(rows),
        "tokens_per_decision": round(fm.tokens_per_decision(ctl), 1),
        "cells": len(fm.cells(fm.samples(ctl))),
        "path_units": round(fm.path_units(fm.samples(ctl)), 1),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("attempts", nargs="+", help="attempt JSON files written by the runner")
    ap.add_argument("--out", default=None, help="directory for the graded JSON (default: beside the attempt)")
    a = ap.parse_args(argv)
    for path in a.attempts:
        attempt = json.load(open(path, encoding="utf-8"))
        graded = grade(attempt)
        dest = os.path.join(a.out or os.path.dirname(os.path.abspath(path)),
                            "graded-%s-%s.json" % (graded["map"], graded["seed"]))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        json.dump(graded, open(dest, "w", encoding="utf-8"), indent=1)
        print("%-6s seed %-3s score %.3f  %s  progress %.2f (best %.2f)  %s"
              % (graded["map"], graded["seed"], graded["score"],
                 "completed in %.0f s" % graded["level_time"] if graded["completed"] else graded["end_reason"],
                 graded["progress"], graded["progress_best"], dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
