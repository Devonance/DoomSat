"""Kill ViZDoom processes nothing is driving any more, by PID.

The bench starts a fresh game per attempt and closes it, and an interrupted run leaves its game behind.
Thirty-six of them were found alive on the night of 23 September, the oldest seven hours old, all of them
competing for the same cores as the run being measured. Every number taken while they were up was taken
on a busier machine than the one it claims to describe.

ViZDoom ignores SIGTERM -- that was measured too, by sending it to thirty-five of them and finding all
thirty-five still running. So this sends SIGKILL, and only ever to a pid it has just listed.

    python research/reap.py [--keep-younger-than SECONDS]
"""
import argparse
import os
import signal
import subprocess
import time


def games():
    out = subprocess.check_output(["ps", "-eo", "pid,etimes,args"], text=True)
    found = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) >= 3 and "/vizdoom/vizdoom " in parts[2]:
            found.append((int(parts[0]), int(parts[1])))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-younger-than", type=int, default=120,
                    help="seconds; a game this new probably belongs to a run that is going on")
    a = ap.parse_args()
    before = games()
    killed = []
    for pid, age in before:
        if age < a.keep_younger_than:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(pid)
        except ProcessLookupError:
            pass
    time.sleep(1.5)
    print("vizdoom games: %d before, %d killed by pid, %d left" % (len(before), len(killed), len(games())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
