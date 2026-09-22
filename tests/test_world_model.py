"""The onboard world model: what is walkable, where the frontiers are, and the route there. Charter 3.2.

Built on a stand-in for the payload's Explorer rather than a real game, so the suite stays offline. The
stand-in is deliberately thin -- a set of swept cells and a class per cell -- because that is all the
world model is entitled to read.
"""
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "payload"))

import mapclasses as mc          # noqa: E402
import world_model as wm         # noqa: E402

GRID = wm.GRID


class FakeExplorer:
    """Everything WorldModel is allowed to know: swept floor, a class per place, keys held."""

    def __init__(self, free=(), walls=(), keys=()):
        self.free = set(free)
        self.walls = dict(walls)          # cell -> class
        self.keys = set(keys)
        import numpy as np
        self.n = 512
        self.ox, self.oy = -1024.0, 1024.0
        self.raster = np.zeros((self.n, self.n), np.uint8)
        self.exit_at = None

    def cell(self, x, y):
        return int(math.floor(x / GRID)), int(math.floor(y / GRID))

    def wpx(self, x, y):
        return int((x - self.ox) / mc.WPX), int((self.oy - y) / mc.WPX)

    def klass(self, ix, iy, now, r=1):
        x = self.ox + ix * mc.WPX
        y = self.oy - iy * mc.WPX
        return self.walls.get(self.cell(x, y), mc.NONE)

    def nearest_exit(self, x, y, now):
        if self.exit_at is None:
            return None
        ex, ey = self.exit_at
        return ex, ey, math.hypot(ex - x, ey - y)


def room(x0, y0, x1, y1):
    return {(cx, cy) for cx in range(x0, x1) for cy in range(y0, y1)}


class TestWhatIsWalkable(unittest.TestCase):
    def test_only_floor_that_has_been_swept_counts(self):
        ex = FakeExplorer(free=room(0, 0, 3, 3))
        w = wm.WorldModel(ex)
        self.assertTrue(w.passable(1, 1, 0.0))
        self.assertFalse(w.passable(9, 9, 0.0), "ground nothing has seen is not walkable")

    def test_a_wall_a_barrier_or_a_locked_door_blocks(self):
        for cls in (mc.WALL, mc.BARRIER, mc.LOCKED):
            ex = FakeExplorer(free=room(0, 0, 3, 3), walls={(1, 1): cls})
            self.assertFalse(wm.WorldModel(ex).passable(1, 1, 0.0), "class %d should block" % cls)

    def test_a_locked_door_opens_once_its_key_is_held(self):
        ex = FakeExplorer(free=room(0, 0, 3, 3), walls={(1, 1): mc.LOCK_RED})
        self.assertFalse(wm.WorldModel(ex).passable(1, 1, 0.0))
        ex.keys.add("red")
        self.assertTrue(wm.WorldModel(ex).passable(1, 1, 0.0))

    def test_an_ordinary_door_does_not_block(self):
        ex = FakeExplorer(free=room(0, 0, 3, 3), walls={(1, 1): mc.DOOR})
        self.assertTrue(wm.WorldModel(ex).passable(1, 1, 0.0), "a door opens; it is not a wall")


class TestFrontiers(unittest.TestCase):
    def test_the_edge_of_swept_floor_is_a_frontier(self):
        w = wm.WorldModel(FakeExplorer(free=room(0, 0, 5, 5)))
        fr = w.frontiers(0.0, 0.0, 0.0, force=True)
        self.assertTrue(fr)
        self.assertTrue(all(size >= wm.FRONTIER_MIN_CELLS for _c, size in fr))

    def test_floor_with_no_edge_has_no_frontier(self):
        """Every cell swept and every neighbour swept: nothing left to discover."""
        big = room(-6, -6, 7, 7)
        w = wm.WorldModel(FakeExplorer(free=big))
        inner = wm.WorldModel(FakeExplorer(free=big))
        fr = inner.frontiers(0.0, 0.0, 0.0, force=True)
        # the outer ring is still an edge, so there is a frontier; the interior contributes none
        cells = {c for c, _s in fr}
        self.assertTrue(all(abs(c[0]) >= 5 or abs(c[1]) >= 5 for c in cells), cells)
        self.assertTrue(w.frontiers(0.0, 0.0, 0.0, force=True))

    def test_separate_openings_cluster_separately(self):
        free = room(0, 0, 3, 3) | room(20, 20, 23, 23)
        fr = wm.WorldModel(FakeExplorer(free=free)).frontiers(0.0, 0.0, 0.0, force=True)
        cells = {c for c, _s in fr}
        self.assertGreaterEqual(len(cells), 2)
        self.assertTrue(any(c[0] < 10 for c in cells) and any(c[0] > 10 for c in cells))

    def test_a_single_stray_cell_is_noise_not_a_frontier(self):
        groups = wm.WorldModel._cluster({(0, 0)})
        self.assertEqual(groups, [], "one cell is a sensing artefact, not a way on")


