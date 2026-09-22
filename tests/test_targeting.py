"""Choosing where to go: the words, the rubric, the rule that is not the rubric, and the intent.

The thing these tests are really guarding is the separation between the two. On the sector head, the
rubric was written as a level-by-level restatement of the code rule, and the consequence was that
sharpening the rubric drove agreement with ten lines of code from 79% to 89% -- the model could only
reproduce the rule, so the comparison measured nothing. `test_the_rule_is_not_a_copy_of_the_rubric` is
the guard against doing it again.
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ground"))
sys.path.insert(0, os.path.join(ROOT, "payload"))

import graph_config as gc        # noqa: E402
import targeting as tg           # noqa: E402

RULES = {"monsters": {"Zombieman": {"danger": 2}, "BaronOfHell": {"danger": 9}, "DoomImp": {"danger": 3}},
         "behaviour": {"health_critical": 30, "health_low": 50, "health_comfortable": 80,
                       "armor_low": 25, "ammo_low": {"shells": 6, "bullets": 20}}}


def cand(kind="frontier", path=300.0, novelty=200, tries=0, colour="", threat=255, count=0, bearing=0.0):
    return {"kind": kind, "x": 100.0, "y": 200.0, "bearing": bearing, "path_units": path,
            "novelty": novelty, "colour": colour, "tries": tries,
            "threat_class": threat, "threat_count": count}


class TestTheWordsTheModelSees(unittest.TestCase):
    def test_no_number_and_no_coordinate_reaches_the_model(self):
        """A classifier is not a calculator. Raw map positions in the state are noise to see past, and
        they are also how a decision quietly starts depending on the map frame."""
        t = {"HEALTH": 62, "ARMOR": 0, "SHELLS": 2, "BULLETS": 14, "KEYS": 1, "POS_X": 1.0, "POS_Y": 2.0}
        state = tg.build_state(t, [cand(), cand(kind="door", path=1500.0)],
                               tg.needs_from(t, RULES), ["red"], rules=RULES)
        for tid, words in state["targets"].items():
            for k, v in words.items():
                self.assertIsInstance(v, str, "%s.%s is not a word: %r" % (tid, k, v))
            self.assertNotIn("x", words)
            self.assertNotIn("y", words)
            self.assertNotIn("path_units", words)
        for k, v in state["here"].items():
            self.assertIsInstance(v, str, "here.%s is not a word: %r" % (k, v))

    def test_distance_is_given_relative_to_the_other_options(self):
        """An absolute band cannot separate "everything is far" from "this one is far and the rest are
        next door", and the second is the case where the answer matters."""
        near, mid, far = cand(path=100.0), cand(path=500.0), cand(path=2000.0)
        allc = [near, mid, far]
        self.assertEqual(tg.relative_distance(near, allc), "the nearest")
        self.assertEqual(tg.relative_distance(far, allc), "the furthest")
        self.assertIn(tg.relative_distance(mid, allc), ("nearer than most", "further than most"))
        self.assertEqual(tg.relative_distance(near, [near]), "the only one")

    def test_the_threat_word_is_a_judgement_made_with_the_knowledge_file(self):
        """The payload reports a class and a count, which are facts. "Deadly" is knowledge a player has."""
        self.assertEqual(tg.threat_word(cand(), RULES), "none")
        self.assertEqual(tg.threat_word(cand(threat=0, count=1), RULES), "a straggler")     # Zombieman
        self.assertEqual(tg.threat_word(cand(threat=8, count=1), RULES), "deadly")          # BaronOfHell
        self.assertEqual(tg.threat_word(cand(threat=0, count=4), RULES), "dangerous",
                         "several stragglers are not one straggler")

    def test_a_locked_door_says_whether_the_key_is_held(self):
        w = tg.target_words(cand(kind="door", colour="red"), None, ["red"], RULES)
        self.assertIn("held", w["locked"])
        w = tg.target_words(cand(kind="door", colour="blue"), None, ["red"], RULES)
        self.assertIn("no key", w["locked"])

    def test_a_pickup_says_whether_it_is_needed_now(self):
        self.assertEqual(tg.target_words(cand(kind="item", colour="health"), "health", [], RULES)["needed_now"], "yes")
        self.assertEqual(tg.target_words(cand(kind="item", colour="armor"), "health", [], RULES)["needed_now"], "no")


