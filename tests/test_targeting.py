"""Choosing where to go: the words, the rubric, the rule that is not the rubric, and the intent.

The thing these tests are really guarding is the separation between the two. On the sector head, the
rubric was written as a level-by-level restatement of the code rule, and the consequence was that
sharpening the rubric drove agreement with ten lines of code from 79% to 89% -- the model could only
reproduce the rule, so the comparison measured nothing. `test_the_rule_is_not_a_copy_of_the_rubric` is
the guard against doing it again.
"""
import io
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
        for soft in ("threat", "health", "ammunition", "relative_distance", "needs",
                     "unknown_runs", "further_from_the_start", "gate"):
            self.assertIn(soft, text, "the rubric does not ask about %s" % soft)
        # Behavioural, not textual: the rule must be unmoved by the things the rubric is asked to weigh.
        base = cand()
        for field, value in (("threat_class", 8), ("threat_count", 5),
                             ("opening", 400), ("depth", 2000), ("away", False)):
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

    def test_a_near_tie_falls_back_to_the_frozen_fallback_rather_than_dithering(self):
        """The brief allows code one fallback: keep the current target, else the nearest way on.

        It used to fall back to `rule_score`, which is a second rule and not that one. On an E1M1 flight
        it settled 31% of the decisions, and on another 49%.
        """
        i, d = tg.pick(self.answers(5.0, 5.05), self.state, self.cands, self.cfg, self.mem)
        self.assertEqual(d.get("fallback"), "unsure: nearest way on")
        self.assertEqual(i, 0, "nothing is held yet, so it takes the nearest way on")

    def test_a_near_tie_keeps_what_it_is_already_walking_to(self):
        tg.pick(self.answers(9.0, 1.0), self.state, self.cands, self.cfg, self.mem)   # commit to t0
        i, d = tg.pick(self.answers(5.0, 5.05), self.state, self.cands, self.cfg, self.mem)
        self.assertEqual(d.get("fallback"), "unsure: held")
        self.assertEqual(i, 0)

    def test_a_low_confidence_answer_is_treated_as_cannot_tell(self):
        a = self.answers(2.0, 8.0)
        a["g_t1"]["confidence"] = 0.1
        _i, d = tg.pick(a, self.state, self.cands, self.cfg, self.mem)
        self.assertTrue(str(d.get("fallback", "")).startswith("unsure"), d)

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
        self.assertEqual(it["fire_policy"], tg.FIRE_ANY_ATTACKER,
                         "a retreat that does not return fire is a slower death: RETREAT was 99 of the "
                         "203 deaths on the dev set")

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


