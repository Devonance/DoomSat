"""Frozen definitions of the numbers DoomSat compares runs on.

The after-action report, tools/replay.py and tools/run_report.py all import these, so a before-and-after
comparison is always apples to apples. Two readings of the same log differed by 12 percent on the spin
count purely because one skipped windows that crossed an episode boundary and the other did not; the
definitions below settle that. They are the ones the baselines in docs/audit-2026-09-22.md were measured
with, so changing one invalidates every baseline: change it deliberately and re-measure the lot.
"""
import math
from collections import Counter

SPIN_WINDOW_TICKS = 8         # consecutive control decisions in one window
SPIN_ROTATION_DEG = 300.0     # total absolute heading change over the window, at or above this
SPIN_TRAVEL_UNITS = 64.0      # straight-line distance between the window's ends, strictly under this
CELL_UNITS = 128              # the grid the walk's coverage is counted on
UNSURE_BAND = (0.35, 0.65)    # an open band on a probability: "cannot tell"
SPIN_KEY = "spin_windows_%dtick_%ddeg_under%du" % (SPIN_WINDOW_TICKS, SPIN_ROTATION_DEG, SPIN_TRAVEL_UNITS)


def samples(rows):
    """(episode, x, y, heading) per control row that carries a position, in order."""
    out = []
    for r in rows:
        raw = r.get("raw") or {}
        if raw.get("POS_X") is None or raw.get("ANGLE") is None:
            continue
        out.append((r.get("episode"), float(raw["POS_X"]), float(raw["POS_Y"]), float(raw["ANGLE"])))
    return out


def spin_windows(samples_):
    """Windows of SPIN_WINDOW_TICKS consecutive ticks that turned a lot and went nowhere.

    Windows crossing an episode boundary are skipped: the position jumps when the player respawns, which
    would otherwise read as a huge instant traversal or a huge instant turn.
    """
    n = 0
    for i in range(max(0, len(samples_) - SPIN_WINDOW_TICKS)):
        w = samples_[i:i + SPIN_WINDOW_TICKS + 1]
        if any(s[0] != w[0][0] for s in w):
            continue
        rot = sum(abs((w[j + 1][3] - w[j][3] + 180) % 360 - 180) for j in range(len(w) - 1))
        if rot >= SPIN_ROTATION_DEG and math.hypot(w[-1][1] - w[0][1], w[-1][2] - w[0][2]) < SPIN_TRAVEL_UNITS:
            n += 1
    return n


def cells(samples_):
    """How often each CELL_UNITS cell of the level was stood in."""
    return Counter((round(x / CELL_UNITS) * CELL_UNITS, round(y / CELL_UNITS) * CELL_UNITS)
                   for _, x, y, _ in samples_)


def unsure(p):
    """True when a probability falls in the open band where the answer means "cannot tell"."""
    return p is not None and UNSURE_BAND[0] < p < UNSURE_BAND[1]


def path_units(samples_):
    """Manhattan distance walked, skipping episode boundaries."""
    total = 0.0
    for a, b in zip(samples_, samples_[1:]):
        if a[0] == b[0]:
            total += abs(a[1] - b[1]) + abs(a[2] - b[2])
    return total
