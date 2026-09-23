"""Changes staged while a measurement run is in flight, applied the moment it ends.

The bench imports the payload once per runner process, and `ladder.sh` starts one process per rung. Edit
a payload file while a ladder is running and the rungs stop being comparable -- half the ladder on one
version of the code, half on another, and nothing in the output saying so. This file is where a change
waits.

    python research/_queued_patch.py      # applies, then says what it did
"""
import io
import sys

EDITS = [
    # ---------------------------------------------------------------- 1. why the player was not moving
    ("payload/executor.py",
     """                print("[executor] rubbing at (%.0f,%.0f) rel=%.0f ahead=%s@%.0f fwd=%.0f fl=%.0f fr=%.0f "
                      "plan_left=%d" % (x, y, rel, obs["ahead_kind"], obs["ahead_dist"], obs["clear_fwd"],
                                        obs["clear_fl"], obs["clear_fr"],
                                        (len(self.world.plan.cells) - self.world.plan.i)
                                        if self.world.plan else -1), flush=True)""",
     """                print("[executor] rubbing at (%.0f,%.0f) %s/%s rel=%.0f speed=%.0f ahead=%s@%.0f "
                      "fwd=%.0f fl=%.0f fr=%.0f enemies=%d plan_left=%d"
                      % (x, y, it.mode, it.stance, rel, speed, obs["ahead_kind"], obs["ahead_dist"],
                         obs["clear_fwd"], obs["clear_fl"], obs["clear_fr"], len(obs["enemies"]),
                         (len(self.world.plan.cells) - self.world.plan.i)
                         if self.world.plan else -1), flush=True)"""),

    # ---------------------------------------------------------------- 2. never stand still under fire
    ("payload/executor.py",
     """            if it.stance == "advance_strafing" and obs["enemies"]:
                cmd["strafe"] = STRAFE_DELTA * self._circle_side(now)
                # Do not close on something that is already shooting at us. Charging at a run was worth
                # four times the deaths on the first executor baseline.
                if obs["enemies"][0][2] < FIGHT_KEEP_UNITS:
                    cmd["move"] = min(cmd["move"], 0.0)""",
     """            if it.stance == "advance_strafing" and obs["enemies"]:
                cmd["strafe"] = STRAFE_DELTA * self._circle_side(now)
                # Do not close on something that is already shooting at us -- charging at a run was worth
                # four times the deaths on the first executor baseline -- but do not stop either. Clamping
                # the throttle to zero left the player circling one monster at a fixed radius for as long
                # as the intent held: measured, `advance_strafing` with anything inside FIGHT_KEEP_UNITS
                # commanded no forward movement on 60 tics out of 60, indefinitely. That is neither
                # fighting nor going anywhere, and the brief's words for it are "never stand still under
                # fire". Backing off is what a player does: it opens the range, it keeps the shotgun
                # pointed, and it ends.
                if obs["enemies"][0][2] < FIGHT_KEEP_UNITS:
                    cmd["move"] = -RUN_DELTA if obs["clear_back"] > 64 else 0.0"""),

    # ---------------------------------------------------------------- 3. a goal on a wall is still a goal
    ("payload/world_model.py",
     """        import time as _t
        t0 = _t.perf_counter()
        costs = self.path_costs(x, y, set(goals), now)
        _cost("path_costs", t0)""",
     """        import time as _t
        t0 = _t.perf_counter()
        # An exit line is a one-sided wall, a door line is the door itself, and an item can sit against a
        # pillar -- so the cell a goal names is regularly a cell no player can stand in, and the flood
        # below would report "no route" to a place the player could walk right up to. `plan_to` already
        # snapped its goal to the nearest cell that works; this is the same courtesy, done once for the
        # whole list. Without it the exit was silently dropped from the candidate list of every attempt
        # that had one.
        goals = self._reachable_goals(goals, meta, door_cells, now)
        costs = self.path_costs(x, y, set(goals), now)
        _cost("path_costs", t0)"""),

    # ---------------------------------------------------------------- 4. a path you cannot walk is not a path
    ("payload/executor.py",
     """            plan = self.world.plan
            if plan is not None and not plan.blocked:
                pt = plan.advance(x, y)
                if pt is not None:
                    want = math.degrees(math.atan2(pt[1] - y, pt[0] - x))""",
     """            plan = self.world.plan
            if plan is not None and not plan.blocked:
                pt = plan.advance(x, y)
                if pt is not None and rub and not plan.straight_line_clear(x, y, pt[0], pt[1]):
                    # Pressed against something, with a waypoint on the far side of it. That is not a
                    # corner to be rounded, it is a path the player has come off -- the rub correction
                    # leans forty degrees off the heading, which moves it, and a waypoint twenty units
                    # away through a wall keeps it leaning. Throwing the path away is what makes it stop:
                    # the next decision plans from where the player actually is.
                    plan.blocked = True
                    self.stats["replanned_off_path"] = self.stats.get("replanned_off_path", 0) + 1
                    pt = None
                if pt is not None:
                    want = math.degrees(math.atan2(pt[1] - y, pt[0] - x))"""),

    ("payload/world_model.py",
     """    def outwardness(self, c, x, y):""",
     '''    def _reachable_goals(self, goals, meta, door_cells, now):
        """Move each goal to the nearest cell a player could stand in, keeping what it stands for.

        Measured on the oracle rung, which is handed the exit's exact position: the payload reported the
        exit in telemetry on all 334 decisions of an attempt, and the exit appeared in the candidate list
        on none of them. An exit line is a one-sided wall, so its cell is not walkable, so the flood never
        reached it and it was dropped without a word. The same is true of a door line and of an item
        against a pillar -- and it is true on an honest run too, which means the pilot could never target
        an exit it saw.
        """
        walk = self.walkable(now)
        out = []
        for cell in goals:
            if cell in walk:
                out.append(cell)
                continue
            near = [c for c in walk if abs(c[0] - cell[0]) <= 2 and abs(c[1] - cell[1]) <= 2]
            if not near:
                out.append(cell)                 # genuinely unreachable; the flood will say so
                continue
            moved = min(near, key=lambda c: (c[0] - cell[0]) ** 2 + (c[1] - cell[1]) ** 2)
            kind = meta[cell][0]
            # A cell can be two things at once -- the floor beside an exit line is also a frontier. The
            # exit and a key win, because one ends the level and the other opens what nothing else will.
            if moved not in meta or kind in (KIND_EXIT, KIND_KEY):
                meta[moved] = meta[cell]
                self._features.setdefault(moved, self._features.get(cell, {}))
            if cell in door_cells:
                door_cells.add(moved)
            out.append(moved)
        return out

    def outwardness(self, c, x, y):'''),
    # ------------------------------------------- 6. the throttle's room is sideways room, not forward room
    ("payload/executor.py",
     """        # The narrowest of the three forward bands, because which way the body drifts depends on the
        # strafe as well as the turn and the honest answer is "whichever is tightest".
        room = min(obs["clear_fl"], obs["clear_fr"], obs["clear_fwd"])""",
     """        # The narrower SHOULDER, and not the forward band. The question this answers is how far the
        # body will drift sideways while the heading comes round, so the room that matters is sideways
        # room. Including `clear_fwd` made it a handbrake: a wall seven units ahead is a wall the player
        # slides along for free in this engine, and folding it in here took the throttle to zero for any
        # heading error over a degree -- so the player stopped dead exactly where it most needed to be
        # moving. What to do about something straight ahead is the avoidance guard's job, below.
        room = min(obs["clear_fl"], obs["clear_fr"])"""),

    # ------------------------------------------- 7. lean toward the side that is open
    ("payload/executor.py",
     """            if rub:
                # Override the guard rather than obey it: the guard is what put us here.
                side = 1.0 if int((now - self._rub_since) / RUB_FLIP_S) % 2 == 0 else -1.0""",
     """            if rub:
                # Override the guard rather than obey it: the guard is what put us here.
                #
                # Toward the side the camera says is open, and alternate only when it cannot tell. The
                # side used to be chosen by a clock alone, which meant that half the time the player
                # leaned into the wall it was already pressed against: the ladder log is full of
                # `fl=7 fr=428` with the lean going left. `_freer_side` is a measurement and was sitting
                # right there, used by the avoidance guard two lines up.
                side = self._freer_side(obs)
                if abs(obs["clear_fl"] - obs["clear_fr"]) < PLAYER_RADIUS:
                    side = 1.0 if int((now - self._rub_since) / RUB_FLIP_S) % 2 == 0 else -1.0"""),
]


def main():
    done, missing = [], []
    for path, old, new in EDITS:
        text = io.open(path, encoding="utf-8").read()
        if new in text:
            done.append("%s: already applied" % path)
            continue
        if old not in text:
            missing.append("%s: anchor not found -- %r" % (path, old.strip().splitlines()[0][:60]))
            continue
        io.open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))
        done.append("%s: patched" % path)
    for line in done:
        print(" ", line)
    for line in missing:
        print("  MISSING", line)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
