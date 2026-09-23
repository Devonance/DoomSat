"""The sensor that decides what the pilot is allowed to know about the level's shape.

Two questions, and the second is the one that matters:

  can it tell a doorway from a ledge from a pillar   (it is why exact geometry replaces the colours)
  does anything leave it that the automap did not draw   (it is the knowledge boundary, charter 2.2)

No ViZDoom here: the sector table is a handful of plain objects with the fields the engine reports, which
is also a statement about the sensor -- it takes floats and booleans, and nothing about it needs a game.
"""
import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "payload"))

import mapclasses as mc                                        # noqa: E402
import seen_geometry as sg                                     # noqa: E402


class Line:
    def __init__(self, x1, y1, x2, y2, blocking=False):
        self.x1, self.y1, self.x2, self.y2, self.is_blocking = x1, y1, x2, y2, blocking


class Sector:
    """As ViZDoom reports it -- floor_height NEGATED, which is measured and not a guess."""

    def __init__(self, floor, ceiling, lines):
        self.floor_height, self.ceiling_height, self.lines = -floor, ceiling, lines


class FakeExplorer:
    def __init__(self):
        self.n = 512
        self.ox, self.oy = -1024.0, 1024.0
        self.raster = np.zeros((self.n, self.n), np.uint8)
        self.drawn = np.zeros((self.n, self.n), bool)
        self.free = set()
        self.geom = None

    def wpx(self, x, y):
        return int((x - self.ox) / mc.WPX), int((self.oy - y) / mc.WPX)

    def cell(self, x, y):
        return int(math.floor(x / mc.GRID)), int(math.floor(y / mc.GRID))

    def draw_line(self, x1, y1, x2, y2):
        """Pretend the automap drew this, the way `Explorer.stamp` would."""
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) / 2.0))
        for i in range(n + 1):
            t = i / n
            ix, iy = self.wpx(x1 + t * (x2 - x1), y1 + t * (y2 - y1))
            self.drawn[iy, ix] = True


def room(floor=0.0, ceiling=128.0, shared=None, blocking=False):
    """A sector whose only interesting line is the one it shares with its neighbour."""
    line = shared if shared is not None else Line(0, 0, 64, 0, blocking)
    return Sector(floor, ceiling, [line])


class TestWhatALineIs(unittest.TestCase):
    def kind(self, a, b, shared):
        return sg.SeenGeometry._kind([(a, shared), (b, shared)])

    def test_a_one_sided_line_is_a_wall(self):
        ln = Line(0, 0, 64, 0)
        self.assertEqual(sg.SeenGeometry._kind([(room(shared=ln), ln)]), mc.WALL)

    def test_anything_the_engine_flags_impassable_is_a_wall(self):
        ln = Line(0, 0, 64, 0, blocking=True)
        self.assertEqual(self.kind(room(shared=ln), room(shared=ln), ln), mc.WALL)

    def test_a_flat_sector_at_the_neighbours_floor_is_a_door(self):
        ln = Line(0, 0, 64, 0)
        self.assertEqual(self.kind(room(0, 128, ln), Sector(0, 0, [ln]), ln), mc.DOOR,
                         "a ceiling that has come down to the floor is a door")

    def test_a_flat_sector_at_the_neighbours_ceiling_is_a_pillar_and_a_wall(self):
        """How Doom builds a column in the middle of a room. Its lines look exactly like a door's."""
        ln = Line(0, 0, 64, 0)
        self.assertEqual(self.kind(room(0, 128, ln), Sector(128, 128, [ln]), ln), mc.WALL)

    def test_a_climbable_rise_is_a_step_and_a_ledge_is_a_wall(self):
        ln = Line(0, 0, 64, 0)
        self.assertEqual(self.kind(room(0, 128, ln), room(24, 152, ln), ln), mc.STEP)
        self.assertEqual(self.kind(room(0, 128, ln), room(25, 153, ln), ln), mc.WALL,
                         "the engine lets a player climb 24 units and no more")

    def test_an_opening_too_short_to_fit_through_is_a_wall(self):
        ln = Line(0, 0, 64, 0)
        self.assertEqual(self.kind(room(0, 128, ln), room(0, 40, ln), ln), mc.WALL)

    def test_a_plain_threshold_is_not_drawn_at_all(self):
        ln = Line(0, 0, 64, 0)
        self.assertIsNone(self.kind(room(0, 128, ln), room(0, 128, ln), ln))


