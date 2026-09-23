"""Where an attempt's ticks went, and why the player was not moving. Read-only over graded runs.

The suite score says an attempt did not finish. This says what it was doing instead, in the executor's own
accounting: moving, turning, looking around, recovering from a watchdog trip, or rubbing -- pressed
against geometry at full throttle with somewhere to be. That last one does not show up as a freeze,
because a player scraping a corner still covers ground, and it was 46% of an oracle run that had the
whole level and the exit in hand.

    python research/where_the_time_goes.py research/out/<run>
"""
import argparse
import glob
import json
import os
from collections import Counter

ORDER = ("move_ticks", "full_speed_ticks", "turn_ticks", "rub_ticks", "look_ticks", "recover_ticks",
         "safe_ticks", "no_plan_ticks")


def one(path):
    a = json.load(open(path, encoding="utf-8"))
    st = a.get("executor_stats") or {}
    n = max(1, st.get("ticks", 1))
    row = {"file": os.path.basename(path), "map": a.get("map"), "seed": a.get("seed"),
           "end": a.get("end_reason"), "game_s": a.get("game_seconds"), "deaths": a.get("deaths"),
           "oracle": a.get("oracle"), "tics": st.get("ticks", 0),
           "tic_rate": a.get("tic_rate")}
    for k in ORDER:
        row[k.replace("_ticks", "")] = round(100.0 * st.get(k, 0) / n)
    row["watchdog"] = sum((a.get("watchdog_trips") or {}).values())
    ctx = Counter()
    for c in a.get("watchdog_context") or []:
        ctx["%s ahead=%s plan=%s" % (c.get("mode"), c.get("ahead"), c.get("has_plan"))] += 1
    row["freeze_context"] = dict(ctx.most_common(3))
    g = a.get("geometry_stats") or {}
    if g:
        row["seen_lines"] = "%s/%s" % (g.get("admitted"), g.get("classified"))
        row["doors"] = g.get("doors")
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    a = ap.parse_args()
    rows = [one(p) for p in sorted(glob.glob(os.path.join(a.run_dir, "attempt-*.json")))]
    if not rows:
        raise SystemExit("no attempt-*.json in %s" % a.run_dir)
    head = ("map", "seed", "end", "game_s", "deaths", "tics", "tic_rate", "move", "full_speed", "turn",
            "rub", "look", "recover", "safe", "no_plan", "watchdog")
    print("  ".join("%-9s" % h for h in head))
    for r in rows:
        print("  ".join("%-9s" % r.get(h, "-") for h in head))
    avg = {h: (sum(r.get(h) or 0 for r in rows) / len(rows)) for h in head[6:]}
    print("  ".join("%-9s" % x for x in ("MEAN", "", "", "", "", "")) +
          "  " + "  ".join("%-9.0f" % avg[h] for h in head[6:]))
    ctx = Counter()
    for r in rows:
        ctx.update(r["freeze_context"])
    if ctx:
        print("\nfreeze contexts: %s" % ", ".join("%s x%d" % kv for kv in ctx.most_common(5)))
    if rows[0].get("seen_lines"):
        print("seen lines: %s" % ", ".join("%s" % r.get("seen_lines") for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())
