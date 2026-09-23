"""Queued: the avoidance guard stops slowing the player down, and keeps sidestepping.

Measured on the dev bench, from the rub log once it was made to say what was being commanded. Of the
ticks where the player was asking to move and not moving:

    speed=8   52    the guard's 15% crawl
    speed=0   19    the throttle, with no room to turn in
    speed=50  12    genuinely pressed against something at a run

Eighty-five per cent of being stuck is the executor deciding to crawl. The guard's own comment already
argued its way to the answer and then did not take it: "The player has almost no momentum in this engine,
so the guard only has to stop it grinding into a wall, and turning away is the path planner's job rather
than the throttle's." Grinding into a wall in Doom costs nothing -- the player stops, and starts again the
moment it points somewhere else. Crawling at 15% of a run for four seconds costs four seconds.

So the guard keeps the half of itself that does something -- lean toward the shoulder the camera says is
open, which is how a player gets round a doorframe -- and loses the half that only makes the player late.
The throttle above it already limits speed by the room there is to turn in, which is the honest version of
the same worry.
"""
import io
import sys

EDITS = [
    ("payload/executor.py",
     '''            if obs["clear_fwd"] <= guard and obs["ahead_kind"] not in ("door", "exit"):
                # something solid ahead: keep the heading, step around it, and slow down first
                cmd["strafe"] = STRAFE_DELTA * self._freer_side(obs)
                speed *= 0.5 if obs["clear_fwd"] > AVOID_MIN_UNITS else 0.15''',
     '''            if obs["clear_fwd"] <= guard and obs["ahead_kind"] not in ("door", "exit"):
                # Something solid ahead: keep the heading and step around it. It used to slow down as
                # well, and that was most of being stuck -- 52 of 83 rub ticks in a dev run were the
                # guard's 15% crawl. This engine gives the player no momentum, so grinding into a wall
                # costs nothing and crawling at a seventh of a run costs the whole afternoon. How fast
                # it is safe to go while still turning is the throttle's question, and it is answered
                # above from the room the camera reports.
                cmd["strafe"] = STRAFE_DELTA * self._freer_side(obs)'''),
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
