"""The after-action report must describe the heads the episode actually asked.

The old report summarised `steer`, `move` and `strafe`, heads that had not existed for several graph
versions, so the two heads that drove navigation appeared nowhere and `longest_hold_streak` was 0 by
construction. Sonnet then wrote a review around that constant. `coverage_gaps` must stay empty.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ground"))

import after_action                  # noqa: E402
import metrics                       # noqa: E402
import decision_graph as dg          # noqa: E402
import graph_config as gc            # noqa: E402

CFG = gc.validate(gc.DEFAULT)


def row(i, answers, mode="EXPLORE", pick="ahead", x=0.0, y=0.0, angle=0.0, select=None):
    return {"t": 1000.0 + i * 0.5, "kind": "control", "episode": 1, "graph_version": 1, "mode": mode,
            "goal": "EXPLORE", "pick": pick, "select": select or {"gap": 0.4, "held": False, "fallback": None},
            "answers": {k: dg.answer_label(v) for k, v in answers.items()},
            "confidence": {k: round(dg.answer_confidence(v), 2) for k, v in answers.items()},
            "control": dict(dg.STOP), "health": 100, "kills": 0, "usage": {"input_tokens": 1200},
            "latency_ms": 400, "here": {"at_arms_length": "nothing near", "stuck": "no"}, "seen": {},
            "raw": {"POS_X": x, "POS_Y": y, "ANGLE": angle, "AHEAD_KIND": "NOTHING", "ENEMY_COUNT": 0,
                    "EXIT_DIST": 0, "STUCK": False, "LEVEL": 1, "KEYS": 0, "EXPLORED_CELLS": i}}


def episode(n=40, spin=False):
    rows = []
    for i in range(n):
        answers = {"s_%s" % d: {"type": "score", "score": 1.0 + (d == "ahead"), "confidence": 0.8}
                   for d in ("ahead", "left", "right")}
        if i % 10 == 0:
            answers["goal"] = {"type": "choice", "choice": "Explore", "confidence": 0.9}
        if i % 17 == 0:
            answers["danger"] = {"type": "score", "score": 0.4, "confidence": 0.7}
        rows.append(row(i, answers, angle=(i * 50) % 360 if spin else 0.0,
                        x=0.0 if spin else i * 40.0))
    return rows


class ReportCoversTheLiveHeads(unittest.TestCase):
    def setUp(self):
        self.report = after_action.summarise([], episode(), "test", CFG)

    def test_no_coverage_gaps(self):
        self.assertEqual(self.report["coverage_gaps"], [])

    def test_the_navigation_head_is_in_the_report(self):
        self.assertIn("sector", self.report["heads"])
        self.assertGreater(self.report["heads"]["sector"]["asked"], 0)
        self.assertIn("score", self.report["heads"]["sector"])
        self.assertIn("s_left", self.report["heads"]["sector"]["asked_per_direction"])

    def test_the_other_heads_are_in_the_report(self):
        self.assertIn("goal", self.report["heads"])
        self.assertIn("danger", self.report["heads"])
        self.assertEqual(self.report["heads"]["goal"]["answers"], {"Explore": 4})

    def test_no_head_statistic_is_constant_by_construction(self):
        sel = self.report["selection"]
        self.assertGreater(sel["longest_same_direction_run"], 0)
        self.assertIsNotNone(sel["median_top_two_gap"])

    def test_a_head_that_was_never_asked_is_simply_absent(self):
        self.assertNotIn("way", self.report["heads"])
        self.assertNotIn("advance", self.report["heads"])

    def test_the_pinned_model_is_recorded(self):
        self.assertEqual(self.report["model"], CFG["model"])


class ReportMeasuresTheSpin(unittest.TestCase):
    """The spin the audit measured is now a number in every report, not something to rediscover."""

    def test_a_spinning_episode_is_counted(self):
        spun = after_action.summarise([], episode(spin=True), "test", CFG)
        walked = after_action.summarise([], episode(spin=False), "test", CFG)
        self.assertGreater(spun["walk"][metrics.SPIN_KEY], 0)
        self.assertEqual(walked["walk"][metrics.SPIN_KEY], 0)
        self.assertGreater(walked["walk"]["distinct_128u_bins"], spun["walk"]["distinct_128u_bins"])


class ReviewFeedsRejectionsBack(unittest.TestCase):
    """A revision code refuses goes back to System Two with the reason, and it gets one more try."""

    class Stub:
        def __init__(self, replies):
            self.replies, self.prompts = list(replies), []

        def structured(self, system, prompt, schema):
            self.prompts.append(prompt)
            return self.replies.pop(0)

    def test_a_rejected_edit_is_retried_with_the_error(self):
        bad = {"config": {"select": {"sector_margin": 9.0}}, "rationale": "raise the margin"}
        good = {"config": {"select": {"sector_margin": 0.65}}, "rationale": "raise the margin"}
        stub = self.Stub([bad, good])
        cfg, rationale, issues, meta = after_action.review(stub, {"outcome": "test"}, CFG)
        self.assertEqual(meta["attempts"], 2)
        self.assertAlmostEqual(cfg["select"]["sector_margin"], 0.65)
        self.assertIn("REJECTED BY CODE", stub.prompts[1])
        self.assertIn("sector_margin", stub.prompts[1])

    def test_the_limits_are_in_the_first_prompt(self):
        stub = self.Stub([{"config": {}, "rationale": "no change"}])
        after_action.review(stub, {"outcome": "test"}, CFG)
        self.assertIn(str(gc.TEXT_LIMIT), stub.prompts[0])

    def test_two_bad_replies_raise(self):
        bad = {"config": {"standing_order": "x" * 999}, "rationale": "long"}
        with self.assertRaises(gc.GraphError):
            after_action.review(self.Stub([bad, bad]), {"outcome": "test"}, CFG)


if __name__ == "__main__":
    unittest.main()
