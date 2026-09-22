"""After-action review: code summarises an episode, System Two revises the graph jev plays with.

The report is built from the heads the episode actually asked, never from a hard-coded list, so it cannot
go stale the way the old one did: it summarised `steer`, `move` and `strafe`, heads that had not existed
for several graph versions, and reported `longest_hold_streak: 0` by construction. Sonnet then tuned from
that constant. `coverage` in the report names any head that was asked and got no statistics, and the unit
test in tests/test_after_action.py fails if that list is ever non-empty.
"""
import json
import time
from collections import Counter

import graph_config as gc
import metrics

REVIEW_SYSTEM = (
    "You are the mission's System Two: a reviewer, not a player. A fast System One model (jev) plays Doom live. "
    "Every half second code builds a structured state and asks jev the judgments that have no exact rule behind "
    "them: one Score per open sector (`how promising is this direction`, asked once per offered direction on a "
    "shared rubric), one Score for how dangerous the scene is, and every few ticks a goal Choice. Everything else "
    "is code: the mode machine (EXPLORE, APPROACH, OPERATE, FIGHT, RECOVER), walking, doors, firing, weapon "
    "selection, aiming, sidestepping, the hysteresis on the committed direction and the fallback when jev is "
    "unsure. Between episodes you read the after-action report and revise the graph: reword the questions, "
    "rewrite the Score rubric levels, reword the goal options, and adjust the numbers in `thresholds` and "
    "`select`. Change few things per review, each tied to a number in the report, and say why in the rationale. "
    "Return the full config."
)


def head_group(key):
    """`s_left`, `s_ahead` ... all belong to the one `sector` head; every other key is its own head."""
    return "sector" if key.startswith("s_") else key


