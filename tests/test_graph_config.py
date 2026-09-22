"""The graph contract: a revision code refuses must raise, never be quietly trimmed.

Ten of the last eleven Sonnet reviews of the old graph re-diagnosed the same truncation because
`validate` cut every string to 700 characters and clamped `way_margin` to 0.5 without a word. These tests
hold the opposite behaviour in place.
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ground"))

import decision_graph as dg          # noqa: E402
import graph_config as gc            # noqa: E402


class ValidateRejects(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(gc.DEFAULT)

    def test_default_is_valid_and_lints_clean(self):
        out = gc.validate(self.cfg)
        self.assertEqual(dg.lint(out), [])
        self.assertEqual(out["questions"]["sector"]["criteria"], gc.DEFAULT["questions"]["sector"]["criteria"])

    def test_long_criterion_raises_instead_of_being_cut(self):
        self.cfg["questions"]["sector"]["criteria"][0] = "x" * (gc.TEXT_LIMIT + 1)
        with self.assertRaises(gc.GraphError) as e:
            gc.validate(self.cfg)
        self.assertIn(str(gc.TEXT_LIMIT), str(e.exception))

    def test_long_standing_order_raises(self):
        self.cfg["standing_order"] = "x" * (gc.ORDER_LIMIT + 1)
        with self.assertRaises(gc.GraphError):
            gc.validate(self.cfg)

    def test_out_of_range_number_raises_instead_of_being_clamped(self):
        self.cfg["select"]["sector_margin"] = 1.3          # the old code silently clamped this
        with self.assertRaises(gc.GraphError) as e:
            gc.validate(self.cfg)
        self.assertIn("sector_margin", str(e.exception))

    def test_in_range_number_is_kept_exactly(self):
        self.cfg["select"]["sector_margin"] = 0.65
        self.assertAlmostEqual(gc.validate(self.cfg)["select"]["sector_margin"], 0.65)

    def test_a_margin_that_could_outvote_a_whole_rubric_level_raises(self):
        self.cfg["select"]["sector_margin"] = 0.9
        self.cfg["select"]["commit_bonus"] = 0.3
        with self.assertRaises(gc.GraphError) as e:
            gc.validate(self.cfg)
        self.assertIn("rubric levels", str(e.exception))

    def test_unknown_head_raises(self):
        self.cfg["questions"]["way"] = {"type": "choice", "criteria": {}}
        with self.assertRaises(gc.GraphError):
            gc.validate(self.cfg)

    def test_unknown_goal_option_raises(self):
        self.cfg["questions"]["goal"]["criteria"]["Dance"] = {"what": "why not"}
        with self.assertRaises(gc.GraphError):
            gc.validate(self.cfg)

    def test_head_type_is_fixed(self):
        self.cfg["questions"]["sector"]["type"] = "choice"
        with self.assertRaises(gc.GraphError):
            gc.validate(self.cfg)

    def test_rubric_length_is_bounded(self):
        for levels in ([], ["one"], ["l%d" % i for i in range(gc.MAX_LEVELS + 1)]):
            self.cfg["questions"]["danger"]["criteria"] = levels
            with self.assertRaises(gc.GraphError):
                gc.validate(self.cfg)

    def test_criterion_naming_a_field_that_does_not_exist_raises(self):
        self.cfg["questions"]["sector"]["criteria"][0] = "prefer it when `sectors.{dir}.smells_nice` is yes"
        with self.assertRaises(gc.GraphError) as e:
            gc.validate(self.cfg)
        self.assertIn("smells_nice", str(e.exception))

    def test_cross_field_rules(self):
        bad = copy.deepcopy(gc.DEFAULT)
        bad["thresholds"]["tight_units"] = bad["thresholds"]["blocked_units"]
        with self.assertRaises(gc.GraphError):
            gc.validate(bad)
        bad = copy.deepcopy(gc.DEFAULT)
        bad["select"]["danger_retreat"] = 0.5
        bad["select"]["danger_sidestep"] = 2.0
        with self.assertRaises(gc.GraphError):
            gc.validate(bad)


class SchemaTellsSystemTwoTheLimits(unittest.TestCase):
    """The old review schema never mentioned a limit, so the reviewer could not have known one existed."""

    def setUp(self):
        self.schema = gc.review_schema()["properties"]["config"]["properties"]

    def test_text_limits_are_in_the_schema(self):
        self.assertEqual(self.schema["standing_order"]["maxLength"], gc.ORDER_LIMIT)
        rubric = self.schema["questions"]["properties"]["sector"]["properties"]["criteria"]
        self.assertEqual(rubric["items"]["maxLength"], gc.TEXT_LIMIT)
        self.assertEqual(rubric["minItems"], gc.MIN_LEVELS)
        self.assertEqual(rubric["maxItems"], gc.MAX_LEVELS)

    def test_every_numeric_range_is_in_the_schema(self):
        for section, ranges in (("thresholds", gc.THRESHOLD_RANGES), ("select", gc.SELECT_RANGES)):
            props = self.schema[section]["properties"]
            self.assertEqual(set(props), set(ranges))
            for k, (lo, hi) in ranges.items():
                self.assertEqual((props[k]["minimum"], props[k]["maximum"]), (lo, hi), k)

    def test_limits_note_names_the_bounds(self):
        note = gc.limits_note()
        self.assertIn(str(gc.TEXT_LIMIT), note)
        self.assertIn("sector_margin", note)


if __name__ == "__main__":
    unittest.main()
