"""Summarise a pilot run from out/decisions.jsonl: who decided what, how often, how fast, and whether the player moved.

Head statistics come from the heads the run actually asked, so this cannot go stale when the graph
changes. The walk numbers use the frozen definitions in ground/metrics.py, so they are the same numbers
the after-action report and tools/replay.py print.

    python tools/run_report.py [out/decisions.jsonl]
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ground"))

import metrics                                  # noqa: E402
from after_action import head_group             # noqa: E402

path = Path(sys.argv[1] if len(sys.argv) > 1 else HERE.parent / "out" / "decisions.jsonl")
rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
ctrl = [r for r in rows if r.get("kind") == "control"]
if not ctrl:
    sys.exit("no control decisions in " + str(path))

span = ctrl[-1]["t"] - ctrl[0]["t"]
lat = sorted(r.get("latency_ms", 0) for r in ctrl)
cmd = sorted(r.get("cmd_ms", 0) for r in ctrl)
tok = sorted((r.get("usage") or {}).get("input_tokens", 0) for r in ctrl if r.get("usage"))
pct = lambda xs, p: xs[min(len(xs) - 1, int(len(xs) * p))] if xs else 0
print(f"run span {span:.0f} s, {len(ctrl)} decisions ({len(ctrl) / max(span, 1):.2f}/s)")
print(f"System One ({ctrl[0].get('model')}, graph v{ctrl[0].get('graph_version')}): latency median "
      f"{pct(lat, 0.5)} ms p95 {pct(lat, 0.95)} ms; command issue median {pct(cmd, 0.5)} ms p95 "
      f"{pct(cmd, 0.95)} ms; input tokens median {pct(tok, 0.5)}")

heads = Counter()
answers = {}
for r in ctrl:
    for k, v in r.get("answers", {}).items():
        g = head_group(k)
        heads[g] += 1
        answers.setdefault(g, []).append(v)
for g, n in heads.most_common():
    vals = answers[g]
    try:
        nums = sorted(float(v) for v in vals)
        shape = f"score min {nums[0]:.2f} median {nums[len(nums) // 2]:.2f} max {nums[-1]:.2f}"
    except (TypeError, ValueError):
        shape = ", ".join(f"{k} {c}" for k, c in Counter(vals).most_common(4))
    print(f"  {g:8s} asked {n:5d}  {shape}")
silent = sum(1 for r in ctrl if not r.get("answers"))
if silent:
    print(f"  {'(code)':8s} {silent} ticks decided by code alone (OPERATE / RECOVER / DONE: exact rules)")

modes = Counter(r.get("mode") for r in ctrl if r.get("mode"))
if modes:
    print("  modes: " + ", ".join(f"{k} {v}" for k, v in modes.most_common()))
picks = Counter(r.get("pick") for r in ctrl if r.get("pick"))
if picks:
    print("  directions: " + ", ".join(f"{k} {v}" for k, v in picks.most_common()))
sel = [r.get("select") or {} for r in ctrl]
fb = Counter(d.get("fallback") for d in sel if d.get("fallback"))
held = sum(1 for d in sel if d.get("held"))
if sel:
    print(f"  selection: {held} ticks held by hysteresis, fallbacks {dict(fb) or 'none'}")

samples = metrics.samples(ctrl)
if samples:
    xs = [s[1] for s in samples]
    ys = [s[2] for s in samples]
    cells = metrics.cells(samples)
    print(f"  player: x {min(xs):.0f}..{max(xs):.0f}  y {min(ys):.0f}..{max(ys):.0f}  "
          f"path ~{metrics.path_units(samples):.0f} units  {len(cells)} distinct {metrics.CELL_UNITS}-unit cells  "
          f"stuck {sum(1 for r in ctrl if (r.get('raw') or {}).get('STUCK'))}/{len(ctrl)}")
    print(f"  spin: {metrics.spin_windows(samples)} tick windows, {metrics.spin_seconds(samples)} "
          f"{metrics.SPIN_WINDOW_SECONDS:.0f}s windows, {metrics.spin_rate(samples):.3f} per second "
          f"(compare designs on the per-second figure)")
hp = [r["health"] for r in ctrl if r.get("health") is not None]
if hp:
    print(f"  health: start {hp[0]} min {min(hp)} end {hp[-1]}")
arms = Counter(str((r.get("raw") or {}).get("AHEAD_KIND")) for r in ctrl if (r.get("raw") or {}).get("AHEAD_KIND"))
if arms:
    print("  at arm's length: " + ", ".join(f"{k} {v}" for k, v in arms.most_common()))

bumps = [r for r in rows if r.get("kind") == "system_two_hint"]
if bumps:
    med = sorted(b["latency_ms"] for b in bumps)[len(bumps) // 2]
    print(f"  System Two bumps: {len(bumps)} (median {med} ms): "
          + "; ".join(f"{b['bearing_deg']} deg/{b['ttl']} s" for b in bumps[-6:]))
levels = [r for r in rows if r.get("kind") == "level"]
episodes = sorted({r.get("episode") for r in ctrl if r.get("episode") is not None})
print(f"  levels finished: {len(levels)} "
      + ", ".join(f"level {r['finished']} after {r['controls']} decisions" for r in levels)
      + f"; episodes played: {len(episodes)}")

reviews = [r for r in rows if r.get("kind") == "after_action"]
rerr = [r for r in rows if r.get("kind") == "after_action_error"]
print(f"System Two: {len(reviews)} after-action reviews, {len(rerr)} errors")
for r in reviews:
    tk = " ".join(f"{m.split('-')[1]}:{v[0]}in/{v[1]}out" for m, v in (r.get("tokens") or {}).items())
    tries = r.get("attempts")
    print(f"  [{r.get('outcome')}] -> graph v{r.get('graph_version')} {r.get('latency_ms')} ms "
          f"${r.get('cost_usd') or 0:.3f} {tk}" + (f" ({tries} attempts)" if tries and tries > 1 else ""))
    print(f"     {str(r.get('rationale'))[:220]}")
    for c in (r.get("changes") or [])[:8]:
        print(f"     - {c}")
for r in rerr:
    print(f"  rejected: {str(r.get('error'))[:200]}")
