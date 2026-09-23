"""Queued: the throttle stops at nothing, not at zero.

The throttle limits speed so that the sideways drift while the heading comes round fits the room the
camera reports. That is the right question while the player has room. Once the shoulders are inside its
own radius the player is already scraping, and the premise is gone: in this engine a scrape costs nothing
and a stop costs the tic.

Measured on the dev bench: the executor commanded no movement at all on about 22% of ticks outside
recovery and looking, which is the throttle at zero.
"""
import io
import sys

EDITS = [
    ("payload/executor.py",
     '''        room = max(0.0, room - PLAYER_RADIUS)
        drift_per_delta = (UNITS_PER_S_PER_DELTA / TICRATE) * tics * math.sin(math.radians(rel)) / 2.0
        if drift_per_delta <= 1e-6:
            return RUN_DELTA
        return max(0.0, min(RUN_DELTA, room / drift_per_delta))''',
     '''        room -= PLAYER_RADIUS
        if room <= 0.0:
            # Already touching. There is no drift left to prevent, and this engine charges nothing for a
            # scrape and a whole tic for a stop. Measured: the throttle at zero was about 22% of all
            # ticks outside recovery and looking.
            return RUN_DELTA
        drift_per_delta = (UNITS_PER_S_PER_DELTA / TICRATE) * tics * math.sin(math.radians(rel)) / 2.0
        if drift_per_delta <= 1e-6:
            return RUN_DELTA
        return min(RUN_DELTA, room / drift_per_delta)'''),
]


def main():
    bad = 0
    for path, old, new in EDITS:
        text = io.open(path, encoding="utf-8").read()
        if new in text:
            print("  %s: already applied" % path)
            continue
        if old not in text:
            print("  MISSING %s: %r" % (path, old.splitlines()[0][:70]))
            bad += 1
            continue
        io.open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))
        print("  %s: patched" % path)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
