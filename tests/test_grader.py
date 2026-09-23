"""The ruler itself: the walkability model, the distance field and the score.

Built on WADs this file writes, not on a real IWAD, so the suite stays offline and every case is one the
test chose. The two cases that mattered in practice are both here: a doorway narrower than the old grid
(which reported three of the eight shareware levels as having no route to their own exit) and a closed
door sector (which reported three more).
"""
import math
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("DOOMSAT_ROLE", None)          # this file IS the grader's test; it is not a pilot
sys.path.insert(0, os.path.join(ROOT, "research"))

from grader import wad                 # noqa: E402
from grader import score as gscore     # noqa: E402
import frozen_metrics as fm            # noqa: E402


def build_wad(path, name="E1M1", verts=(), lines=(), sides=(), sectors=(), things=()):
    """A PWAD with one map. `lines` are (v1, v2, flags, special, tag, right, left)."""
    def lump(fmt, rows):
        return b"".join(struct.pack(fmt, *r) for r in rows)
    data = {
        "THINGS": lump("<hhhhh", things),
        "LINEDEFS": lump("<hhHhhhh", lines),
        "SIDEDEFS": b"".join(struct.pack("<hh8s8s8sh", 0, 0, b"-", b"-", b"-", s) for s in sides),
        "VERTEXES": lump("<hh", verts),
        "SEGS": b"", "SSECTORS": b"", "NODES": b"",
        "SECTORS": b"".join(struct.pack("<hh8s8shhh", f, c, b"FLOOR", b"CEIL", 160, sp, 0)
                            for f, c, sp in sectors),
        "REJECT": b"", "BLOCKMAP": b"",
    }
    order = [(name, b"")] + [(k, data[k]) for k in
                             ("THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SEGS", "SSECTORS",
                              "NODES", "SECTORS", "REJECT", "BLOCKMAP")]
    body, entries, off = b"", [], 12
    for lname, blob in order:
        entries.append((off + len(body), len(blob), lname))
        body += blob
    header = struct.pack("<4sii", b"PWAD", len(order), 12 + len(body))
    with open(path, "wb") as f:
        f.write(header)
        f.write(body)
        for p, size, lname in entries:
            f.write(struct.pack("<ii8s", p, size, lname.encode()[:8].ljust(8, b"\0")))
    return path