class TestThePlanner(unittest.TestCase):
    def test_it_finds_a_straight_route(self):
        w = wm.WorldModel(FakeExplorer(free=room(0, 0, 10, 3)))
        path = w.plan_to(16.0, 16.0, (8, 1), 0.0)
        self.assertIsNotNone(path)
        self.assertEqual(path[0], (0, 0))
        self.assertEqual(path[-1], (8, 1))

    def test_it_goes_around_a_wall_rather_than_through_it(self):
        free = room(0, 0, 9, 5)
        walls = {(4, cy): mc.WALL for cy in range(0, 4)}      # a wall with a gap at the top
        w = wm.WorldModel(FakeExplorer(free=free, walls=walls))
        path = w.plan_to(16.0, 16.0, (8, 1), 0.0)
        self.assertIsNotNone(path, "there is a way round")
        self.assertTrue(any(c[1] == 4 for c in path), "the route has to use the gap: %s" % path)

    def test_no_route_means_none_and_not_a_guess(self):
        free = room(0, 0, 3, 3) | room(9, 0, 12, 3)
        w = wm.WorldModel(FakeExplorer(free=free))
        self.assertIsNone(w.plan_to(16.0, 16.0, (10, 1), 0.0))
        self.assertEqual(w.planner_failures, 1)

    def test_it_will_not_squeeze_between_two_diagonal_walls(self):
        free = room(0, 0, 3, 3)
        walls = {(1, 0): mc.WALL, (0, 1): mc.WALL}
        w = wm.WorldModel(FakeExplorer(free=free, walls=walls))
        path = w.plan_to(16.0, 16.0, (1, 1), 0.0)
        self.assertIsNone(path, "a player cannot pass through the corner where two walls meet")

    def test_path_costs_answers_many_goals_in_one_flood(self):
        w = wm.WorldModel(FakeExplorer(free=room(0, 0, 10, 3)))
        costs = w.path_costs(16.0, 16.0, {(2, 0), (5, 0), (9, 0)}, 0.0)
        self.assertEqual(len(costs), 3)
        self.assertLess(costs[(2, 0)], costs[(5, 0)])
        self.assertLess(costs[(5, 0)], costs[(9, 0)])
        self.assertEqual(w.planner_calls, 0, "a flood is not an A* call per goal")


class TestCommitment(unittest.TestCase):
    """The first planner in this project was removed for flipping between equal-cost routes on every
    replan. That is a commitment problem, and this is the commitment."""

    def setUp(self):
        self.w = wm.WorldModel(FakeExplorer(free=room(0, 0, 12, 6)))

    def cand(self, cell):
        return wm.Candidate(wm.KIND_FRONTIER, (cell[0] + 0.5) * GRID, (cell[1] + 0.5) * GRID, 100.0, cell=cell)

    def test_a_route_to_the_same_target_is_not_replanned_every_tick(self):
        a = self.cand((9, 1))
        first = self.w.route_to(16.0, 16.0, a, 100.0)
        again = self.w.route_to(16.0, 16.0, a, 100.2)
        self.assertIs(first, again, "the same target inside the replan window keeps the same path")

    def test_a_new_target_replans(self):
        self.w.route_to(16.0, 16.0, self.cand((9, 1)), 100.0)
        second = self.w.route_to(16.0, 16.0, self.cand((2, 4)), 100.1)
        self.assertEqual(second.target.cell, (2, 4))

    def test_an_equally_good_path_does_not_displace_the_one_being_walked(self):
        plan = wm.Plan([(0, 0)] * 10, None, 0.0)
        same = wm.Plan([(0, 0)] * 10, None, 1.0)
        shorter = wm.Plan([(0, 0)] * 7, None, 1.0)
        self.assertFalse(same.better_than(plan), "equal cost is not a reason to change route")
        self.assertTrue(shorter.better_than(plan))

    def test_a_blocked_plan_is_always_replaced(self):
        plan = wm.Plan([(0, 0)] * 3, None, 0.0)
        plan.blocked = True
        self.assertTrue(wm.Plan([(0, 0)] * 99, None, 1.0).better_than(plan))

    def test_walking_the_path_advances_the_waypoint(self):
        plan = wm.Plan([(0, 0), (1, 0), (2, 0), (3, 0)], None, 0.0)
        plan.advance(16.0, 16.0)
        self.assertEqual(plan.i, 1)
        plan.advance(3 * GRID + 16.0, 16.0)
        self.assertGreaterEqual(plan.i, 3)


