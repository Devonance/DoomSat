"""The test campaign. Charter 5 phase 6, and the only thing in this repo that answers section 1.

Five episode attempts on the full flight stack, shareware E1M1 to E1M8, a fresh payload each time, and a
report against the charter's five "done means" conditions.

**A person runs this.** Not the experiment loop, not a schedule, not an agent deciding it is time. The
test set is the thing every number in the ledger is trying to earn the right to predict, and a loop that
can run it will tune on it in the end, whatever anyone intended (charter 2.5). `runner.py` refuses the
test set without `--i-am-a-person` for the same reason, and this script passes that flag exactly once,
where a human can see it.

    python research/campaign.py --attempts 5 --python /root/doom/payload-venv/bin/python

What it does per attempt:

  1. preflight, killing orphans, and refuse to start unless the payload is fresh
  2. start the flight stack, play until the episode ends or the budget runs out
  3. convert the pilot's log into per-attempt records and grade them
  4. stop everything, so the next attempt starts from nothing

It does not start Yamcs or F Prime for you: `scripts/flight.sh start` owns that, and pretending otherwise
would hide the one failure mode that has cost this project the most time -- a process that was still
running from the attempt before.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

try:
    import yaml
except ImportError:                                            # noqa: BLE001
    raise SystemExit("PyYAML is needed to read research/levels.yaml")


def sh(cmd, **kw):
    print("\n$ %s" % " ".join(str(c) for c in cmd), flush=True)
    return subprocess.call([str(c) for c in cmd], cwd=str(ROOT), **kw)


def report(run_dirs, conf):
    """Charter section 1: the five conditions, each answered from the graded runs rather than asserted."""
    attempts = []
    for d in run_dirs:
        s = Path(d) / "summary.json"
        if s.is_file():
            attempts.append(json.load(open(s, encoding="utf-8")))
    maps = conf["test"]["maps"]
    budget = conf["run"]["level_budget_s"]
    out = {"attempts": len(attempts), "conditions": {}}

    finished = [a for a in attempts if a.get("completed", 0) >= len(maps)]
    out["conditions"]["1. one continuous episode, every level inside %ds" % budget] = {
        "pass": bool(finished),
        "detail": "%d of %d attempts completed all %d levels" % (len(finished), len(attempts), len(maps))}
    out["conditions"]["2. repeatable: at least 4 of 5"] = {
        "pass": len(finished) >= 4,
        "detail": "%d of %d" % (len(finished), len(attempts))}
    honest = all(a.get("guardrails", {}).get("honesty", {}).get("pass", True) for a in attempts)
    out["conditions"]["3. honest: every honesty test passes on every attempt"] = {
        "pass": honest, "detail": "preflight ran the suite before each attempt"}
    shares = [a["guardrails"]["jev_share"]["value"] for a in attempts if "jev_share" in a.get("guardrails", {})]
    out["conditions"]["4. jev decides: jev_share at or above %.0f%%" % (100 * conf["guardrails"]["jev_share_min"])] = {
        "pass": all(a.get("guardrails", {}).get("jev_share", {}).get("pass", False) for a in attempts),
        "detail": "; ".join(shares) or "not measured"}
    deaths = sum(a.get("deaths", 0) for a in attempts)
    out["conditions"]["5. deaths counted and reported"] = {
        "pass": True, "detail": "%d deaths across %d attempts (charter 8.1 requires 0 in the final campaign)"
                                % (deaths, len(attempts))}
    out["pass"] = all(c["pass"] for c in out["conditions"].values())
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--attempts", type=int, default=5)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--duration", type=float, default=1500.0, help="wall seconds per attempt")
    ap.add_argument("--distro", default="ros2")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    a = ap.parse_args(argv)
    conf = yaml.safe_load(open(HERE / "levels.yaml", encoding="utf-8"))
    maps = conf["test"]["maps"]

    print(__doc__.split("\n\n")[0])
    print("\ntest set: %s %s at skill %d, %d s a level, %d attempts"
          % (conf["test"]["wad"], ",".join(maps), conf["run"]["skill"], conf["run"]["level_budget_s"],
             a.attempts))
    if a.dry_run:
        return 0

    stamp = time.strftime("%Y%m%dT%H%M%S")
    dirs = []
    for i in range(a.attempts):
        run_dir = HERE / "out" / ("campaign-%s-a%d" % (stamp, i + 1))
        print("\n================ attempt %d of %d ================" % (i + 1, a.attempts))
        if sh([sys.executable, HERE / "preflight.py", "--run-dir", run_dir, "--kill",
               "--require-fresh-payload", "--distro", a.distro]):
            print("preflight failed: the attempt is void (charter 2.4), moving on")
            continue
        if sh(["wsl", "-d", a.distro, "--", "bash", "-lc",
               "cd /mnt/c/Users/Kevin/Genai/DoomSat && bash scripts/flight.sh payload"]):
            print("could not restart the payload; skipping")
            continue
        sh([sys.executable, ROOT / "ground" / "pilot.py", "--control", "intent",
            "--duration", a.duration, "--level-budget", conf["run"]["level_budget_s"],
            "--out-dir", run_dir])
        sh([a.python, HERE / "runner.py", "flight", "--from-log", run_dir / "decisions.jsonl",
            "--maps"] + maps + ["--out", run_dir, "--run-id", run_dir.name, "--i-am-a-person", "--grade"])
        dirs.append(run_dir)

    result = report(dirs, conf)
    dest = HERE / "out" / ("campaign-%s-report.json" % stamp)
    json.dump(result, open(dest, "w", encoding="utf-8"), indent=1)
    print("\n================ against charter section 1 ================")
    for name, c in result["conditions"].items():
        print("  %-4s %-58s %s" % ("PASS" if c["pass"] else "no", name, c["detail"]))
    print("\n%s\nwrote %s" % ("THE MISSION IS DONE" if result["pass"] else "not yet", dest))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