def one_room(path, width=512, height=256, exit_special=11):
    """A rectangle with the exit on the east wall and the player at the west end."""
    verts = [(0, 0), (width, 0), (width, height), (0, height)]
    lines = [(0, 1, 1, 0, 0, 0, -1), (1, 2, 1, exit_special, 0, 0, -1),
             (2, 3, 1, 0, 0, 0, -1), (3, 0, 1, 0, 0, 0, -1)]
    return build_wad(path, verts=verts, lines=lines, sides=[0], sectors=[(0, 128, 0)],
                     things=[(64, height // 2, 0, 1, 7)])


class TestTheWadReader(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = one_room(os.path.join(self.dir, "t.wad"))

    def test_it_finds_the_map_and_not_a_lump_that_follows_it(self):
        self.assertEqual(wad.maps(self.path), ["E1M1"])

    def test_it_reads_the_player_start(self):
        self.assertEqual(wad.Level(self.path, "E1M1").start(), (64, 128))

    def test_a_one_sided_line_blocks(self):
        level = wad.Level(self.path, "E1M1")
        self.assertTrue(all(level.blocks(l) for l in level.lines))

    def test_the_exit_line_is_found(self):
        self.assertEqual(len(wad.Level(self.path, "E1M1").exit_lines()), 1)

    def test_a_secret_exit_is_not_a_normal_exit(self):
        p = one_room(os.path.join(self.dir, "secret.wad"), exit_special=51)
        self.assertEqual(wad.Level(p, "E1M1").exit_lines(), [])
        self.assertEqual(len(wad.Level(p, "E1M1").exit_lines(include_secret=True)), 1)

    def test_a_sector_that_ends_the_level_counts_as_an_exit(self):
        """E1M8's exit is sector special 11, not a linedef. A grader that missed it scored every attempt
        at that map as zero progress."""
        verts = [(0, 0), (512, 0), (512, 256), (0, 256)]
        lines = [(0, 1, 1, 0, 0, 0, -1), (1, 2, 1, 0, 0, 0, -1), (2, 3, 1, 0, 0, 0, -1), (3, 0, 1, 0, 0, 0, -1)]
        p = build_wad(os.path.join(self.dir, "e8.wad"), verts=verts, lines=lines, sides=[0],
                      sectors=[(0, 128, 11)], things=[(64, 128, 0, 1, 7)])
        self.assertEqual(len(wad.Level(p, "E1M1").exit_lines()), 4)


class TestTheDistanceField(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_the_start_has_a_finite_distance_to_the_exit(self):
        field = wad.DistanceField(wad.Level(one_room(os.path.join(self.dir, "a.wad")), "E1M1"))
        d = field.at(64, 128)
        self.assertIsNotNone(d)
        self.assertTrue(350 < d < 520, "expected roughly the room's length, got %s" % d)

    def test_it_gets_smaller_as_the_player_walks_toward_the_exit(self):
        field = wad.DistanceField(wad.Level(one_room(os.path.join(self.dir, "b.wad")), "E1M1"))
        walk = [field.at(x, 128) for x in (64, 160, 260, 360, 440)]
        self.assertEqual(walk, sorted(walk, reverse=True), walk)

    def test_a_narrow_doorway_is_still_walkable(self):
        """A 64-unit gap. Blocking whole 32-unit cells sealed this, which is what made three shareware
        levels read as having no route to their own exit."""
        verts = [(0, 0), (512, 0), (512, 256), (0, 256),     # outer room
                 (256, 0), (256, 96), (256, 160), (256, 256)]  # a wall across the middle with a 64-unit gap
        lines = [(0, 1, 1, 0, 0, 0, -1), (1, 2, 1, 11, 0, 0, -1), (2, 3, 1, 0, 0, 0, -1), (3, 0, 1, 0, 0, 0, -1),
                 (4, 5, 1, 0, 0, 0, -1), (6, 7, 1, 0, 0, 0, -1)]
        p = build_wad(os.path.join(self.dir, "gap.wad"), verts=verts, lines=lines, sides=[0],
                      sectors=[(0, 128, 0)], things=[(64, 128, 0, 1, 7)])
        field = wad.DistanceField(wad.Level(p, "E1M1"))
        self.assertIsNotNone(field.at(64, 128), "the 64-unit doorway was sealed")

    def test_a_closed_door_sector_does_not_wall_the_level_in_half(self):
        """Only the line you press carries the door special; the line on the far side of the same sector is
        a plain two-sided line into a sector whose ceiling is on its floor."""
        big = [(0, 0), (512, 0), (512, 256), (0, 256)]
        door = [(256, 96), (272, 96), (272, 160), (256, 160)]
        verts = big + door
        outer = [(0, 1, 1, 0, 0, 0, -1), (1, 2, 1, 11, 0, 0, -1), (2, 3, 1, 0, 0, 0, -1), (3, 0, 1, 0, 0, 0, -1)]
        # sector 1 is the shut door (floor 0, ceiling 0). The west face carries the door special, the east
        # face is plain. Walls above and below close the gap so the only way through is the door.
        wall = [(4, 5, 1, 0, 0, 0, -1), (7, 6, 1, 0, 0, 0, -1)]
        doorlines = [(4, 7, 0x0004, 1, 0, 0, 1),        # pressable side
                     (5, 6, 0x0004, 0, 0, 0, 1)]        # the far side, plain
        block = [(256, 0), (256, 96), (256, 160), (256, 256), (272, 0), (272, 96), (272, 160), (272, 256)]
        verts = big + door + block
        wall = [(8, 9, 1, 0, 0, 0, -1), (10, 11, 1, 0, 0, 0, -1),
                (12, 13, 1, 0, 0, 0, -1), (14, 15, 1, 0, 0, 0, -1)]
        p = build_wad(os.path.join(self.dir, "door.wad"), verts=verts, lines=outer + wall + doorlines,
                      sides=[0, 1], sectors=[(0, 128, 0), (0, 0, 0)], things=[(64, 128, 0, 1, 7)])
        field = wad.DistanceField(wad.Level(p, "E1M1"))
        self.assertIsNotNone(field.at(64, 128), "a shut door walled the level in half")

    def test_an_unreachable_exit_is_reported_and_not_guessed(self):
        """Two sealed rooms. The grader must say it cannot measure progress rather than invent a number."""
        verts = [(0, 0), (256, 0), (256, 256), (0, 256), (512, 0), (768, 0), (768, 256), (512, 256)]
        lines = [(0, 1, 1, 0, 0, 0, -1), (1, 2, 1, 0, 0, 0, -1), (2, 3, 1, 0, 0, 0, -1), (3, 0, 1, 0, 0, 0, -1),
                 (4, 5, 1, 0, 0, 0, -1), (5, 6, 1, 11, 0, 0, -1), (6, 7, 1, 0, 0, 0, -1), (7, 4, 1, 0, 0, 0, -1)]
        p = build_wad(os.path.join(self.dir, "sealed.wad"), verts=verts, lines=lines, sides=[0],
                      sectors=[(0, 128, 0)], things=[(64, 128, 0, 1, 7)])
        field = wad.DistanceField(wad.Level(p, "E1M1"))
        self.assertIsNone(field.at(64, 128))


class TestTheScore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.wad = one_room(os.path.join(self.dir, "s.wad"))

    def attempt(self, **kw):
        base = {"wad_path": self.wad, "map": "E1M1", "seed": 1, "tier": "bench", "budget_s": 180.0,
                "start_xy": [64, 128], "end_xy": [64, 128], "end_reason": "timeout",
                "game_seconds": 180.0, "deaths": 0, "decider": "code", "decisions": []}
        base.update(kw)
        return base

    def test_finishing_fast_scores_near_two(self):
        g = gscore.grade(self.attempt(end_reason="exit", game_seconds=18.0, end_xy=[500, 128]))
        self.assertTrue(g["completed"])
        self.assertAlmostEqual(g["score"], 1 + (180 - 18) / 180, places=3)

    def test_finishing_at_the_bell_scores_one(self):
        g = gscore.grade(self.attempt(end_reason="exit", game_seconds=180.0, end_xy=[500, 128]))
        self.assertAlmostEqual(g["score"], 1.0, places=3)

    def test_not_finishing_scores_partial_credit_for_how_far_it_got(self):
        near = gscore.grade(self.attempt(end_xy=[440, 128]))
        far = gscore.grade(self.attempt(end_xy=[64, 128]))
        self.assertGreater(near["score"], far["score"])
        self.assertLess(near["score"], 0.9, "an unfinished level can never outscore a finished one")

    def test_the_score_is_the_closest_approach_and_going_back_is_reported_separately(self):
        """Track t3. "Did it find the way out" and "what did it do afterwards" are two questions."""
        rows = [{"kind": "control", "t": i, "raw": {"POS_X": x, "POS_Y": 128, "ANGLE": 0.0}}
                for i, x in enumerate((64, 200, 440, 200, 64))]
        g = gscore.grade(self.attempt(decisions=rows, end_xy=[64, 128]))
        self.assertGreater(g["progress_best"], g["progress"])
        self.assertAlmostEqual(g["score"], 0.9 * g["progress_best"], places=4)
        self.assertAlmostEqual(g["progress_given_back"], g["progress_best"] - g["progress"], places=4)

    def test_walking_away_no_longer_erases_having_got_there(self):
        went = [{"kind": "control", "t": i, "raw": {"POS_X": x, "POS_Y": 128, "ANGLE": 0.0}}
                for i, x in enumerate((64, 440, 64))]
        never = [{"kind": "control", "t": i, "raw": {"POS_X": 64, "POS_Y": 128, "ANGLE": 0.0}}
                 for i in range(3)]
        a = gscore.grade(self.attempt(decisions=went, end_xy=[64, 128]))
        b = gscore.grade(self.attempt(decisions=never, end_xy=[64, 128]))
        self.assertGreater(a["score"], b["score"],
                           "under t2 these scored the same, which is why every exploration experiment "
                           "was being graded on what happened after the closest approach")

    def test_a_map_with_no_route_says_so_instead_of_scoring_zero_quietly(self):
        verts = [(0, 0), (256, 0), (256, 256), (0, 256), (512, 0), (768, 0), (768, 256), (512, 256)]
        lines = [(0, 1, 1, 0, 0, 0, -1), (1, 2, 1, 0, 0, 0, -1), (2, 3, 1, 0, 0, 0, -1), (3, 0, 1, 0, 0, 0, -1),
                 (4, 5, 1, 0, 0, 0, -1), (5, 6, 1, 11, 0, 0, -1), (6, 7, 1, 0, 0, 0, -1), (7, 4, 1, 0, 0, 0, -1)]
        p = build_wad(os.path.join(self.dir, "nr.wad"), verts=verts, lines=lines, sides=[0],
                      sectors=[(0, 128, 0)], things=[(64, 128, 0, 1, 7)])
        g = gscore.grade(self.attempt(wad_path=p))
        self.assertFalse(g["exit_reachable_from_start"])
        self.assertIn("progress is meaningless", g["warning"])

    def test_the_charter_formula(self):
        self.assertAlmostEqual(fm.attempt_score(True, 90.0, 1.0, 180.0), 1.5)
        self.assertAlmostEqual(fm.attempt_score(False, None, 0.5, 180.0), 0.45)
        self.assertAlmostEqual(fm.attempt_score(True, 200.0, 0.9, 180.0), 0.81, places=6)  # over budget is not completed
        self.assertEqual(fm.progress(1000.0, 1000.0), 0.0)
        self.assertEqual(fm.progress(1000.0, 0.0), 1.0)
        self.assertEqual(fm.progress(1000.0, 2000.0), 0.0, "walking away cannot score below zero")


if __name__ == "__main__":
    unittest.main()
