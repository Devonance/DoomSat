"""A closed loop without Yamcs, the flight stack or the game: does the pilot actually get anywhere?

The audit's headline symptom was a player that turned 300 degrees and travelled under 64 units, 736 times
in one run. Every other test here checks one decision; this one runs the decision loop against a toy world
that answers the telemetry, moves the player the way the payload would, and then measures the walk with the
same frozen definitions the after-action report uses.

The answering pilot is the code-only scorer from tools/replay.py, so this test never touches the network.
That is the point: if the loop spins with a perfectly consistent answerer, the spin is the loop's fault.
"""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ground"))
sys.path.insert(0, str(ROOT / "tools"))

import decision_graph as dg          # noqa: E402
import graph_config as gc            # noqa: E402
import metrics                       # noqa: E402
from replay import CodePilot         # noqa: E402

CFG = gc.validate(gc.DEFAULT)
STEP = 24.0                          # units the player covers per decision when walking
TURN_RATE = 120.0                    # degrees a turn covers between decisions (the payload does 6 per tic)


class Corridor:
    """A corridor running east-west, 200 units wide, 1600 long, with walls all round."""

    def __init__(self, x=120.0, y=100.0, angle=90.0):
        self.x, self.y, self.angle = x, y, angle
        self.visits = {}
        self.pending = 0.0

    def inside(self, x, y):
        return 0 <= x <= 1600 and 0 <= y <= 200

    def clearance(self, rel_deg):
        """How far the way is open on that bearing, by walking a ray until it leaves the corridor."""
        a = math.radians(self.angle + rel_deg)
        dx, dy = math.cos(a), math.sin(a)
        d = 0.0
        while d < 900 and self.inside(self.x + dx * d, self.y + dy * d):
            d += 8.0
        return int(d)

    def novelty(self, rel_deg):
        """255 where nothing has been walked, falling as the cell 100 units that way is revisited."""
        a = math.radians(self.angle + rel_deg)
        cell = (round((self.x + math.cos(a) * 100) / 64), round((self.y + math.sin(a) * 100) / 64))
        n = self.visits.get(cell, 0)
        return 255 if n == 0 else max(0, 100 - 12 * n)

    def telemetry(self):
        t = {"ANGLE": self.angle % 360, "POS_X": self.x, "POS_Y": self.y, "HEALTH": 100, "ARMOR": 0,
             "SHELLS": 0, "BULLETS": 50, "WEAPON": "PISTOL", "OWN_SHOTGUN": False, "ENEMY_COUNT": 0,
             "ENEMY_BEARING": 0.0, "ENEMY_DIST": 0, "AHEAD_KIND": "NOTHING", "AHEAD_DIST": 0,
             "STUCK": False, "LEVEL": 1, "KEYS": 0, "EXIT_DIST": 0, "KEY_DIST": 0,
             "HEALTH_ITEM_DIST": 0, "AMMO_ITEM_DIST": 0, "ARMOR_ITEM_DIST": 0,
             "HINT_ACTIVE": False, "HINT_REL": 0}
        for d, (ck, nk, dk) in dg.DIR_KEYS.items():
            t[ck], t[nk], t[dk] = self.clearance(dg.SECTORS[d]), self.novelty(dg.SECTORS[d]), 0
        t["CLEAR_MAP_FWD"] = t["CLEAR_FWD"]
        return t

    def apply(self, cargs):
        """What the payload does with one CONTROL: turn toward the setpoint, then walk if there is room."""
        self.pending += cargs["turn"]
        step = max(-TURN_RATE, min(TURN_RATE, self.pending))
        self.angle = (self.angle + step) % 360
        self.pending -= step
        if cargs["move"]:
            a = math.radians(self.angle)
            nx = self.x + math.cos(a) * STEP * cargs["move"]
            ny = self.y + math.sin(a) * STEP * cargs["move"]
            if self.inside(nx, ny):
                self.x, self.y = nx, ny
        self.visits[(round(self.x / 64), round(self.y / 64))] = self.visits.get((round(self.x / 64), round(self.y / 64)), 0) + 1


def fly(ticks=120, cfg=CFG):
    """Run the loop and return the rows a real run would have logged."""
    world, mem, pilot = Corridor(), dg.NavMemory(cfg), CodePilot(cfg)
    pending, rows = 0.0, []
    for _ in range(ticks):
        t = world.telemetry()
        settle = float(cfg["thresholds"]["turn_settle_deg"])
        if abs(pending) > settle:                       # the pilot's rule: never decide mid-turn
            pending = world.pending
            if abs(world.pending) > settle:
                world.apply(dict(dg.STOP))
                continue
        mem.step()
        state = dg.build_state(t, "EXPLORE", cfg, mem)
        mode = dg.next_mode(state, t, mem, cfg)
        offered = dg.offered_sectors(state)
        questions = dg.questions_for(state, cfg, mode, offered=offered)
        answers = pilot.answer(dg.state_for(state, questions), questions)["answers"] if questions else {}
        pick = None
        if mode in dg.JUDGED_MODES:
            pick, _ = dg.pick_sector(answers, state, cfg, mem, float(t["ANGLE"]), "EXPLORE", offered,
                                     (t["POS_X"], t["POS_Y"]))
        cargs = dg.control_args(state, t, cfg, mem, mode, answers, pick)
        rows.append({"episode": 1, "pick": pick, "mode": mode,
                     "raw": {"POS_X": world.x, "POS_Y": world.y, "ANGLE": world.angle}})
        world.apply(cargs)
        pending = world.pending
    return rows, world


class TheLoopGetsSomewhere(unittest.TestCase):
    def setUp(self):
        self.rows, self.world = fly()

    def test_it_does_not_spin_on_the_spot(self):
        self.assertEqual(metrics.spin_windows(metrics.samples(self.rows)), 0)

    def test_it_travels_the_corridor(self):
        # Measured as the farthest it ever got from the start, not where it ended: the corridor has an end
        # wall, and walking to it and back is the right behaviour, not a failure.
        start = (120.0, 100.0)
        reached = max(math.dist((r["raw"]["POS_X"], r["raw"]["POS_Y"]), start) for r in self.rows)
        self.assertGreater(reached, 800, "the player never got out of its starting corner")
        self.assertGreater(metrics.path_units(metrics.samples(self.rows)), 1500)

    def test_it_covers_new_ground(self):
        self.assertGreaterEqual(len(metrics.cells(metrics.samples(self.rows))), 4)

    def test_it_holds_a_direction_rather_than_reversing_every_tick(self):
        picks = [r["pick"] for r in self.rows if r["pick"]]
        runs, longest = 1, 1
        for a, b in zip(picks, picks[1:]):
            runs = runs + 1 if a == b else 1
            longest = max(longest, runs)
        self.assertGreaterEqual(longest, CFG["select"]["commit_ticks"])

    def test_it_never_commands_a_turn_beyond_the_cap(self):
        self.assertLessEqual(abs(self.world.pending), CFG["thresholds"]["max_turn_deg"])


if __name__ == "__main__":
    unittest.main()