class TestTheCombatHeads(unittest.TestCase):
    """Charter 4. The charter's own example of a question worth asking: "three imps and a sergeant
    between me and the only frontier, 38 health, 12 shells, armor behind me." No field settles that."""

    def setUp(self):
        self.cfg = gc.load()

    def met(self, **kw):
        t = {"HEALTH": 70, "SHELLS": 8, "BULLETS": 40, "ENEMY_COUNT": 2, "ENEMY_DIST": 250,
             "THREAT_CLASS": 3, "THREAT_COUNT": 2}       # DoomImp
        t.update(kw)
        return t

    def test_an_empty_room_has_no_combat_words_and_asks_nothing(self):
        t = {"HEALTH": 90, "ENEMY_COUNT": 0, "THREAT_COUNT": 0}
        state = tg.build_state(t, [cand()], tg.needs_from(t, RULES), [], rules=RULES)
        self.assertEqual(state["combat"]["threat"], "none")
        qs = tg.questions(state, self.cfg)
        self.assertNotIn("engage", qs, "a head asked about an empty room is latency for nothing")
        self.assertNotIn("weapon", qs)

    def test_meeting_something_asks_both_heads_in_the_same_call(self):
        t = self.met()
        state = tg.build_state(t, [cand()], tg.needs_from(t, RULES), [], rules=RULES)
        qs = tg.questions(state, self.cfg)
        self.assertIn("engage", qs)
        self.assertIn("weapon", qs)
        self.assertEqual(qs["engage"]["type"], "choice")

    def test_the_combat_words_name_the_class_and_rank_it_from_the_knowledge_file(self):
        t = self.met(THREAT_CLASS=8, THREAT_COUNT=1)      # BaronOfHell
        c = tg.combat_words(t, RULES)
        self.assertEqual(c["what"], "BaronOfHell")
        self.assertEqual(c["threat"], "deadly")
        self.assertEqual(c["count"], "one")
        self.assertEqual(c["distance"], "close")

    def test_an_engage_answer_sets_the_mode_and_the_stance(self):
        t = self.met()
        state = tg.build_state(t, [cand()], tg.needs_from(t, RULES), [], rules=RULES)
        for answer, (mode, stance) in tg.ENGAGE_MODE.items():
            it = tg.intent_for(t, state, [cand()], 0, self.cfg, engage=answer, rules=RULES)
            if answer == "Break off and go round":
                self.assertIn(it["mode"], ("EXPLORE", "APPROACH", "OPERATE"))
            else:
                self.assertEqual(it["mode"], mode)
            self.assertEqual(it["stance"], stance)

    def test_the_backstop_answers_when_the_head_did_not(self):
        self.assertEqual(tg.engage_backstop(self.met(HEALTH=20), self.cfg), "Retreat")
        self.assertEqual(tg.engage_backstop(self.met(SHELLS=0, BULLETS=0), self.cfg), "Retreat")
        self.assertEqual(tg.engage_backstop(self.met(HEALTH=40, ENEMY_COUNT=4), self.cfg), "Retreat")
        # Neutral by design: choosing a fight is the model's judgement, and a code baseline that picks
        # one is the most dangerous player in its own comparison.
        self.assertEqual(tg.engage_backstop(self.met(), self.cfg), "Break off and go round")

    def test_the_weapon_rule_overrules_the_head_on_an_empty_gun(self):
        # holding the shotgun, out of shells: drop to the pistol
        self.assertEqual(tg.weapon_backstop(self.met(SHELLS=0, WEAPON="SHOTGUN"), "Shotgun", RULES), 2)
        # holding the pistol with nothing loaded at all: the fist is the only thing left
        self.assertEqual(tg.weapon_backstop(self.met(SHELLS=0, BULLETS=0, WEAPON="PISTOL"),
                                            "Chaingun", RULES), 1)

    def test_it_keeps_what_is_already_in_hand_rather_than_re_selecting_every_tick(self):
        """Selecting a weapon holds the select button, which is a tick not spent shooting."""
        self.assertEqual(tg.weapon_backstop(self.met(WEAPON="SHOTGUN"), "Shotgun", RULES), tg.WEAPON_KEEP)

    def test_it_never_fires_a_splash_weapon_at_point_blank(self):
        rules = {"weapons": {"RocketLauncher": {"slot": 5, "splash": True}},
                 "behaviour": {"splash_min_distance": 200}}
        close = tg.weapon_backstop(self.met(ENEMY_DIST=80), "RocketLauncher", rules)
        self.assertNotEqual(close, 5, "a rocket at point blank kills the player who fired it")
        far = tg.weapon_backstop(self.met(ENEMY_DIST=900), "RocketLauncher", rules)
        self.assertEqual(far, 5)

    def test_an_unusable_answer_falls_through_to_the_rule_rather_than_being_ignored(self):
        t = self.met(HEALTH=15)
        state = tg.build_state(t, [cand()], tg.needs_from(t, RULES), [], rules=RULES)
        one = TestDeterminismWithinARun.Counter()

        class Nonsense(one.__class__):
            def ask(self, state, questions):
                out = super().ask(state, questions)
                out["answers"]["engage"] = {"type": "choice", "choice": "Do a little dance"}
                return out

        d = tg.decide(t, [cand()], self.cfg, tg.TargetMemory(self.cfg), Nonsense(), RULES, 0)
        self.assertTrue(d["detail"].get("engage_fallback"))
        self.assertEqual(d["intent"]["mode"], "RETREAT")


