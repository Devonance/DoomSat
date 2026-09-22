"""The keep rule, and the metrics the charter added.

The keep rule is the only thing standing between "the number went up" and "the change works", so it is
worth more tests than it has lines. Every case here is one that has actually bitten: a gain inside the
noise, a gain that came with a guardrail failure, a run compared against a run it shares no seeds with.
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))

import ledger                     # noqa: E402
import frozen_metrics as fm       # noqa: E402

CONF = {"keep_rule": {"min_gain_in_noise_se": 2.0, "completed_must_not_drop": True},
        "run": {"seeds_wide": [1, 2, 3, 4, 5, 6]}, "track": "t1"}


def att(map_name, seed, score, completed=False):
    return {"map": map_name, "seed": seed, "score": score, "completed": completed, "deaths": 0,
            "tier": "bench", "versions": {"commit": "abc1234"}, "metrics": {}}


def runs(parent_scores, child_scores, parent_completed=0, child_completed=0, guard=True):
    keys = [("E1M%d" % (i + 1), 1) for i in range(len(parent_scores))]
    p = [att(m, s, v) for (m, s), v in zip(keys, parent_scores)]
    c = [att(m, s, v) for (m, s), v in zip(keys, child_scores)]
    psum = {"suite_score": sum(parent_scores) / len(parent_scores), "completed": parent_completed,
            "guardrails_pass": True}
    csum = {"suite_score": sum(child_scores) / len(child_scores), "completed": child_completed,
            "guardrails_pass": guard}
    return p, c, psum, csum


class TestTheKeepRule(unittest.TestCase):
    def setUp(self):
        # no measured noise floor in the test environment: the rule falls back to the paired spread
        self._noise, ledger.NOISE = ledger.NOISE, ledger.Path(tempfile.mkdtemp()) / "absent.json"

    def tearDown(self):
        ledger.NOISE = self._noise

    def test_a_large_consistent_gain_is_kept(self):
        p, c, ps, cs = runs([1.0] * 6, [1.4] * 6)
        v = ledger.verdict(list(zip(p, c)), ps, cs, CONF)
        self.assertEqual(v["decision"], "keep")
        self.assertEqual(v["wins"], 6)

    def test_a_gain_inside_the_noise_is_inconclusive_and_not_a_win(self):
        p = [1.0, 1.2, 0.8, 1.4, 0.6, 1.1]
        c = [1.3, 0.9, 1.1, 1.0, 1.2, 0.9]     # mean barely moves, spread is large
        pr, cr, ps, cs = runs(p, c)
        v = ledger.verdict(list(zip(pr, cr)), ps, cs, CONF)
        self.assertIn(v["decision"], ("inconclusive", "discard"))
        self.assertNotEqual(v["decision"], "keep")

    def test_a_guardrail_failure_discards_whatever_the_score_did(self):
        p, c, ps, cs = runs([1.0] * 6, [1.9] * 6, guard=False)
        v = ledger.verdict(list(zip(p, c)), ps, cs, CONF)
        self.assertEqual(v["decision"], "discard")
        self.assertIn("guardrail", v["why"])

    def test_fewer_completed_levels_discards_even_with_a_higher_score(self):
        p, c, ps, cs = runs([1.0] * 6, [1.6] * 6, parent_completed=3, child_completed=2)
        v = ledger.verdict(list(zip(p, c)), ps, cs, CONF)
        self.assertEqual(v["decision"], "discard")
        self.assertIn("completed", v["why"])

    def test_a_loss_is_a_discard(self):
        p, c, ps, cs = runs([1.0] * 6, [0.7] * 6)
        self.assertEqual(ledger.verdict(list(zip(p, c)), ps, cs, CONF)["decision"], "discard")

    def test_one_pair_can_never_be_conclusive(self):
        """One run per side is one sample. The rule has to say so rather than crown a winner."""
        p, c, ps, cs = runs([1.0], [2.0])
        v = ledger.verdict(list(zip(p, c)), ps, cs, CONF)
        self.assertNotEqual(v["decision"], "keep")
        self.assertEqual(v["se"], float("inf"))

    def test_a_measured_noise_floor_is_preferred_to_the_paired_spread(self):
        d = tempfile.mkdtemp()
        ledger.NOISE = ledger.Path(d) / "noise_floor.json"
        ledger.NOISE.write_text(json.dumps({"per_level": {"E1M1": {"sd": 0.30}, "E1M2": {"sd": 0.30}}}),
                                encoding="utf-8")
        p, c, ps, cs = runs([1.0] * 4, [1.1] * 4)
        se, why = ledger.noise_se(list(zip(p, c)))
        self.assertIn("noise floor", why)
        self.assertAlmostEqual(se, 0.30 * (2 ** 0.5) / 2, places=6)
        # the paired spread alone would be zero here, which would crown a 0.1 gain a certain win
        v = ledger.verdict(list(zip(p, c)), ps, cs, CONF)
        self.assertNotEqual(v["decision"], "keep")


class TestPairing(unittest.TestCase):
    def test_only_shared_map_and_seed_pairs_are_compared(self):
        p = [att("E1M1", 1, 1.0), att("E1M2", 1, 1.0)]
        c = [att("E1M1", 1, 1.2), att("E1M3", 1, 1.9)]
        keys, pairs, skipped = ledger.pair(p, c)
        self.assertEqual(keys, [("E1M1", 1)])
        self.assertEqual(sorted(skipped), [("E1M2", 1), ("E1M3", 1)])

    def test_two_runs_with_nothing_in_common_are_refused(self):
        with self.assertRaises(SystemExit):
            ledger.pair([att("E1M1", 1, 1.0)], [att("E1M2", 2, 1.0)])


class TestTheCharterMetrics(unittest.TestCase):
    def rows(self, specs):
        """specs: (t, x, y, angle, mode, answers, select)"""
        return [{"kind": "control", "t": t, "episode": 1, "mode": mode, "answers": a, "select": s,
                 "raw": {"POS_X": x, "POS_Y": y, "ANGLE": ang}}
                for t, x, y, ang, mode, a, s in specs]

    def test_jev_share_counts_changes_the_model_caused(self):
        rows = self.rows([
            (0, 0, 0, 0, "EXPLORE", {"s_ahead": {}}, {}),                 # no change yet
            (1, 0, 0, 0, "EXPLORE", {"s_ahead": {}}, {}),                 # same intent
            (2, 0, 0, 0, "APPROACH", {"s_ahead": {}}, {}),                # changed, model decided
            (3, 0, 0, 0, "EXPLORE", {"s_ahead": {}}, {"fallback": "unsure gap"}),   # changed, code decided
            (4, 0, 0, 0, "FIGHT", {}, {}),                                # changed, no model asked
        ])
        self.assertAlmostEqual(fm.jev_share(rows), 1 / 3)

    def test_jev_share_is_none_when_nothing_ever_changed(self):
        self.assertIsNone(fm.jev_share(self.rows([(0, 0, 0, 0, "EXPLORE", {}, {})] * 3)))

    def test_a_held_decision_is_not_the_models(self):
        rows = self.rows([(0, 0, 0, 0, "EXPLORE", {"s_a": {}}, {}),
                          (1, 0, 0, 0, "APPROACH", {"s_a": {}}, {"held": True})])
        self.assertEqual(fm.jev_share(rows), 0.0)

    def test_fallback_rate(self):
        rows = self.rows([(0, 0, 0, 0, "EXPLORE", {}, {"margin": 0.6}),
                          (1, 0, 0, 0, "EXPLORE", {}, {"fallback": "unsure gap"})])
        self.assertEqual(fm.fallback_rate(rows), 0.5)

    def test_speed_explore_only_counts_exploring(self):
        rows = self.rows([(0, 0, 0, 0, "EXPLORE", {}, {}), (1, 100, 0, 0, "EXPLORE", {}, {}),
                          (2, 900, 0, 0, "FIGHT", {}, {})])
        self.assertAlmostEqual(fm.speed_explore(rows), 100.0)

    def test_revisit_fraction_needs_the_cell_to_be_old(self):
        soon = self.rows([(0, 0, 0, 0, "EXPLORE", {}, {}), (5, 0, 0, 0, "EXPLORE", {}, {})])
        late = self.rows([(0, 0, 0, 0, "EXPLORE", {}, {}), (60, 0, 0, 0, "EXPLORE", {}, {})])
        self.assertEqual(fm.revisit_fraction(soon), 0.0)
        self.assertGreater(fm.revisit_fraction(late), 0.0)

    def test_idle_fraction_sees_a_player_that_is_not_getting_anywhere(self):
        still = self.rows([(i * 0.25, 0, 0, 0, "EXPLORE", {}, {}) for i in range(20)])
        moving = self.rows([(i * 0.25, i * 40, 0, 0, "EXPLORE", {}, {}) for i in range(20)])
        self.assertEqual(fm.idle_fraction(still), 1.0)
        self.assertEqual(fm.idle_fraction(moving), 0.0)

    def test_decision_age_adds_the_three_delays(self):
        rows = [{"kind": "control", "tel_age_ms": 100, "latency_ms": 400, "cmd_ms": 45}]
        self.assertEqual(fm.decision_age_ms(rows), [545.0])
        self.assertEqual(fm.decision_age_complete(rows), 1.0)

    def test_a_row_without_the_telemetry_age_is_flagged_as_incomplete(self):
        rows = [{"kind": "control", "latency_ms": 400, "cmd_ms": 45}]
        self.assertEqual(fm.decision_age_ms(rows), [445.0])
        self.assertEqual(fm.decision_age_complete(rows), 0.0)

    def test_the_old_walk_metrics_are_unchanged(self):
        """Every baseline in docs/audit-2026-09-22.md was measured with these."""
        self.assertEqual(fm.SPIN_WINDOW_TICKS, 8)
        self.assertEqual(fm.SPIN_ROTATION_DEG, 300.0)
        self.assertEqual(fm.SPIN_TRAVEL_UNITS, 64.0)
        self.assertEqual(fm.CELL_UNITS, 128)
        self.assertEqual(fm.SPIN_WINDOW_SECONDS, 4.0)

    def test_the_old_module_name_is_the_same_definitions(self):
        """ground/metrics.py is a shim so the tools keep working. It must be the same file, not a copy of
        it -- a forked metric is how two readings of one log came out 12 percent apart."""
        sys.path.insert(0, os.path.join(ROOT, "ground"))
        import metrics
        self.assertTrue(os.path.samefile(metrics._PATH, fm.__file__),
                        "ground/metrics.py loads %s, not the frozen module" % metrics._PATH)
        self.assertEqual(metrics.SPIN_KEY, fm.SPIN_KEY)
        rows = self.rows([(0, 0, 0, 0, "EXPLORE", {}, {}), (1, 100, 0, 90, "EXPLORE", {}, {})])
        self.assertEqual(metrics.samples(rows), fm.samples(rows))
        self.assertEqual(metrics.path_units(metrics.samples(rows)), fm.path_units(fm.samples(rows)))


if __name__ == "__main__":
    unittest.main()