class TestTheRubricAsksForJudgement(unittest.TestCase):
    def setUp(self):
        self.criteria = gc.DEFAULT["questions"]["target"]["criteria"]

    def test_it_has_as_many_levels_as_the_rule_scores_over(self):
        self.assertEqual(len(self.criteria), tg.RULE_LEVELS)

    def test_every_level_is_inside_the_length_limit(self):
        for c in self.criteria:
            self.assertLessEqual(len(c), gc.TEXT_LIMIT, c)

    def test_the_rule_is_not_a_copy_of_the_rubric(self):
        """The guard against rebuilding the 89% problem on purpose.

        The rubric must weigh things the rule cannot see. If every field the rubric names is also read by
        the rule, the model can only reproduce the rule and the comparison measures nothing.
        """
        text = " ".join(self.criteria)
        for soft in ("threat", "health", "ammunition", "relative_distance", "needs"):
            self.assertIn(soft, text, "the rubric does not ask about %s" % soft)
        # Behavioural, not textual: the rule must be unmoved by the things the rubric is asked to weigh.
        base = cand()
        for field, value in (("threat_class", 8), ("threat_count", 5)):
            other = dict(base)
            other[field] = value
            self.assertEqual(tg.rule_score(tg.target_words(base, None, [], RULES, [base])),
                             tg.rule_score(tg.target_words(other, None, [], RULES, [other])),
                             "the rule moved on %s, so it is a shadow of the rubric" % field)
        # and it cannot see the player's condition at all: it is handed one target's words, nothing else
        import inspect
        self.assertEqual(list(inspect.signature(tg.rule_score).parameters)[0], "w")
        self.assertEqual(len(inspect.signature(tg.rule_score).parameters), 2,
                         "the rule takes one target and the level count; giving it `here` would make it "
                         "able to reproduce the rubric's trade-offs")

    def test_the_rubric_weighs_the_threat_against_what_there_is_to_spend(self):
        joined = " ".join(self.criteria)
        self.assertTrue(re.search(r"threat.*health|health.*threat", joined, re.S),
                        "no level trades danger off against condition")


class TestTheCodeBaseline(unittest.TestCase):
    """Deliberately simple, and it has to have an opinion about everything: it is also the fallback."""

    def words(self, **kw):
        return tg.target_words(cand(**kw), "health", [], RULES, [cand(**kw)])

    def test_the_exit_outranks_everything(self):
        self.assertGreater(tg.rule_score(self.words(kind="exit")), tg.rule_score(self.words(kind="key")))
        self.assertGreater(tg.rule_score(self.words(kind="key")), tg.rule_score(self.words(kind="door")))

    def test_a_door_that_did_not_open_is_worth_nothing(self):
        self.assertEqual(tg.rule_score(self.words(kind="door", tries=4)), 0.0)
        self.assertGreater(tg.rule_score(self.words(kind="door", tries=0)), 0.0)

    def test_among_frontiers_it_takes_the_nearest(self):
        near, far = cand(path=100.0), cand(path=3000.0)
        allc = [near, far]
        wn = tg.target_words(near, None, [], RULES, allc)
        wf = tg.target_words(far, None, [], RULES, allc)
        self.assertGreater(tg.rule_score(wn), tg.rule_score(wf))

    def test_it_is_blind_to_danger(self):
        """Not an oversight. The rule is the null hypothesis; danger is what the model is asked about."""
        safe = tg.target_words(cand(), None, [], RULES, [cand()])
        deadly = tg.target_words(cand(threat=8, count=3), None, [], RULES, [cand(threat=8, count=3)])
        self.assertEqual(tg.rule_score(safe), tg.rule_score(deadly))

    def test_it_always_has_an_opinion(self):
        for kind in ("frontier", "door", "exit", "key", "item", "switch"):
            self.assertIsInstance(tg.rule_score(self.words(kind=kind)), float)