class TestWhenTheModelCannotAnswer(unittest.TestCase):
    """A read timeout is an operational fact, not a reason to throw the attempt away.

    Six of fifteen jev attempts were being voided by a 10 s timeout against the TypeSafe endpoint, which
    failed the crashes guardrail and so discarded the row. The code rule exists precisely for the ticks
    the model cannot answer; a pilot that stops flying because a request timed out is a worse pilot than
    one that falls back.
    """

    class Broken:
        name = "broken"

        def ask(self, state, questions):
            raise IOError("Read timed out. (read timeout=10)")

    def setUp(self):
        self.cfg = gc.load()
        self.t = {"HEALTH": 90, "SHELLS": 8, "BULLETS": 40, "POS_X": 0.0, "POS_Y": 0.0, "ANGLE": 0.0}

    def test_the_attempt_carries_on_with_the_rule(self):
        d = tg.decide(self.t, [cand(), cand(kind="exit", path=900.0)], self.cfg,
                      tg.TargetMemory(self.cfg), self.Broken(), RULES, 0)
        self.assertIsNotNone(d["pick"])
        self.assertTrue(d["answers"], "it should still have answers, from the rule")
        self.assertEqual(d["intent"]["mode"], "APPROACH")

    def test_it_says_so_rather_than_pretending_the_model_answered(self):
        d = tg.decide(self.t, [cand()], self.cfg, tg.TargetMemory(self.cfg), self.Broken(), RULES, 0)
        self.assertIn("Read timed out", d["unavailable"])
        self.assertEqual(d["reply"]["model"], "code (fallback)")

    def test_the_answers_are_the_rule_s_own(self):
        cands = [cand(), cand(kind="exit", path=900.0)]
        d = tg.decide(self.t, cands, self.cfg, tg.TargetMemory(self.cfg), self.Broken(), RULES, 0)
        state = d["state"]
        self.assertEqual(d["answers"]["g_t1"]["score"], tg.rule_score(state["targets"]["t1"]))

    def test_a_working_model_is_not_marked_unavailable(self):
        d = tg.decide(self.t, [cand()], self.cfg, tg.TargetMemory(self.cfg),
                      TestDeterminismWithinARun.Counter(), RULES, 0)
        self.assertIsNone(d["unavailable"])


class TestGivingUpOnATarget(unittest.TestCase):
    """The first full-pipeline flight stalled here: 187 of 342 decisions in OPERATE, 69 of them
    consecutive at the end, standing at a door pressing Use with the level untouched around it.
    `TargetMemory.give_up` existed and nothing ever called it, so a target once chosen was chosen for
    the rest of the attempt."""

    def setUp(self):
        self.cfg = gc.load()
        self.mem = tg.TargetMemory(self.cfg)

    def test_getting_closer_is_not_a_stall(self):
        self.mem.commit(0.0, 0.0)
        for d in (500.0, 400.0, 300.0, 200.0, 100.0):
            self.assertFalse(self.mem.note_progress(d, 5))

    def test_standing_still_at_a_target_eventually_gives_up(self):
        self.mem.commit(0.0, 0.0)
        gave_up = [self.mem.note_progress(300.0, 5) for _ in range(12)]
        self.assertTrue(any(gave_up), "it never gave up on a target it was getting no closer to")

    def test_choosing_a_new_target_resets_the_patience(self):
        self.mem.commit(0.0, 0.0)
        for _ in range(4):
            self.mem.note_progress(300.0, 5)
        self.mem.commit(9000.0, 9000.0)
        self.assertFalse(self.mem.note_progress(300.0, 5))

    def test_a_target_given_up_on_is_not_immediately_chosen_again(self):
        self.mem.give_up(100.0, 200.0, 30)
        self.assertTrue(self.mem.gave_up_recently(100.0, 200.0))
        for _ in range(31):
            self.mem.step()
        self.assertFalse(self.mem.gave_up_recently(100.0, 200.0))

    def test_the_decision_abandons_a_target_it_is_getting_nowhere_with(self):
        cands = [cand(kind="door", path=40.0), cand(kind="frontier", path=600.0)]
        cands[1]["x"] = 5000.0
        t = {"HEALTH": 90, "SHELLS": 8, "BULLETS": 40}
        one = TestDeterminismWithinARun.Counter()
        mem = tg.TargetMemory(self.cfg)
        picks = []
        for _ in range(int(self.cfg["select"]["approach_ticks"]) + 4):
            d = tg.decide(t, cands, self.cfg, mem, one, RULES, 0)
            picks.append(d["pick"])
        self.assertGreater(mem.give_ups, 0, "it stood at the same door forever")
        self.assertGreater(len(set(picks)), 1, "it never tried anything else")


