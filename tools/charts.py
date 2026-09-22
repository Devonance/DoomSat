"""Charts for the report from the decision logs of the day (out/decisions*.jsonl).

    python tools/charts.py            # writes docs/images/chart_*.png
"""
import glob
import json
import os
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "images")
os.makedirs(OUT, exist_ok=True)
LOGS = {"planner v1": "out/decisions_run1_no_steer.jsonl", "planner + steer": "out/decisions_run2_steer.jsonl",
        "local 1": "out/decisions_run6_local1.jsonl", "local 2": "out/decisions_run7_local2.jsonl",
        "local 3": "out/decisions_run8_4way.jsonl", "local 4": "out/decisions_run9_8way.jsonl",
        "local 5": "out/decisions_run10.jsonl", "local 6": "out/decisions_run11.jsonl", "local 7": "out/decisions.jsonl"}


def load(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


runs = {k: load(v) for k, v in LOGS.items()}
runs = {k: v for k, v in runs.items() if v}

# 1. cells explored against jev decisions, per cycle (first 300 decisions)
plt.figure(figsize=(9, 4.5))
for name, rows in runs.items():
    ctrl = [r for r in rows if r.get("kind") == "control" and r.get("raw")]
    ys = [r["raw"].get("EXPLORED_CELLS", 0) or 0 for r in ctrl[:300]]
    if ys:
        plt.plot(range(len(ys)), ys, label=name)
plt.xlabel("jev decisions (first 300 of the run)")
plt.ylabel("map cells stood in (32 units)")
plt.title("Exploration per cycle: how far the character got")
plt.legend(fontsize=8, ncol=3)
plt.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(OUT, "chart_exploration.png"), dpi=130)

# 2. jev latency and command issue latency (all runs)
lat = [r["latency_ms"] for rows in runs.values() for r in rows if r.get("kind") == "control" and r.get("latency_ms")]
cmd = [r["cmd_ms"] for rows in runs.values() for r in rows if r.get("kind") == "control" and r.get("cmd_ms")]
plt.figure(figsize=(9, 3.6))
plt.subplot(1, 2, 1)
plt.hist([x for x in lat if x < 1500], bins=40, color="#2E9E63")
plt.xlabel("jev call, ms (state + 6-8 heads)")
plt.ylabel("decisions")
plt.title(f"jev latency, median {sorted(lat)[len(lat) // 2]} ms, n={len(lat)}")
plt.subplot(1, 2, 2)
plt.hist([x for x in cmd if x < 300], bins=40, color="#3A7BC0")
plt.xlabel("CONTROL command issue through Yamcs, ms")
plt.title(f"command issue, median {sorted(cmd)[len(cmd) // 2]} ms")
plt.tight_layout()
plt.savefig(os.path.join(OUT, "chart_latency.png"), dpi=130)

# 3. what jev answered in the last cycle (way head) and the after-action / bump activity
last = runs.get("local 7") or list(runs.values())[-1]
ctrl = [r for r in last if r.get("kind") == "control"]
ways = Counter(r["answers"].get("way") for r in ctrl if r["answers"].get("way"))
plt.figure(figsize=(9, 3.6))
plt.subplot(1, 2, 1)
names = [k for k, _ in ways.most_common()]
plt.bar(names, [ways[k] for k in names], color="#7A55CC")
plt.xticks(rotation=35, ha="right", fontsize=8)
plt.title("jev's direction answers, last cycle")
plt.subplot(1, 2, 2)
kinds = Counter(r.get("kind") for rows in runs.values() for r in rows)
labels = ["control", "system_two_hint", "after_action", "level"]
plt.bar(labels, [kinds.get(k, 0) for k in labels], color=["#2E9E63", "#7A55CC", "#7A55CC", "#3A7BC0"])
plt.yscale("log")
plt.title("who acted how often (all runs today)")
plt.tight_layout()
plt.savefig(os.path.join(OUT, "chart_answers.png"), dpi=130)
print("charts written; decisions:", len(lat), "cycles:", list(runs))
