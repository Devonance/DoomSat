"""Queued while the dev bench runs: a recovery that goes back the way it came.

The present recovery turns at the full rate and pushes, which over its second and a half is 787 degrees
of spin, and it is 28% of an oracle attempt. Spinning is not how a person gets out of a corner. They back
out the way they came in, because that way is known to work.

The world model already holds the only thing needed for that: `stood`, every cell the player has occupied
this attempt. Walkable by demonstration rather than by inference, which is the strongest kind of evidence
the pilot has about anything. A recovery retreats to the nearest cell it stood in that is far enough back
to be out of whatever it is wedged in, and steers at that.

No new tunable: "far enough back" is the watchdog's own STILL_UNITS, the distance it already uses to
decide that the player has not been getting anywhere.
"""
import io
import sys

EDITS = [
    ("payload/world_model.py",
     '''    def times_tried(self, cell):''',
     '''    def way_back(self, x, y, at_least):
        """The nearest cell the player has stood in that is at least `at_least` units behind it.

        Ground it has stood on is ground it can stand on -- that is the one claim in this whole world
        model that rests on demonstration rather than inference, and it is exactly what a player wedged
        in a corner needs. Nearest, so the retreat is short; at least `at_least` away, so it is not the
        corner itself.
        """
        best, bd = None, None
        for c in self.stood:
            cx, cy = cell_centre(c)
            d = math.hypot(cx - x, cy - y)
            if d < at_least:
                continue
            if bd is None or d < bd:
                best, bd = (cx, cy), d
        return best

    def times_tried(self, cell):'''),

    ("payload/executor.py",
     '''    def _recover(self, obs):
        """Always command motion.

        The payload's stuck detector needs the player to push against something to learn it is there, so a
        recovery that stands still deadlocks it -- 553 decisions in one spot with STUCK false, in September.
        Back off, turn, and keep pushing.
        """
        self.world.clear_plan()
        back = obs["clear_back"] > 64
        return {"turn": TURN_PER_TIC * self.recover_dir,
                "move": -RUN_DELTA * 0.7 if back else RUN_DELTA * 0.5,
                "strafe": STRAFE_DELTA * self._freer_side(obs),
                "fire": 0, "use": 1 if obs["ahead_kind"] in ("door", "exit") else 0,
                "weapon": WEAPON_KEEP}''',
     '''    def _recover(self, obs):
        """Go back the way you came in, because that way is known to work.

        The old recovery turned at the full rate and pushed, which over a second and a half is 787 degrees
        of spin and leaves the heading to arithmetic. It was 28% of an oracle attempt and it is not how
        anyone gets out of a corner.

        `stood` is every cell the player has occupied this attempt -- walkable by demonstration, which is
        the strongest evidence in the world model. Steer at the nearest one that is a watchdog window
        behind, and run at it. If there is none yet, fall back to the old back-off-and-turn, which is all
        a player has in its first seconds on a level.

        Still always commands motion: the payload's stuck detector needs the player to push against
        something to learn it is there, and a recovery that stands still deadlocks it.
        """
        self.world.clear_plan()
        x, y, angle = obs["x"], obs["y"], obs["angle"]
        back_to = self.world.way_back(x, y, Watchdog.STILL_UNITS)
        if back_to is not None:
            want = math.degrees(math.atan2(back_to[1] - y, back_to[0] - x))
            rel = (want - angle + 180) % 360 - 180
            self.stats["recover_retreats"] = self.stats.get("recover_retreats", 0) + 1
            return {"turn": max(-TURN_PER_TIC, min(TURN_PER_TIC, rel)),
                    # Backwards while the heading comes round, forwards once it has: either way the
                    # player is moving toward ground it has already stood on.
                    "move": RUN_DELTA if abs(rel) < 90.0 else -RUN_DELTA * 0.7,
                    "strafe": STRAFE_DELTA * self._freer_side(obs),
                    "fire": 0, "use": 1 if obs["ahead_kind"] in ("door", "exit") else 0,
                    "weapon": WEAPON_KEEP}
        back = obs["clear_back"] > 64
        return {"turn": TURN_PER_TIC * self.recover_dir,
                "move": -RUN_DELTA * 0.7 if back else RUN_DELTA * 0.5,
                "strafe": STRAFE_DELTA * self._freer_side(obs),
                "fire": 0, "use": 1 if obs["ahead_kind"] in ("door", "exit") else 0,
                "weapon": WEAPON_KEEP}'''),
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