class TestTheCandidateList(unittest.TestCase):
    def setUp(self):
        self.ex = FakeExplorer(free=room(0, 0, 12, 6))
        self.w = wm.WorldModel(self.ex)

    def test_frontiers_become_candidates_with_a_path_distance(self):
        cands = self.w.candidates(16.0, 16.0, 0.0, 0.0)
        self.assertTrue(cands)
        self.assertTrue(all(c.path_units > 0 for c in cands))
        self.assertTrue(all(c.kind == wm.KIND_FRONTIER for c in cands))

    def test_an_exit_that_has_been_seen_always_makes_the_cut(self):
        self.ex.exit_at = (11 * GRID, 5 * GRID)
        cands = self.w.candidates(16.0, 16.0, 0.0, 0.0, limit=2)
        self.assertIn(wm.KIND_EXIT, [c.kind for c in cands], "the exit must never be pruned")

    def test_a_locked_door_without_its_key_is_not_somewhere_to_go(self):
        self.w.doors[(5, 2)] = {"x": 5.5 * GRID, "y": 2.5 * GRID, "colour": "red", "tries": 0,
                                "opened": False, "last_try": 0.0}
        self.w.see_doors = lambda *a, **k: None          # the raster scan needs numpy and a real raster
        kinds = [c.kind for c in self.w.candidates(16.0, 16.0, 0.0, 0.0)]
        self.assertNotIn(wm.KIND_DOOR, kinds)
        kinds = [c.kind for c in self.w.candidates(16.0, 16.0, 0.0, 0.0, keys_held=("red",))]
        self.assertIn(wm.KIND_DOOR, kinds, "with the key in hand it is a place to go")

    def test_a_door_that_refused_to_open_stops_being_offered(self):
        self.w.see_doors = lambda *a, **k: None
        self.w.doors[(5, 2)] = {"x": 5.5 * GRID, "y": 2.5 * GRID, "colour": "", "tries": 9,
                                "opened": False, "last_try": 1000.0}
        kinds = [c.kind for c in self.w.candidates(16.0, 16.0, 0.0, 1000.0)]
        self.assertNotIn(wm.KIND_DOOR, kinds)

    def test_somewhere_with_no_route_to_it_is_not_offered(self):
        self.ex.free |= room(40, 40, 43, 43)             # a disconnected patch
        self.w.see_doors = lambda *a, **k: None
        for c in self.w.candidates(16.0, 16.0, 0.0, 0.0, limit=8):
            self.assertLess(c.x, 40 * GRID, "a candidate with no route is not a candidate")

    def test_the_list_is_pruned_to_what_the_ground_can_score(self):
        self.assertLessEqual(len(self.w.candidates(16.0, 16.0, 0.0, 0.0, limit=8)), 8)

    def test_objects_carry_when_they_were_first_seen(self):
        class Lab:
            object_name, object_position_x, object_position_y = "Stimpack", 100.0, 100.0
        w = wm.WorldModel(self.ex, enemies={"DoomImp"}, item_kind={"Stimpack": "health"})
        w.see_objects(0.0, 0.0, [Lab()], 42)
        rec = list(w.objects.values())[0]
        self.assertEqual(rec["first_seen_tic"], 42)
        self.assertEqual(rec["state"], "alive")
        w.see_objects(0.0, 0.0, [Lab()], 99)
        self.assertEqual(list(w.objects.values())[0]["first_seen_tic"], 42, "first seen does not move")

    def test_walking_over_a_pickup_marks_it_taken(self):
        class Lab:
            object_name, object_position_x, object_position_y = "Stimpack", 100.0, 100.0
        w = wm.WorldModel(self.ex, item_kind={"Stimpack": "health"})
        w.see_objects(0.0, 0.0, [Lab()], 1)
        w.see_objects(100.0, 100.0, [], 2)
        self.assertEqual(list(w.objects.values())[0]["state"], "taken")


class TestItMatchesThePayload(unittest.TestCase):
    def test_the_map_classes_are_the_payload_s_own(self):
        """A second copy of these numbers would show up as the pilot walking into a wall."""
        src = open(os.path.join(ROOT, "payload", "doom_payload.py"), encoding="utf-8").read()
        self.assertIn("from mapclasses import", src)
        self.assertNotIn("NONE, STEP, DOOR, LOCK_RED", src.split("from mapclasses import")[0],
                         "the payload still defines its own copy of the class constants")


if __name__ == "__main__":
    unittest.main()