class TestTheKnowledgeBoundary(unittest.TestCase):
    def setUp(self):
        self.ex = FakeExplorer()
        self.wall = Line(0, 0, 128, 0, blocking=True)
        self.far = Line(0, 512, 128, 512, blocking=True)
        self.sectors = [Sector(0, 128, [self.wall, self.far])]

    def test_a_line_the_automap_never_drew_does_not_reach_the_pilot(self):
        g = sg.SeenGeometry(self.ex, reveal="seen")
        g.observe(self.sectors, 0.0, 0.0)
        self.assertEqual(g.admitted, 0, "nothing has been looked at yet")
        self.assertEqual(len(g.unadmitted()), 2)
        self.assertFalse(self.ex.raster.any(), "and nothing was written into the map")

    def test_drawing_it_lets_it_through_and_the_other_one_stays_out(self):
        g = sg.SeenGeometry(self.ex, reveal="seen")
        self.ex.draw_line(0, 0, 128, 0)
        g.observe(self.sectors, 0.0, 0.0)
        self.assertEqual(g.admitted, 1)
        self.assertEqual(len(g.unadmitted()), 1)
        self.assertTrue(self.ex.raster.any())
        self.assertEqual(g.admitted_unseen(), [], "what was admitted, the automap can account for")

    def test_half_a_line_is_not_enough(self):
        g = sg.SeenGeometry(self.ex, reveal="seen")
        self.ex.draw_line(0, 0, 40, 0)          # under a third of it
        g.observe(self.sectors, 0.0, 0.0)
        self.assertEqual(g.admitted, 0, "a line seen at one end is a line mostly not seen")

    def test_the_oracle_opens_the_gate_and_says_so(self):
        g = sg.SeenGeometry(self.ex, reveal="all")
        g.observe(self.sectors, 0.0, 0.0)
        self.assertEqual(g.admitted, 2)
        self.assertEqual(len(g.admitted_unseen()), 2,
                         "an oracle run must be visibly dishonest, which is what voids it")

    def test_only_lines_near_the_automap_window_are_reconsidered(self):
        """The window the payload stamps is +-640 by +-480 units; further off, nothing can have changed."""
        g = sg.SeenGeometry(self.ex, reveal="seen")
        self.ex.draw_line(0, 512, 128, 512)
        g.observe(self.sectors, 0.0, -4000.0)   # the player is nowhere near either line
        self.assertEqual(g.admitted, 0)
        g.observe(self.sectors, 0.0, 512.0)     # now it is standing at the far one
        self.assertEqual(g.admitted, 1)


class TestADoorThatOpens(unittest.TestCase):
    def test_it_stops_being_a_door_and_comes_out_of_the_map(self):
        ex = FakeExplorer()
        ln = Line(0, 0, 64, 0)
        shut = [Sector(0, 128, [ln]), Sector(0, 0, [ln])]
        g = sg.SeenGeometry(ex, reveal="all")
        g.observe(shut, 0.0, 0.0)
        self.assertEqual(len(g.doors()), 1)
        self.assertTrue((ex.raster == mc.DOOR).any())

        opened = [Sector(0, 128, [ln]), Sector(0, 128, [ln])]
        g.observe(opened, 0.0, 0.0)
        self.assertEqual(len(g.doors()), 0, "there is nothing left to open")
        self.assertFalse((ex.raster == mc.DOOR).any(),
                         "and it no longer blocks the view, which is the whole reason it mattered")


if __name__ == "__main__":
    unittest.main()
