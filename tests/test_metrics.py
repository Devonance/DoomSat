"""One definition per number, so a before-and-after comparison is apples to apples.

Two readings of the same 22 September log disagreed by 12 percent on the spin count purely because one
skipped windows that crossed an episode boundary and the other did not. These tests pin the definition.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ground"))

import metrics                       # noqa: E402


def spin(episode, n=9, x=0.0):
    """One tick per 50 degrees of turn on the spot: a window of these is a spin."""
    return [{"episode": episode, "raw": {"POS_X": x, "POS_Y": 0.0, "ANGLE": (i * 50) % 360}} for i in range(n)]


class SpinWindows(unittest.TestCase):
    def test_turning_on_the_spot_counts(self):
        self.assertGreater(metrics.spin_windows(metrics.samples(spin(1, 12))), 0)

    def test_walking_straight_does_not(self):
        rows = [{"episode": 1, "raw": {"POS_X": i * 40.0, "POS_Y": 0.0, "ANGLE": 0.0}} for i in range(12)]
        self.assertEqual(metrics.spin_windows(metrics.samples(rows)), 0)

    def test_a_window_crossing_an_episode_boundary_is_skipped(self):
        # A respawn moves the player across the level between two ticks; counting that window would read
        # either as a huge instant traversal or as a huge instant turn, depending on which way it lands.
        rows = spin(1, 5) + spin(2, 5, x=4000.0)
        joined = metrics.spin_windows(metrics.samples(rows))
        self.assertEqual(joined, 0)
        self.assertGreater(metrics.spin_windows(metrics.samples(spin(1, 10))), 0)

    def test_the_key_names_the_definition(self):
        self.assertEqual(metrics.SPIN_KEY, "spin_windows_8tick_300deg_under64u")


class UnsureBand(unittest.TestCase):
    def test_the_band_is_open(self):
        lo, hi = metrics.UNSURE_BAND
        self.assertFalse(metrics.unsure(lo))
        self.assertFalse(metrics.unsure(hi))
        self.assertTrue(metrics.unsure((lo + hi) / 2))
        self.assertFalse(metrics.unsure(None))


class Coverage(unittest.TestCase):
    def test_cells_are_counted_on_the_frozen_grid(self):
        rows = [{"episode": 1, "raw": {"POS_X": x, "POS_Y": 0.0, "ANGLE": 0.0}} for x in (0, 10, 300, 600)]
        self.assertEqual(len(metrics.cells(metrics.samples(rows))), 3)

    def test_path_units_skip_the_respawn_jump(self):
        rows = [{"episode": 1, "raw": {"POS_X": 0.0, "POS_Y": 0.0, "ANGLE": 0.0}},
                {"episode": 1, "raw": {"POS_X": 10.0, "POS_Y": 0.0, "ANGLE": 0.0}},
                {"episode": 2, "raw": {"POS_X": 9000.0, "POS_Y": 0.0, "ANGLE": 0.0}}]
        self.assertEqual(metrics.path_units(metrics.samples(rows)), 10.0)


if __name__ == "__main__":
    unittest.main()
