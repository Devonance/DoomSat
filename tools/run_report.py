"""Summarise a pilot run from out/decisions.jsonl: who decided what, how often, how fast, and whether the player moved.

    python tools/run_report.py [out/decisions.jsonl]
"""
import json
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "out" / "decisions.jsonl")
rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
ctrl = [r for r in rows if r.get("kind") == "control"]
plans = [r for r in rows if r.get("kind") == "plan"]
errors = [r for r in rows if r.get("kind") == "plan_error"]
if not ctrl:
    sys.exit("no control decisions in " + str(path))
span = ctrl[-1]["t"] - ctrl[0]["t"]
lat = sorted(r["latency_ms"] for r in ctrl)
print(f"run span {span:.0f} s")
cmd = sorted(r.get("cmd_ms", 0) for r in ctrl)
print(f"System One ({ctrl[0].get('model')}): {len(ctrl)} decisions, {len(ctrl) / max(span, 1):.2f}/s, latency median {lat[len(lat) // 2]} ms p95 {lat[int(len(lat) * 0.95) - 1]} ms; command issue median {cmd[len(cmd) // 2]} ms p95 {cmd[int(len(cmd) * 0.95) - 1]} ms")
for head in ("move", "turn", "strafe", "dodge", "fire", "use", "weapon"):
    print(f"  {head:7s}", ", ".join(f"{k} {v}" for k, v in Counter(r["answers"].get(head) for r in ctrl).most_common(4)))
raw = [r["raw"] for r in ctrl if r.get("raw") and r["raw"].get("POS_X") is not None]
if raw:
    xs, ys = [r["POS_X"] for r in raw], [r["POS_Y"] for r in raw]
    moved = sum(abs(a["POS_X"] - b["POS_X"]) + abs(a["POS_Y"] - b["POS_Y"]) for a, b in zip(raw, raw[1:]))
    print(f"  player: x {min(xs):.0f}..{max(xs):.0f}  y {min(ys):.0f}..{max(ys):.0f}  path length ~{moved:.0f} units  stuck {sum(1 for r in raw if r.get('STUCK'))}/{len(raw)}")
hp = [r["health"] for r in ctrl if r.get("health") is not None]
if hp:
    print(f"  health: start {hp[0]} min {min(hp)} end {hp[-1]}")
bumps = [r for r in rows if r.get("kind") == "system_two_hint"]
if bumps:
    print(f"  System Two bumps: {len(bumps)} (median {sorted(b['latency_ms'] for b in bumps)[len(bumps) // 2]} ms): " + "; ".join(f"{b['bearing_deg']} deg/{b['ttl']} s" for b in bumps[-6:]))
levels = [r for r in rows if r.get("kind") == "level"]
episodes = sorted({r.get("episode") for r in ctrl if r.get("episode") is not None})
print(f"  levels finished: {len(levels)} " + ", ".join(f"level {r['finished']} after {r['controls']} decisions" for r in levels) + f"; episodes played: {len(episodes)}")
modes = Counter(str((r.get("raw") or {}).get("AHEAD_KIND")) for r in ctrl if (r.get("raw") or {}).get("AHEAD_KIND") is not None)
if modes:
    print("  at arm's length: " + ", ".join(f"{k} {v}" for k, v in modes.most_common()))
steer = Counter(r["answers"].get("steer") for r in ctrl if "steer" in r["answers"])
if steer:
    print("  steer:  " + ", ".join(f"{k} {v}" for k, v in steer.most_common()))
reviews = [r for r in rows if r.get("kind") == "after_action"]
rerr = [r for r in rows if r.get("kind") == "after_action_error"]
print(f"System Two: {len(reviews)} after-action reviews, {len(rerr)} errors" + (f"; {len(plans)} live plans (old mode)" if plans else ""))
for r in reviews:
    tok = " ".join(f"{m.split('-')[1]}:{v[0]}in/{v[1]}out" for m, v in (r.get("tokens") or {}).items())
    print(f"  [{r.get('outcome')}] -> graph v{r.get('graph_version')} {r.get('latency_ms')} ms ${r.get('cost_usd') or 0:.3f} {tok}")
    print(f"     {str(r.get('rationale'))[:220]}")
    for c in (r.get("changes") or [])[:8]:
        print(f"     - {c}")

for r in plans:
    tok = r.get("tokens") or {}
    tk = " ".join(f"{m.split('-')[1]}:{v[0]}in/{v[1]}out" for m, v in tok.items())
    print(f"  [{r.get('reason')}] {r.get('goal')} steer={r.get('steer_hint')} {r.get('latency_ms')} ms ${r.get('cost_usd') or 0:.3f} {tk}: {str(r.get('rationale'))[:90]}")