class TestPickingAndCommitment(unittest.TestCase):
    def setUp(self):
        self.cfg = gc.load()
        self.mem = tg.TargetMemory(self.cfg)
        self.cands = [cand(path=100.0), cand(path=900.0)]
        self.cands[1]["x"] = 5000.0
        t = {"HEALTH": 90, "SHELLS": 8, "BULLETS": 50}
        self.state = tg.build_state(t, self.cands, tg.needs_from(t, RULES), [], rules=RULES)

    def answers(self, a, b):
        return {"g_t0": {"type": "score", "score": a, "confidence": 1.0},
                "g_t1": {"type": "score", "score": b, "confidence": 1.0}}

    def test_it_takes_the_best_answer(self):
        i, _d = tg.pick(self.answers(2.0, 7.0), self.state, self.cands, self.cfg, self.mem)
        self.assertEqual(i, 1)

    def test_a_near_tie_falls_back_to_the_rule_rather_than_dithering(self):
        i, d = tg.pick(self.answers(5.0, 5.05), self.state, self.cands, self.cfg, self.mem)
        self.assertIn("fallback", d)
        self.assertEqual(i, 0, "the rule prefers the nearer frontier")

    def test_a_low_confidence_answer_is_treated_as_cannot_tell(self):
        a = self.answers(2.0, 8.0)
        a["g_t1"]["confidence"] = 0.1
        _i, d = tg.pick(a, self.state, self.cands, self.cfg, self.mem)
        self.assertEqual(d.get("fallback"), "unsure answer")

    def test_it_holds_what_it_is_already_walking_to(self):
        tg.pick(self.answers(9.0, 1.0), self.state, self.cands, self.cfg, self.mem)
        self.assertTrue(self.mem.is_committed(self.cands[0]["x"], self.cands[0]["y"]))
        # clear of the unsure band, well inside the commitment margin
        i, d = tg.pick(self.answers(9.0, 9.4), self.state, self.cands, self.cfg, self.mem)
        self.assertEqual(i, 0)
        self.assertTrue(d.get("held"), "a small edge is not a reason to change target")

    def test_a_whole_level_better_always_wins(self):
        tg.pick(self.answers(9.0, 1.0), self.state, self.cands, self.cfg, self.mem)
        for _ in range(int(self.cfg["select"]["commit_ticks"]) + 1):
            self.mem.step()
        i, _d = tg.pick(self.answers(5.0, 7.0), self.state, self.cands, self.cfg, self.mem)
        self.assertEqual(i, 1, "two whole levels better and it still held on")

    def test_a_target_given_up_on_is_worth_less(self):
        self.mem.give_up(self.cands[1]["x"], self.cands[1]["y"], 60)
        i, _d = tg.pick(self.answers(5.0, 5.4), self.state, self.cands, self.cfg, self.mem)
        self.assertEqual(i, 0)


class TestTheIntent(unittest.TestCase):
    def setUp(self):
        self.cfg = gc.load()
        self.cands = [cand(kind="door", path=40.0), cand(kind="frontier", path=900.0)]
        t = {"HEALTH": 90, "SHELLS": 8, "BULLETS": 50}
        self.state = tg.build_state(t, self.cands, tg.needs_from(t, RULES), [], rules=RULES)

    def intent(self, t, pick=0):
        return tg.intent_for(t, self.state, self.cands, pick, self.cfg)

    def test_a_door_at_arm_s_length_is_operate_and_presses_use(self):
        it = self.intent({"HEALTH": 90, "SHELLS": 8, "BULLETS": 50})
        self.assertEqual(it["mode"], "OPERATE")
        self.assertTrue(it["use_at_target"])

    def test_a_far_door_is_approach(self):
        it = self.intent({"HEALTH": 90, "SHELLS": 8, "BULLETS": 50}, pick=1)
        self.assertEqual(it["mode"], "EXPLORE")
        it = tg.intent_for({"HEALTH": 90, "SHELLS": 8, "BULLETS": 50}, self.state,
                           [cand(kind="door", path=900.0)], 0, self.cfg)
        self.assertEqual(it["mode"], "APPROACH")

    def test_a_healthy_player_fights_what_is_close(self):
        it = self.intent({"HEALTH": 90, "SHELLS": 8, "BULLETS": 50, "ENEMY_COUNT": 1, "ENEMY_DIST": 200})
        self.assertEqual(it["mode"], "FIGHT")
        self.assertEqual(it["stance"], "advance_strafing")

    def test_a_hurt_player_retreats_instead_of_charging(self):
        """With no danger head asked, this used to fall through to FIGHT every time, so the player
        charged everything it met at running speed: 142 deaths on the dev set against 34."""
        it = self.intent({"HEALTH": 20, "SHELLS": 8, "BULLETS": 50, "ENEMY_COUNT": 1, "ENEMY_DIST": 200})
        self.assertEqual(it["mode"], "RETREAT")
        self.assertEqual(it["stance"], "retreat")
        self.assertEqual(it["fire_policy"], tg.FIRE_NONE)

    def test_a_player_with_no_ammunition_retreats(self):
        it = self.intent({"HEALTH": 90, "SHELLS": 0, "BULLETS": 0, "ENEMY_COUNT": 1, "ENEMY_DIST": 200})
        self.assertEqual(it["mode"], "RETREAT")

    def test_a_crowd_while_hurt_is_a_retreat(self):
        it = self.intent({"HEALTH": 45, "SHELLS": 8, "BULLETS": 50, "ENEMY_COUNT": 4, "ENEMY_DIST": 200})
        self.assertEqual(it["mode"], "RETREAT")

    def test_the_intent_carries_a_time_to_live(self):
        it = self.intent({"HEALTH": 90})
        self.assertEqual(it["ttl_ms"], self.cfg["select"]["intent_ttl_ms"])
        self.assertGreater(it["ttl_ms"], 0)

    def test_the_target_is_a_world_position_because_code_has_to_aim_at_it(self):
        it = self.intent({"HEALTH": 90})
        self.assertTrue(it["has_target"])
        self.assertEqual((it["target_x"], it["target_y"]), (self.cands[0]["x"], self.cands[0]["y"]))

    def test_the_weapon_is_a_rule_and_keeps_what_is_already_held(self):
        self.assertEqual(tg.best_weapon_slot({"OWN_SHOTGUN": True, "SHELLS": 4, "WEAPON": "SHOTGUN"}),
                         tg.WEAPON_KEEP)
        self.assertEqual(tg.best_weapon_slot({"OWN_SHOTGUN": True, "SHELLS": 4, "WEAPON": "PISTOL"}), 3)
        self.assertEqual(tg.best_weapon_slot({"OWN_SHOTGUN": False, "BULLETS": 0, "WEAPON": "PISTOL"}), 1)