def summarise(rows, episode_rows, outcome, cfg):
    """Build the report from the decision rows of one episode."""
    ctrl = [r for r in episode_rows if r.get("kind") == "control"]
    if not ctrl:
        return None
    span = ctrl[-1]["t"] - ctrl[0]["t"]
    raw = [r["raw"] for r in ctrl if r.get("raw")]

    # ---- per-head statistics, from the heads the episode actually asked (issue 3)
    asked = Counter()
    for r in ctrl:
        for k in r.get("answers", {}):
            asked[head_group(k)] += 1
    heads = {}
    for group in asked:
        keys = [k for r in ctrl for k in r.get("answers", {}) if head_group(k) == group]
        vals = [r["answers"][k] for r in ctrl for k in r.get("answers", {}) if head_group(k) == group]
        conf = [r.get("confidence", {}).get(k, 0.0) for r in ctrl for k in r.get("answers", {}) if head_group(k) == group]
        numeric = []
        for v in vals:
            try:
                numeric.append(float(v))
            except (TypeError, ValueError):
                numeric = None
                break
        stats = {"asked": asked[group], "mean_confidence": round(sum(conf) / max(1, len(conf)), 2)}
        if numeric:
            numeric.sort()
            stats["score"] = {"min": round(numeric[0], 2), "median": round(numeric[len(numeric) // 2], 2),
                              "max": round(numeric[-1], 2),
                              "mean": round(sum(numeric) / len(numeric), 2)}
            if group == "sector":
                per = Counter(k for k in keys)
                stats["asked_per_direction"] = dict(per.most_common())
        else:
            stats["answers"] = dict(Counter(vals).most_common())
        heads[group] = stats
    live = sorted({head_group(k) for r in ctrl for k in r.get("answers", {})})
    coverage = [h for h in live if h not in heads or not heads[h]["asked"]]

    # ---- what code did with the answers
    picks = [r.get("pick") for r in ctrl if r.get("pick")]
    detail = [r.get("select") or {} for r in ctrl]
    fallbacks = Counter(d.get("fallback") for d in detail if d.get("fallback"))
    gaps = sorted(d["gap"] for d in detail if d.get("gap") is not None)
    modes = Counter(r.get("mode") for r in ctrl if r.get("mode"))
    held = sum(1 for d in detail if d.get("held"))
    commit_runs, run = [], 0
    for a, b in zip(picks, picks[1:]):
        run = run + 1 if a == b else 0
        commit_runs.append(run)
    longest_commit = max(commit_runs) + 1 if commit_runs else 0

    # ---- what the walk actually did
    hp = [r["health"] for r in ctrl if r.get("health") is not None]
    # One definition of each of these, shared with tools/replay.py, so runs stay comparable (ground/metrics.py).
    pos = metrics.samples(ctrl)
    spins = metrics.spin_windows(pos)
    bins = metrics.cells(pos)
    moved = metrics.path_units(pos)
    damage_no_enemy = sum(max(0, a["health"] - b["health"]) for a, b in zip(ctrl, ctrl[1:])
                          if a.get("health") is not None and b.get("health") is not None
                          and not (b.get("raw") or {}).get("ENEMY_COUNT"))
    tokens = sorted((r.get("usage") or {}).get("input_tokens", 0) for r in ctrl if r.get("usage"))

    last = []
    for r in ctrl[-8:]:
        s = r.get("seen") or {}
        sectors = ", ".join("%s %s/%s" % (d, (s.get(d) or {}).get("space"), (s.get(d) or {}).get("ground"))
                            for d in ("ahead", "left", "right", "behind") if isinstance(s.get(d), dict))
        last.append("hp=%s mode=%s goal=%s pick=%s [%s] arm=%s stuck=%s -> %s"
                    % (r.get("health"), r.get("mode"), r.get("goal"), r.get("pick"), sectors,
                       (r.get("here") or {}).get("at_arms_length"), (r.get("here") or {}).get("stuck"),
                       " ".join("%s=%s" % (k, v) for k, v in r.get("answers", {}).items())))
    return {
        "graph_version": cfg.get("version"),
        "model": cfg.get("model"),
        "outcome": outcome,
        "level": max((r.get("LEVEL", 0) or 0) for r in raw) if raw else None,
        "duration_s": round(span),
        "decisions": len(ctrl),
        "heads": heads,
        "coverage_gaps": coverage,
        "selection": {"picks": dict(Counter(picks).most_common()),
                      "held_by_hysteresis": held,
                      "longest_same_direction_run": longest_commit,
                      "fallbacks": dict(fallbacks),
                      "median_top_two_gap": round(gaps[len(gaps) // 2], 3) if gaps else None,
                      "gaps_under_unsure_gap": sum(1 for g in gaps if g < cfg["select"]["unsure_gap"])},
        "modes": dict(modes.most_common()),
        "walk": {"distinct_128u_bins": len(bins),
                 "revisit_ratio": round(1 - len(bins) / max(1, len(pos)), 2),
                 metrics.SPIN_KEY: spins,
                 "path_units": round(moved),
                 "most_visited": ["(%d,%d) x%d" % (x, y, n) for (x, y), n in bins.most_common(5)],
                 "hints_from_system_two": sum(1 for r in episode_rows if r.get("kind") == "system_two_hint")},
        "ahead_kind_ticks": dict(Counter(str(r.get("AHEAD_KIND")) for r in raw if r.get("AHEAD_KIND") is not None).most_common()),
        "exit_line_seen": any((r.get("EXIT_DIST") or 0) > 0 for r in raw),
        "keys_held_at_end": (raw[-1].get("KEYS") if raw else None),
        "kills": max((r.get("kills", 0) or 0) for r in ctrl) if any("kills" in r for r in ctrl) else None,
        "health": {"start": hp[0] if hp else None, "min": min(hp) if hp else None, "end": hp[-1] if hp else None},
        "damage_taken_with_no_enemy_in_view": damage_no_enemy,
        "ticks_with_enemy_in_view": sum(1 for r in raw if r.get("ENEMY_COUNT")),
        "explored_cells": max((r.get("EXPLORED_CELLS", 0) or 0) for r in raw) if raw else None,
        "stuck_ticks": sum(1 for r in raw if r.get("STUCK") is True),
        "median_input_tokens": tokens[len(tokens) // 2] if tokens else None,
        "goals_used": dict(Counter(r.get("goal") for r in ctrl)),
        "last_moments": last,
    }


def review(system_two, report, cfg, retries=1):
    """Ask System Two for a revised graph; returns (new_cfg, rationale, issues, meta) or raises.

    A revision code refuses comes straight back with the reason, so the reviewer can see its edit fail and
    fix it. Silently trimming it, as the old `validate` did, is what made ten reviews in a row re-fix the
    same truncation.
    """
    base = ("AFTER-ACTION REPORT (one episode):\n" + json.dumps(report, indent=1) +
            "\n\n" + gc.limits_note() +
            "\n\nCURRENT GRAPH CONFIG (revise and return in full):\n"
            + json.dumps({k: v for k, v in cfg.items() if k not in ("version", "model")}, indent=1))
    prompt, t0, last = base, time.time(), None
    for attempt in range(retries + 1):
        result = system_two.structured(REVIEW_SYSTEM, prompt, gc.review_schema())
        try:
            new_cfg = gc.validate(result["config"])
        except gc.GraphError as e:
            last = e
            prompt = base + ("\n\nYOUR PREVIOUS REPLY WAS REJECTED BY CODE: %s\nFix exactly that and return "
                             "the full config again." % e)
            continue
        meta = {"latency_ms": int((time.time() - t0) * 1000), "model": result.get("model"),
                "cost_usd": result.get("cost_usd"), "tokens": result.get("tokens"), "attempts": attempt + 1}
        return new_cfg, result.get("rationale", ""), result.get("issues", []), meta
    raise gc.GraphError("System Two could not produce a valid graph in %d attempts: %s" % (retries + 1, last))
