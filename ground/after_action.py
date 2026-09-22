"""After-action review: code summarises an episode, System Two revises the graph jev plays with.

The report is deliberately small (a few KB): outcome and numbers, per-head answer distributions and
confidence, failure patterns code can detect, and the last moments before the episode ended.
"""
import json
import time
from collections import Counter

import graph_config as gc

REVIEW_SYSTEM = (
    "You are the mission's System Two: a reviewer, not a player. A fast System One model (jev) plays Doom live by "
    "classifying a structured state document every half second with the typed questions in the decision graph "
    "(one narrow question per head; Choice heads pick an option, Noul heads answer yes/no); code owns thresholds, the "
    "option menus and the button mapping. Between episodes you read the after-action report and revise the graph so jev "
    "plays better next episode: reword instructions or option criteria (strings or JSON objects with what / not_for / "
    "examples that reference state fields such as surroundings.ahead.space, surroundings.left.ground, seen.exit.where, "
    "stuck), adjust thresholds, turn sizes, way_margin (hysteresis on direction changes), how often the goal is re-asked, "
    "and the standing order. Head names, head types and option names are fixed. Change few things per review, each tied "
    "to an observed problem, and say why in the rationale. Return the full config."
)


def summarise(rows, episode_rows, outcome, cfg):
    """Build the report from the decision rows of one episode."""
    ctrl = [r for r in episode_rows if r.get("kind") == "control"]
    if not ctrl:
        return None
    span = ctrl[-1]["t"] - ctrl[0]["t"]
    raw = [r["raw"] for r in ctrl if r.get("raw")]
    heads = {}
    for head in ("steer", "move", "turn", "strafe", "dodge", "fire", "use", "weapon", "goal"):
        asked = [r for r in ctrl if head in r["answers"]]
        if asked:
            conf = [r["confidence"].get(head, 0) for r in asked]
            heads[head] = {"asked": len(asked), "answers": dict(Counter(r["answers"][head] for r in asked).most_common()),
                           "mean_confidence": round(sum(conf) / len(conf), 2)}
    hp = [r["health"] for r in ctrl if r.get("health") is not None]
    turns = [r["answers"].get("turn") for r in ctrl]
    flips = sum(1 for a, b in zip(turns, turns[1:]) if a and b and ("left" in a.lower()) != ("left" in b.lower()) and "Hold" not in (a, b) and "around" not in (a + b).lower())
    holds = [r["answers"].get("move") == "Hold" for r in ctrl]
    longest_hold, run = 0, 0
    for h in holds:
        run = run + 1 if h else 0
        longest_hold = max(longest_hold, run)
    enemy_ticks = sum(1 for r in raw if r.get("ENEMY_COUNT"))
    damage_no_enemy = sum(max(0, a["health"] - b["health"]) for a, b in zip(ctrl, ctrl[1:])
                          if a.get("health") is not None and b.get("health") is not None and not (b.get("raw") or {}).get("ENEMY_COUNT"))
    moved = sum(abs(a["POS_X"] - b["POS_X"]) + abs(a["POS_Y"] - b["POS_Y"]) for a, b in zip(raw, raw[1:])) if raw else 0
    last = []
    for r in ctrl[-8:]:
        s = r.get("seen", {})
        last.append(f"hp={r.get('health')} goal={r.get('goal')} ahead={s.get('ahead')}/{s.get('ahead_ground')} left={s.get('left')}/{s.get('left_ground')} "
                    f"right={s.get('right')}/{s.get('right_ground')} arm={s.get('at_arms_length_ahead')} exit={s.get('exit')} stuck={s.get('stuck')} -> "
                    + " ".join(f"{k}={v}" for k, v in r["answers"].items()))
    modes = Counter(str(r.get("AHEAD_KIND")) for r in raw if r.get("AHEAD_KIND") is not None)
    bins = Counter((round(r["POS_X"] / 128) * 128, round(r["POS_Y"] / 128) * 128) for r in raw if r.get("POS_X") is not None)
    walk = {"distinct_128u_bins": len(bins), "revisit_ratio": round(1 - len(bins) / max(1, len(raw)), 2),
            "most_visited": [f"({x},{y}) x{n}" for (x, y), n in bins.most_common(5)],
            "hints_from_system_two": sum(1 for r in episode_rows if r.get("kind") == "system_two_hint")}
    return {
        "graph_version": cfg.get("version"),
        "outcome": outcome,
        "level": max((r.get("LEVEL", 0) or 0) for r in raw) if raw else None,
        "ahead_kind_ticks": dict(modes.most_common()),
        "exit_line_seen": any((r.get("EXIT_DIST") or 0) > 0 for r in raw),
        "walk": walk,

        "keys_held_at_end": (raw[-1].get("KEYS") if raw else None),
        "duration_s": round(span),
        "decisions": len(ctrl),
        "kills": max((r.get("kills", 0) or 0) for r in ctrl) if any("kills" in r for r in ctrl) else None,
        "health": {"start": hp[0] if hp else None, "min": min(hp) if hp else None, "end": hp[-1] if hp else None},
        "damage_taken_with_no_enemy_in_view": damage_no_enemy,
        "ticks_with_enemy_in_view": enemy_ticks,
        "explored_cells": max((r.get("EXPLORED_CELLS", 0) or 0) for r in raw) if raw else None,
        "path_units": round(moved),
        "stuck_ticks": sum(1 for r in raw if r.get("STUCK") is True),
        "patterns": {"turn_direction_flips": flips, "longest_hold_streak": longest_hold,
                     "backward_answers": heads.get("move", {}).get("answers", {}).get("Backward", 0)},
        "heads": heads,
        "goals_used": dict(Counter(r.get("goal") for r in ctrl)),
        "last_moments": last,
    }


def review(system_two, report, cfg):
    """Ask System Two for a revised graph; returns (new_cfg, rationale, issues, meta) or raises."""
    prompt = ("AFTER-ACTION REPORT (one episode):\n" + json.dumps(report, indent=1) +
              "\n\nCURRENT GRAPH CONFIG (revise and return in full):\n" + json.dumps({k: v for k, v in cfg.items() if k != "version"}, indent=1))
    t0 = time.time()
    result = system_two.structured(REVIEW_SYSTEM, prompt, gc.review_schema())
    new_cfg = gc.validate(result["config"])
    meta = {"latency_ms": int((time.time() - t0) * 1000), "model": result.get("model"), "cost_usd": result.get("cost_usd"), "tokens": result.get("tokens")}
    return new_cfg, result.get("rationale", ""), result.get("issues", []), meta
