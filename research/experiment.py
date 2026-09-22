"""One experiment, start to finish. Charter 5 phase 5 and section 6.3.

The autoresearch loop is a process, not a program, and this is the part of it that should not be done by
hand: preflight, run the dev set, grade it, and append the ledger row the keep rule decided. What it
refuses to do is as important as what it does.

    python research/experiment.py EXP-0001 --parent research/out/t2-baseline-code

It will not run without `research/exp/<id>/hypothesis.md` already written. That is charter 6.3 step 2,
and it is the one rule in the loop that cannot be automated away: a hypothesis written after the numbers
are in is not a hypothesis, it is a story about them. It will not touch the test set. It will not write
the ledger row itself -- `ledger.py` does that, from the keep rule, whatever anyone hoped for.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def run(cmd, **kw):
    print("\n$ %s" % " ".join(str(c) for c in cmd), flush=True)
    return subprocess.call([str(c) for c in cmd], cwd=str(ROOT), **kw)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exp_id", help="EXP-####; research/exp/<id>/hypothesis.md must already exist")
    ap.add_argument("--parent", required=True, help="the run directory this is measured against")
    ap.add_argument("--decider", default="jev", choices=["code", "jev"])
    ap.add_argument("--seeds", nargs="*", type=int, default=None)
    ap.add_argument("--area", default="graph")
    ap.add_argument("--author", default="claude-code")
    ap.add_argument("--change", required=True, help="one line: what actually changed")
    ap.add_argument("--python", default=sys.executable, help="the interpreter that has ViZDoom")
    ap.add_argument("--skip-preflight", action="store_true")
    a = ap.parse_args(argv)

    exp_dir = HERE / "exp" / a.exp_id
    hypothesis = exp_dir / "hypothesis.md"
    if not hypothesis.is_file():
        raise SystemExit(
            "%s does not exist.\n"
            "Charter 6.3 step 2: the hypothesis is written BEFORE the code, and it says what should move, "
            "in which direction, and roughly by how much. A hypothesis written after the numbers are in is "
            "not a hypothesis." % hypothesis)
    text = hypothesis.read_text(encoding="utf-8")
    first = next((ln.strip("# ").strip() for ln in text.splitlines() if ln.strip()), a.exp_id)

    run_dir = HERE / "out" / ("%s-%s" % (a.exp_id.lower(), time.strftime("%Y%m%dT%H%M%S")))
    if not a.skip_preflight:
        rc = run([sys.executable, HERE / "preflight.py", "--run-dir", run_dir, "--kill"])
        if rc:
            raise SystemExit("preflight failed; the run is void (charter 2.4)")

    cmd = [a.python, HERE / "runner.py", "bench", "--set", "dev", "--decider", a.decider,
           "--control", "intent", "--run-id", run_dir.name, "--out", run_dir, "--grade"]
    if a.seeds:
        cmd += ["--seeds"] + [str(s) for s in a.seeds]
    if run(cmd):
        raise SystemExit("the run failed; nothing is appended")

    rc = run([sys.executable, HERE / "ledger.py", "--exp", a.exp_id, "--parent", a.parent,
              "--new", run_dir, "--author", a.author, "--area", a.area,
              "--hypothesis", first, "--change", a.change])
    print("\nhypothesis: %s" % hypothesis)
    print("run:        %s" % run_dir)
    print("\nNow write %s/verdict.md with anything the row does not carry, and keep or git reset as the "
          "row says." % exp_dir)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
