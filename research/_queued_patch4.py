"""Queued: a path follower that re-acquires the path instead of steering at a waypoint behind a wall.

The rub log, once it was made to say what the executor was commanding, named the failure in one line and
it was the commonest one in the run:

    APPROACH/advance rel=0 speed=8 ahead=wall@21 fwd=21

Heading dead on the aim point. A wall twenty-one units in front. Throttle cut to eight out of fifty by the
avoidance guard, which is what the guard is for. The player creeps into the wall at 15% of a run and stays
there.

The aim point is waypoint `i+1`, and `advance()` only moves the cursor on when the player gets within
twenty-four units of waypoint `i` or when `i+1` is nearer than `i`. A player that has drifted sideways --
which is what the rub correction does to it, by design, forty degrees off the heading -- satisfies neither,
so the cursor stays pointing at a waypoint on the other side of a wall for as long as it takes.

Blanking the plan was tried and measured worse: the payload only replans when the next INTENT arrives,
about seventeen tics, so the executor spent most of an attempt with a target and no path. This does not
need a replan. The path is still a good path; the player has come off it. Find the nearest waypoint it can
walk a straight line to and carry on from there, which is what a person does when they step off a trail.
"""
import io
import sys

EDITS = [
    ("payload/world_model.py",
     '''        if self.i >= len(self.cells):
            return None''',
     '''        if self.i >= len(self.cells):
            return None
        self._reacquire(x, y)'''),

    ("payload/world_model.py",
     '''    def _aim_index(self, x, y):''',
     '''    def _reacquire(self, x, y, span=LOOKAHEAD_CELLS * 2):
        """If the cursor points somewhere the player cannot walk to, move it to the nearest one it can.

        A path the player has come off is still a good path. `advance` moves the cursor on when the player
        reaches a waypoint or passes it, and a player pushed sideways does neither -- so it goes on
        steering at a waypoint behind a wall, with the avoidance guard holding it at 15% of a run against
        the wall, for as long as the rub correction keeps pushing it sideways. That was the commonest
        single line in a dev run's rub log.

        Forward first, because going on is the point and going back is what the recovery is for.
        """
        here = cell_centre(self.cells[self.i])
        if self.straight_line_clear(x, y, here[0], here[1]):
            return
        for j in list(range(self.i + 1, min(len(self.cells), self.i + span + 1))) + \\
                list(range(self.i - 1, max(-1, self.i - span - 1), -1)):
            cx, cy = cell_centre(self.cells[j])
            if self.straight_line_clear(x, y, cx, cy):
                self.reacquired += 1
                self.i = j
                return

    def _aim_index(self, x, y):'''),

    ("payload/world_model.py",
     '''        self.i = 0                          # how far along it the player is
        self.blocked = False''',
     '''        self.i = 0                          # how far along it the player is
        self.blocked = False
        self.reacquired = 0                 # times the cursor was moved to a waypoint reachable from here'''),
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