class TestFightingWhileBusy(unittest.TestCase):
    def setUp(self):
        self.cfg = gc.load()
        self.cands = [cand(kind="door", path=40.0)]
        t = {"HEALTH": 90, "SHELLS": 8, "BULLETS": 50}
        self.state = tg.build_state(t, self.cands, tg.needs_from(t, RULES), [], rules=RULES)

    def test_a_door_in_an_empty_room_is_leaned_on_not_stood_in_front_of(self):
        """Standing still at a door was six of seventeen watchdog freezes: a deliberate stand-still
        reads as a stuck player, and each one cost four seconds plus a recovery. A player walks into
        the door and taps Use."""
        it = tg.intent_for({"HEALTH": 90, "SHELLS": 8, "BULLETS": 50, "ENEMY_COUNT": 0},
                           self.state, self.cands, 0, self.cfg, rules=RULES)
        self.assertEqual(it["mode"], "OPERATE")
        self.assertEqual(it["stance"], "advance")
        self.assertTrue(it["use_at_target"])

    def test_a_door_with_something_shooting_at_it_is_not(self):
        """37 of 203 deaths were in OPERATE with stance=hold."""
        it = tg.intent_for({"HEALTH": 90, "SHELLS": 8, "BULLETS": 50, "ENEMY_COUNT": 1, "ENEMY_DIST": 200},
                           self.state, self.cands, 0, self.cfg, rules=RULES)
        self.assertNotEqual(it["stance"], "hold")
        self.assertEqual(it["fire_policy"], tg.FIRE_ANY_ATTACKER)


class TestTheStructNamesMatch(unittest.TestCase):
    """The flight struct and the ground decoder have to agree on spelling.

    They did not. `normalise` read "dist" where the F Prime Candidate struct calls it `pathUnits`, and
    never read threatClass/threatCount at all, so on every flight jev was handed six candidates all
    described as "right here", all "the nearest", all with threat "none" -- it scored them 5.00 across
    the board and the pick fell to the tie-break. Nothing failed, nothing logged, and the run looked
    like a model that could not tell options apart. Read the names out of the .fpp so the next rename
    breaks a test instead of a flight.
    """

    def struct_members(self):
        fpp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "flight", "Components", "Doom", "Doom.fpp")
        text = io.open(fpp, encoding="utf-8").read()
        body = text.split("struct Candidate {", 1)[1].split("}", 1)[0]
        return [ln.strip().split(":")[0].strip() for ln in body.splitlines() if ":" in ln]

    def test_normalise_reads_every_member_the_struct_downlinks(self):
        members = self.struct_members()
        self.assertIn("pathUnits", members)
        seen = {}
        c = {m: 1 for m in members}
        c.update({"kind": 0, "x": 10.0, "y": 20.0, "pathUnits": 640, "novelty": 30,
                  "opening": 96, "depth": 512, "away": 1, "flags": 0,
                  "threatClass": 3, "threatCount": 2})

        class Watched(dict):
            def get(self, k, d=None):
                seen[k] = True
                return dict.get(self, k, d)

        out = tg.normalise(Watched(c), {"POS_X": 0.0, "POS_Y": 0.0, "ANGLE": 0.0})
        missed = [m for m in members if m not in seen]
        self.assertEqual(missed, [], "normalise never reads %s" % missed)
        self.assertEqual(out["path_units"], 640.0)
        self.assertEqual(out["threat_class"], 3)
        self.assertEqual(out["threat_count"], 2)

    def test_the_words_move_when_the_numbers_do(self):
        """The failure was not a wrong word, it was the same word every time. Pin the variation."""
        t = {"POS_X": 0.0, "POS_Y": 0.0, "ANGLE": 0.0}
        near = tg.normalise({"kind": 0, "x": 64.0, "y": 0.0, "pathUnits": 64}, t)
        far = tg.normalise({"kind": 0, "x": 900.0, "y": 0.0, "pathUnits": 900}, t)
        both = [near, far]
        self.assertNotEqual(tg.target_words(near, None, [], all_cands=both)["how_far"],
                            tg.target_words(far, None, [], all_cands=both)["how_far"])
        self.assertEqual(tg.target_words(near, None, [], all_cands=both)["relative_distance"],
                         "the nearest")
        self.assertEqual(tg.target_words(far, None, [], all_cands=both)["relative_distance"],
                         "the furthest")
