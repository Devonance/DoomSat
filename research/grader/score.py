"""Turn one attempt into one graded row. Charter 6.4 and 7.

Input is the attempt JSON the runner writes (`research/runner.py` builds it; the schema is documented in
`attempt_schema()` below). Output is a graded JSON with the score, the progress the score rests on, and
every frozen metric, so a ledger row never has to recompute anything.

The grader is the only thing that opens the WAD, and it does so only to answer "how much farther was it".
"""
import argparse
import importlib.util
import json
import math
import os

from . import wad

_FM = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frozen_metrics.py")
_spec = importlib.util.spec_from_file_location("doomsat_frozen_metrics", _FM)
fm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fm)

_FIELDS = {}


def _last(rows, key, default=0):
    """The high-water mark of a counter, not its last value.

    These count up within an episode and restart with it, so reading the last row reports whatever
    happened after the final reset -- which for an attempt that ran its level budget is zero. One flight
    was recorded as pressing Use no times when it had pressed 11.
    """
    seen = [int(v) for v in ((r.get("raw") or {}).get(key) for r in rows) if v is not None]
    return max(seen) if seen else int(default or 0)


def door_recall(level, rows, within=160.0):
    """Real doors the player got close to, and how many of them the pilot ever offered as a candidate.

    Precision without recall is a trap: rejecting every suspect scores a perfect precision and leaves the
    player unable to leave any room a door closes off. This is the other half, and only the grader can
    compute it, because only the grader is allowed to know where the doors really are.
    """
    real = []
    for line in level.lines:
        if line[3] in wad.DOOR or line[3] in wad.KEY_DOOR:
            a, b = level.verts[line[0]], level.verts[line[1]]
            real.append(((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0))
    if not real:
        return {"real_doors": 0, "came_into_view": 0, "offered": 0, "door_recall": None}
    near, offered = set(), set()
    for r in rows:
        raw = r.get("raw") or {}
        if raw.get("POS_X") is None:
            continue
        px, py = float(raw["POS_X"]), float(raw["POS_Y"])
        for i, (dx, dy) in enumerate(real):
            if math.hypot(dx - px, dy - py) <= 512.0:
                near.add(i)
        for c in r.get("cand_xy") or []:
            if c.get("kind") != "door":
                continue
            for i, (dx, dy) in enumerate(real):
                if math.hypot(dx - c["x"], dy - c["y"]) <= within:
                    offered.add(i)
    seen = len(near)
    return {"real_doors": len(real), "came_into_view": seen, "offered": len(offered & near),
            "door_recall": round(len(offered & near) / seen, 4) if seen else None}


def _precision(rows, attempt):
    """Use presses that opened something, over presses. The number that says whether the senses are
    telling the truth about what is a door."""
    presses = _last(rows, "DOOR_PRESSES", attempt.get("door_presses", 0))
    opens = _last(rows, "DOOR_OPENS", attempt.get("door_opens", 0))
    return round(opens / presses, 4) if presses else None


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

    # The closest the attempt ever came. Track t3 scores THIS, not where it ended: see
    # frozen_metrics.attempt_score. The gap between the two is how you see thrashing, and it is reported
    # as `progress` beside it rather than folded into one number.
    best = start_d
    for px, py in ([(float(r["raw"]["POS_X"]), float(r["raw"]["POS_Y"])) for r in rows
                    if (r.get("raw") or {}).get("POS_X") is not None] + [tuple(end)]):
        # `end` is in the list because the closest approach may BE the last position, and under t3 the
        # score is the closest approach: leaving it out scored an attempt that walked straight at the
        # exit and ran out of clock as though it had never left the start.
        d = field.at(px, py)
        if d is not None and (best is None or d < best):
            best = d

    budget = float(attempt.get("budget_s") or fm.LEVEL_BUDGET_S)
    level_time = attempt.get("game_seconds")
    completed = attempt.get("end_reason") == "exit" and level_time is not None and level_time <= budget
    prog = fm.progress(start_d, remaining)
    prog_best = fm.progress(start_d, best)

    out = {
        "map": attempt["map"], "seed": attempt.get("seed"), "tier": attempt.get("tier"),
        "decider": attempt.get("decider"),
        "run_id": attempt.get("run_id"), "versions": attempt.get("versions", {}),
        "commit": attempt.get("commit"), "dirty": attempt.get("dirty"),
        "score": round(fm.attempt_score(completed, level_time, prog_best, budget), 4),
        "completed": bool(completed),
        "level_time": level_time,
        "end_reason": attempt.get("end_reason"),
        "deaths": int(attempt.get("deaths") or 0),
        "deaths_per_minute": round(fm.deaths_per_minute(int(attempt.get("deaths") or 0), level_time), 3),
        # charter phase 2: a freeze is only ever visible as the onboard watchdog having had to step in
        "watchdog_trips": attempt.get("watchdog_trips") or {},
        # None, not 0, when nothing reported them. A flight attempt carries no watchdog_trips at all:
        # Doom.cpp initialises m_watchdogTrips to zero and never assigns it, so the WATCHDOG_TRIPS channel
        # has always been zero on the wire. Summing an absent dict gave 0 and every flight report said
        # "0 freezes" while the payload log filled with them. An unmeasured thing has to read as unmeasured.
        "freezes": (sum(attempt["watchdog_trips"].values())
                    if attempt.get("watchdog_trips") is not None else None),
        "executor_stats": attempt.get("executor_stats") or {},
        "cache_hit_rate": attempt.get("cache_hit_rate"),
        "model_unavailable": attempt.get("model_unavailable", 0),
        "door_presses": _last(rows, "DOOR_PRESSES", attempt.get("door_presses", 0)),
        "door_opens": _last(rows, "DOOR_OPENS", attempt.get("door_opens", 0)),
        "door_precision": _precision(rows, attempt),
        "door_recall": door_recall(level, rows),
        "exit_ever_seen": any((r.get("raw") or {}).get("EXIT_DIST") for r in rows),
        "progress": round(prog, 4),
        "progress_best": round(prog_best, 4),
        # how much of the closest approach was given back afterwards. A large number here is a pilot that
        # found the way and then lost it, which is a different failure from one that never found it.
        "progress_given_back": round(prog_best - prog, 4),
        "oracle": attempt.get("oracle"),
        "geometry": attempt.get("geometry"),
        "geometry_stats": attempt.get("geometry_stats"),
        "tic_rate": attempt.get("tic_rate"),
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
        "decision_reasons": fm.decision_reasons(ctl),
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