class TestItMatchesTheRestOfTheStack(unittest.TestCase):
    def test_the_enemy_class_table_is_the_payload_s_own(self):
        import mapclasses as mc
        self.assertEqual(tg.ENEMY_CLASSES, mc.ENEMY_CLASSES,
                         "the ground would read a different monster out of the same byte")

    def test_every_class_in_the_table_is_ranked_in_the_knowledge_file(self):
        import yaml
        rules = yaml.safe_load(open(os.path.join(ROOT, "knowledge", "doom_rules.yaml"), encoding="utf-8"))
        for name in tg.ENEMY_CLASSES:
            self.assertIn(name, rules["monsters"], "%s has no danger rank" % name)

    def test_the_modes_and_stances_match_the_executor(self):
        import executor as ex
        self.assertEqual(sorted(tg.MODE_INDEX), sorted(ex.MODES))
        self.assertEqual(sorted(tg.STANCE_INDEX), sorted(ex.STANCES))
        for name, i in tg.MODE_INDEX.items():
            self.assertEqual(ex.MODES[i], name)
        for name, i in tg.STANCE_INDEX.items():
            self.assertEqual(ex.STANCES[i], name)


if __name__ == "__main__":
    unittest.main()


class TestDeterminismWithinARun(unittest.TestCase):
    """Charter 3.4. A System One model is not deterministic across calls, and the replay measured two
    commands differing between identical passes at a gap of 0.20. Small, and still enough that a run
    cannot be reproduced from its log."""

    class Counter:
        name = "counting"

        def __init__(self):
            self.calls = 0

        def ask(self, state, questions):
            self.calls += 1
            return {"answers": {q: {"type": "score", "score": float(self.calls), "confidence": 1.0}
                                for q in questions},
                    "latency_ms": 7, "usage": {"input_tokens": 3}, "model": "counting"}

    def setUp(self):
        self.cfg = gc.load()
        self.one = self.Counter()
        self.cache = tg.DecisionCache()
        self.t = {"HEALTH": 90, "SHELLS": 8, "BULLETS": 50, "POS_X": 0.0, "POS_Y": 0.0, "ANGLE": 0.0}

    def run_once(self, cands, mem=None):
        return tg.decide(self.t, cands, self.cfg, mem or tg.TargetMemory(self.cfg), self.one,
                         RULES, 0, cache=self.cache)

    def test_the_same_state_gets_the_same_answer(self):
        cands = [cand(), cand(path=900.0)]
        first = self.run_once(cands)
        second = self.run_once(cands)
        self.assertEqual(self.one.calls, 1, "it asked twice about an identical state")
        self.assertEqual(first["answers"], second["answers"])
        self.assertTrue(second["cached"])
        self.assertFalse(first["cached"])

    def test_a_state_that_really_changed_gets_a_fresh_call(self):
        self.run_once([cand()])
        self.run_once([cand(kind="exit")])
        self.assertEqual(self.one.calls, 2)

    def test_a_change_too_small_to_reach_the_words_does_not(self):
        """The state is quantised to words before it is hashed, so a pixel of movement is not a new state."""
        self.run_once([cand(path=300.0)])
        self.run_once([cand(path=301.0)])          # same distance band, same relative position
        self.assertEqual(self.one.calls, 1)

    def test_the_cache_reports_how_often_it_saved_a_call(self):
        cands = [cand()]
        for _ in range(4):
            self.run_once(cands)
        self.assertAlmostEqual(self.cache.hit_rate, 0.75)

    def test_it_can_be_turned_off(self):
        self.cache = tg.DecisionCache(enabled=False)
        cands = [cand()]
        self.run_once(cands)
        self.run_once(cands)
        self.assertEqual(self.one.calls, 2)
