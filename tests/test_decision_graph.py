"""The behaviours the audit found broken, pinned as tests.

Each test names the issue it guards. They run without the game, Yamcs or a network: a telemetry dict in,
a command dict out.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ground"))

import decision_graph as dg          # noqa: E402
import graph_config as gc            # noqa: E402

CFG = gc.validate(gc.DEFAULT)


def telemetry(**over):
    """A plain, open, unexplored scene with every channel present."""
    t = {"ANGLE": 0.0, "POS_X": 0.0, "POS_Y": 0.0, "HEALTH": 100, "ARMOR": 0, "SHELLS": 0, "BULLETS": 50,
         "WEAPON": "PISTOL", "OWN_SHOTGUN": False, "ENEMY_COUNT": 0, "ENEMY_BEARING": 0.0, "ENEMY_DIST": 0,
         "AHEAD_KIND": "NOTHING", "AHEAD_DIST": 0, "STUCK": False, "LEVEL": 1, "KEYS": 0,
         "EXIT_DIST": 0, "KEY_DIST": 0, "HEALTH_ITEM_DIST": 0, "AMMO_ITEM_DIST": 0, "ARMOR_ITEM_DIST": 0,
         "HINT_ACTIVE": False, "HINT_REL": 0, "CLEAR_MAP_FWD": 400}
    for ck, nk, dk in dg.DIR_KEYS.values():
        t[ck], t[nk], t[dk] = 400, 255, 0
    t.update(over)
    return t


def scores(best, value=3.0, other=1.0, conf=0.95):
    out = {"s_%s" % d: {"type": "score", "score": other, "confidence": conf} for d in dg.SECTORS}
    out["s_%s" % best] = {"type": "score", "score": value, "confidence": conf}
    return out


class Vocabulary(unittest.TestCase):
    """Issue 8: the exit, the key, the hint and the sectors all speak in the same eight labels."""

    def test_sector_of_bins_every_bearing(self):
        self.assertEqual(dg.sector_of(0), "ahead")
        self.assertEqual(dg.sector_of(40), "ahead-left")      # the old words called 40 degrees "to the left"
        self.assertEqual(dg.sector_of(89), "left")
        self.assertEqual(dg.sector_of(-46), "ahead-right")
        self.assertEqual(dg.sector_of(179), "behind")
        self.assertEqual(dg.sector_of(-179), "behind")

    def test_exit_lands_in_its_own_sector_field(self):
        s = dg.build_state(telemetry(EXIT_DIST=200, EXIT_BEARING=40.0), "EXPLORE", CFG)
        self.assertEqual(s["sectors"]["ahead-left"]["exit_here"], "yes")
        self.assertEqual(s["sectors"]["left"]["exit_here"], "no")
        self.assertEqual(s["seen"]["exit"], "mid-range ahead-left")


class UnknownIsNotGood(unittest.TestCase):
    """Issue 4: a dropped channel used to default to 999 clearance and 100 novelty, the best option on offer."""

    def test_missing_channel_makes_the_sector_unknown_and_unoffered(self):
        t = telemetry()
        del t["CLEAR_LEFT"]
        s = dg.build_state(t, "EXPLORE", CFG)
        self.assertEqual(s["sectors"]["left"], {"data": "unknown"})
        self.assertNotIn("left", dg.offered_sectors(s))

    def test_blocked_sectors_are_not_offered(self):
        s = dg.build_state(telemetry(CLEAR_LEFT=10), "EXPLORE", CFG)
        self.assertNotIn("left", dg.offered_sectors(s))

    def test_stop_is_explicit_zeros(self):
        # The end-of-run stop used to be control_args({}), which defaulted the `advance` Noul to 1.0 and
        # therefore commanded the player to keep walking forward as the pilot shut down.
        self.assertEqual(dg.STOP["move"], 0)
        self.assertEqual(dg.STOP["turn"], 0.0)
        self.assertFalse(dg.STOP["fire"])
        self.assertFalse(dg.STOP["use"])

    def test_no_answers_at_all_never_walks(self):
        t = telemetry()
        mem = dg.NavMemory(CFG)
        s = dg.build_state(t, "EXPLORE", CFG, mem)
        for mode in dg.MODES:
            c = dg.control_args(s, t, CFG, dg.NavMemory(CFG), mode, {}, pick=None)
            self.assertIn(c["move"], (0, 1, -1), mode)
        done = dg.control_args(s, t, CFG, mem, "DONE", {}, pick=None)
        self.assertEqual((done["move"], done["turn"], done["fire"]), (0, 0.0, False))


class WorldFrameMemory(unittest.TestCase):
    """Issue 5: 'keep going left' named a new direction after every turn, so the player span."""

    def test_the_committed_bearing_survives_a_turn(self):
        mem = dg.NavMemory(CFG)
        mem.commit(heading=0.0, label="left", pos=(0.0, 0.0))       # world bearing 90
        self.assertEqual(mem.label_now(0.0), "left")
        self.assertEqual(mem.label_now(45.0), "ahead-left")
        self.assertEqual(mem.label_now(90.0), "ahead")              # the turn landed: now it is straight on

    def test_once_the_turn_lands_the_commitment_becomes_walk_not_another_turn(self):
        """The old hysteresis kept the word 'left', so every tick re-commanded another 90 degrees. Here the
        commitment is a world bearing, so once the heading has swung onto it the pilot simply walks."""
        mem = dg.NavMemory(CFG)
        s = dg.build_state(telemetry(), "EXPLORE", CFG)
        pick, _ = dg.pick_sector(scores("left"), s, CFG, mem, heading=0.0, pos=(0.0, 0.0))
        self.assertEqual(dg.travel_controls(s, pick)["turn"], 90.0)
        mem.step()
        s2 = dg.build_state(telemetry(ANGLE=90.0), "EXPLORE", CFG)
        # jev mildly prefers "left" again at the new heading: under the old graph that re-commanded another
        # 90 degrees every tick. The gap is inside the margin, so the committed bearing wins instead.
        drift = {"s_%s" % d: {"type": "score", "score": 1.5, "confidence": 0.9} for d in dg.offered_sectors(s2)}
        drift["s_left"] = {"type": "score", "score": 2.2, "confidence": 0.9}   # clear of the unsure band,
        #                                                                       but inside the hysteresis margin
        pick2, detail = dg.pick_sector(drift, s2, CFG, mem, heading=90.0, pos=(0.0, 0.0))
        self.assertEqual(pick2, "ahead")                            # not another 90 degrees to the left
        self.assertTrue(detail["held"])
        c = dg.travel_controls(s2, pick2)
        self.assertEqual((c["move"], c["turn"]), (1, 0.0))

    def test_a_direction_held_without_progress_is_marked_tried(self):
        mem = dg.NavMemory(CFG)
        mem.commit(0.0, "left", (0.0, 0.0))
        for _ in range(5):
            mem.step()
        mem.commit(0.0, "right", (10.0, 0.0))                       # 10 units: went nowhere
        self.assertTrue(mem.tried_recently(0.0, "left"))
        self.assertFalse(mem.tried_recently(0.0, "right"))
        s = dg.build_state(telemetry(), "EXPLORE", CFG, mem)
        self.assertEqual(s["sectors"]["left"]["tried_recently"], "yes")


class UnsureBand(unittest.TestCase):
    """Issue 10: a hard 0.5 cutoff turned one walk decision in five into a coin flip."""

    def test_a_near_tie_goes_to_the_named_fallback(self):
        mem = dg.NavMemory(CFG)
        s = dg.build_state(telemetry(CLEAR_LEFT=600, NEW_LEFT=255, NEW_FWD=10), "EXPLORE", CFG)
        flat = {"s_%s" % d: {"type": "score", "score": 1.5, "confidence": 0.99} for d in dg.offered_sectors(s)}
        pick, detail = dg.pick_sector(flat, s, CFG, mem, heading=0.0, pos=(0.0, 0.0))
        self.assertEqual(detail["fallback"], "unsure gap")
        self.assertEqual(pick, dg.frontier_fallback(s, dg.offered_sectors(s)))
        self.assertEqual(mem.fallbacks, 1)

    def test_the_gap_and_the_answer_are_two_independent_ways_to_be_unsure(self):
        # Each sector is scored by its own question, so a Score's `confidence` says how concentrated that
        # sector's own answer is, not how far it beats the others. Replaying the 22 September run found jev
        # at 0.97-0.99 confidence per sector with the top two 0.01 levels apart: requiring both conditions
        # meant the band never fired once in 116 states.
        s = dg.build_state(telemetry(), "EXPLORE", CFG)
        offered = dg.offered_sectors(s)
        wide_but_unsure = {"s_%s" % d: {"type": "score", "score": 0.5, "confidence": 0.1} for d in offered}
        wide_but_unsure["s_left"] = {"type": "score", "score": 3.0, "confidence": 0.1}
        _, detail = dg.pick_sector(wide_but_unsure, s, CFG, dg.NavMemory(CFG), 0.0, pos=(0.0, 0.0))
        self.assertEqual(detail["fallback"], "unsure answer")
        confident_and_separated = {"s_%s" % d: {"type": "score", "score": 0.5, "confidence": 0.9} for d in offered}
        confident_and_separated["s_left"] = {"type": "score", "score": 3.0, "confidence": 0.9}
        pick, detail = dg.pick_sector(confident_and_separated, s, CFG, dg.NavMemory(CFG), 0.0, pos=(0.0, 0.0))
        self.assertIsNone(detail["fallback"])
        self.assertEqual(pick, "left")

    def test_the_fallback_is_deterministic(self):
        s = dg.build_state(telemetry(CLEAR_LEFT=600, NEW_FWD=10, NEW_RIGHT=10), "EXPLORE", CFG)
        offered = dg.offered_sectors(s)
        self.assertEqual({dg.frontier_fallback(s, offered) for _ in range(20)}, {dg.frontier_fallback(s, offered)})

    def test_a_confident_close_call_is_still_jevs(self):
        mem = dg.NavMemory(CFG)
        s = dg.build_state(telemetry(), "EXPLORE", CFG)
        near = {"s_%s" % d: {"type": "score", "score": 1.0, "confidence": 0.9} for d in dg.offered_sectors(s)}
        near["s_left"] = {"type": "score", "score": 1.5, "confidence": 0.9}   # half a level clear of the band
        pick, detail = dg.pick_sector(near, s, CFG, mem, heading=0.0, pos=(0.0, 0.0))
        self.assertIsNone(detail["fallback"])
        self.assertEqual(pick, "left")


class Hysteresis(unittest.TestCase):
    """Hysteresis damps flicker; it must never override a clearly better direction."""

    def held_then(self, first, second, heading=0.0):
        mem = dg.NavMemory(CFG)
        s = dg.build_state(telemetry(), "EXPLORE", CFG)
        dg.pick_sector(first, s, CFG, mem, heading, pos=(0.0, 0.0))
        mem.step()
        return dg.pick_sector(second, s, CFG, mem, heading, pos=(0.0, 0.0))

    def test_a_small_difference_does_not_break_a_fresh_commitment(self):
        near = scores("right", value=1.5, other=1.0)      # half a level better: inside the margin
        pick, detail = self.held_then(scores("left"), near)
        self.assertEqual(pick, "left")
        self.assertTrue(detail["held"])
        self.assertLess(detail["margin"], 1.0)            # the effective margin is always under one level

    def test_a_whole_level_better_wins_even_inside_the_commit_window(self):
        pick, detail = self.held_then(scores("left"), scores("right", value=2.0, other=1.0))
        self.assertEqual(pick, "right")
        self.assertFalse(detail["held"])

    def test_the_exit_is_never_held_off_by_a_fresh_commitment(self):
        mem = dg.NavMemory(CFG)
        s = dg.build_state(telemetry(), "EXPLORE", CFG)
        dg.pick_sector(scores("left"), s, CFG, mem, 0.0, pos=(0.0, 0.0))
        mem.step()
        s2 = dg.build_state(telemetry(EXIT_DIST=200, EXIT_BEARING=-90.0), "EXPLORE", CFG)
        self.assertEqual(s2["sectors"]["right"]["exit_here"], "yes")
        pick, _ = dg.pick_sector(scores("right", value=3.0, other=1.0), s2, CFG, mem, 0.0, pos=(0.0, 0.0))
        self.assertEqual(pick, "right")

    def test_the_margin_relaxes_once_the_commitment_has_aged(self):
        mem = dg.NavMemory(CFG)
        s = dg.build_state(telemetry(), "EXPLORE", CFG)
        dg.pick_sector(scores("left"), s, CFG, mem, 0.0, pos=(0.0, 0.0))
        for _ in range(CFG["select"]["commit_ticks"] + 1):
            mem.step()
            mem.commit(0.0, "left", (0.0, 0.0))
        _, detail = dg.pick_sector(scores("right", value=1.9, other=1.0), s, CFG, mem, 0.0, pos=(0.0, 0.0))
        self.assertAlmostEqual(detail["margin"], CFG["select"]["sector_margin"])

    def test_a_tried_direction_loses_a_level_in_code_not_in_a_criterion(self):
        mem = dg.NavMemory(CFG)
        mem.commit(0.0, "left", (0.0, 0.0))
        mem.step()
        mem.commit(0.0, "ahead", (5.0, 0.0))              # left was held and went nowhere
        s = dg.build_state(telemetry(), "EXPLORE", CFG, mem)
        self.assertEqual(dg.adjust(s, "left", "EXPLORE", CFG), -CFG["select"]["tried_penalty"])
        self.assertEqual(dg.adjust(s, "right", "EXPLORE", CFG), 0.0)
        rendered = json.dumps(dg.rendered_questions(CFG))
        self.assertNotIn("tried_recently", rendered)      # the rule is code's, so jev is never asked it


class RulesThatLeftJev(unittest.TestCase):
    """Issue 11: four heads re-derived rules code already had, and one of them had a bug."""

    def test_a_long_passage_counts_as_dodge_space(self):
        # The old dodge head only offered a side that read exactly "open"; "long" is the best dodge space.
        s = dg.build_state(telemetry(CLEAR_LEFT=600, CLEAR_RIGHT=30, ENEMY_COUNT=1, ENEMY_DIST=100,
                                     ENEMY_BEARING=0.0), "EXPLORE", CFG)
        self.assertEqual(s["sectors"]["left"]["space"], "long")
        self.assertEqual(dg.combat_controls(s, telemetry(), CFG, danger=2.0)["strafe"], -1)

    def test_fire_needs_a_target_and_ammunition(self):
        t = telemetry(ENEMY_COUNT=1, ENEMY_DIST=100, ENEMY_BEARING=0.0, BULLETS=0)
        s = dg.build_state(t, "EXPLORE", CFG)
        self.assertFalse(dg.combat_controls(s, t, CFG, danger=1.0)["fire"])
        t = telemetry(ENEMY_COUNT=1, ENEMY_DIST=100, ENEMY_BEARING=0.0, BULLETS=20)
        s = dg.build_state(t, "EXPLORE", CFG)
        self.assertTrue(dg.combat_controls(s, t, CFG, danger=1.0)["fire"])

    def test_weapon_is_a_pure_ammunition_rule(self):
        self.assertEqual(dg.best_weapon(telemetry(OWN_SHOTGUN=True, SHELLS=4, WEAPON="PISTOL")), "SHOTGUN")
        self.assertEqual(dg.best_weapon(telemetry(OWN_SHOTGUN=False, BULLETS=9, WEAPON="FIST")), "PISTOL")
        self.assertEqual(dg.best_weapon(telemetry(SHELLS=0, BULLETS=0, WEAPON="PISTOL")), "FIST")

    def test_the_weapon_already_in_hand_is_never_re_selected(self):
        # The payload holds the select-weapon button for as long as the command names a real weapon, so
        # asking for the equipped weapon every tick would hold that button down for the whole run.
        self.assertEqual(dg.best_weapon(telemetry(OWN_SHOTGUN=True, SHELLS=4, WEAPON="SHOTGUN")), "FIST")
        self.assertEqual(dg.best_weapon(telemetry(BULLETS=9, WEAPON="PISTOL")), "FIST")

    def test_aim_uses_the_number_not_a_word(self):
        t = telemetry(ENEMY_COUNT=1, ENEMY_DIST=200, ENEMY_BEARING=23.0)
        s = dg.build_state(t, "EXPLORE", CFG)
        self.assertAlmostEqual(dg.combat_controls(s, t, CFG, danger=1.0)["turn"], 23.0)


class Reflex(unittest.TestCase):
    """Rule 9: hard invariants live in code, under every mode."""

    def test_never_fires_with_no_ammunition(self):
        t = telemetry(BULLETS=0, SHELLS=0)
        s = dg.build_state(t, "EXPLORE", CFG)
        self.assertFalse(dg.reflex({**dg.STOP, "fire": True}, s, t, CFG)["fire"])

    def test_never_walks_into_a_known_wall(self):
        t = telemetry(CLEAR_FWD=10, CLEAR_MAP_FWD=10)
        s = dg.build_state(t, "EXPLORE", CFG)
        self.assertEqual(dg.reflex({**dg.STOP, "move": 1}, s, t, CFG)["move"], 0)

    def test_walks_up_to_a_door_even_when_the_camera_calls_it_blocked(self):
        t = telemetry(CLEAR_FWD=10, CLEAR_MAP_FWD=10, AHEAD_KIND="DOOR", AHEAD_DIST=40)
        s = dg.build_state(t, "EXPLORE", CFG)
        self.assertEqual(dg.reflex({**dg.STOP, "move": 1}, s, t, CFG)["move"], 1)

    def test_never_re_commands_a_turn_still_in_flight(self):
        t = telemetry()
        s = dg.build_state(t, "EXPLORE", CFG)
        out = dg.reflex({**dg.STOP, "turn": 90.0}, s, t, CFG, pending_turn=45.0)
        self.assertEqual(out["turn"], 0.0)

    def test_turn_is_capped(self):
        t = telemetry()
        s = dg.build_state(t, "EXPLORE", CFG)
        self.assertLessEqual(abs(dg.reflex({**dg.STOP, "turn": 180.0}, s, t, CFG)["turn"]),
                             CFG["thresholds"]["max_turn_deg"])


class Modes(unittest.TestCase):
    """Rule 8: every transition is an exact rule in code, not a clause in a criterion."""

    def make(self):
        return dg.NavMemory(CFG)

    def test_stuck_enters_recover_and_leaves_after_moving(self):
        mem = self.make()
        t = telemetry(STUCK=True)
        self.assertEqual(dg.next_mode(dg.build_state(t, "EXPLORE", CFG, mem), t, mem, CFG), "RECOVER")
        t2 = telemetry(POS_X=200.0)
        self.assertEqual(dg.next_mode(dg.build_state(t2, "EXPLORE", CFG, mem), t2, mem, CFG), "EXPLORE")

    def test_a_door_at_arms_length_enters_operate(self):
        mem = self.make()
        t = telemetry(AHEAD_KIND="DOOR", AHEAD_DIST=40)
        self.assertEqual(dg.next_mode(dg.build_state(t, "EXPLORE", CFG, mem), t, mem, CFG), "OPERATE")

    def test_an_enemy_enters_fight_and_lingers(self):
        mem = self.make()
        t = telemetry(ENEMY_COUNT=1, ENEMY_DIST=200)
        self.assertEqual(dg.next_mode(dg.build_state(t, "EXPLORE", CFG, mem), t, mem, CFG), "FIGHT")
        mem.step()
        t2 = telemetry()
        self.assertEqual(dg.next_mode(dg.build_state(t2, "EXPLORE", CFG, mem), t2, mem, CFG), "FIGHT")

    def test_operate_gives_up_after_door_tries(self):
        mem = self.make()
        t = telemetry(AHEAD_KIND="DOOR", AHEAD_DIST=40)
        s = dg.build_state(t, "EXPLORE", CFG, mem)
        for _ in range(CFG["select"]["door_tries"]):
            self.assertTrue(dg.operate_controls(s, t, CFG, mem)["use"])
        self.assertFalse(dg.operate_controls(s, t, CFG, mem)["use"])

    def test_each_head_is_only_sent_the_blocks_it_inspects(self):
        # Text no question reads costs accuracy as well as tokens, and a criterion that names a block its
        # head is not given would be asking about something that is not there.
        t = telemetry()
        s = dg.build_state(t, "EXPLORE", CFG, self.make())
        sectors_only = dg.questions_for(s, CFG, "EXPLORE", ask_goal=False)
        self.assertEqual(set(dg.state_for(s, sectors_only)), {"sectors"})
        with_goal = dg.questions_for(s, CFG, "EXPLORE", ask_goal=True)
        self.assertEqual(set(dg.state_for(s, with_goal)), {"sectors", "player", "combat", "seen", "here"})
        for head, q in dg.rendered_questions(CFG):
            for path in dg._paths_in(q, set()):
                self.assertIn(path.split(".")[0], dg.HEAD_STATE[head],
                              "%s names %s, which it is not given" % (head, path))

    def test_jev_is_only_asked_where_there_is_a_judgment_to_make(self):
        mem = self.make()
        t = telemetry()
        s = dg.build_state(t, "EXPLORE", CFG, mem)
        heads = dg.questions_for(s, CFG, "EXPLORE", ask_goal=False)
        self.assertEqual(set(heads), {"s_%s" % d for d in dg.offered_sectors(s)})
        self.assertEqual(dg.questions_for(s, CFG, "OPERATE", ask_goal=False), {})


class Walking(unittest.TestCase):
    """The `advance` Noul is gone: once the direction is chosen, walking is a rule."""

    def test_walks_when_the_chosen_sector_is_straight_on(self):
        t = telemetry()
        s = dg.build_state(t, "EXPLORE", CFG)
        self.assertEqual(dg.travel_controls(s, "ahead")["move"], 1)

    def test_turns_without_walking_when_the_chosen_sector_is_to_the_side(self):
        t = telemetry()
        s = dg.build_state(t, "EXPLORE", CFG)
        c = dg.travel_controls(s, "left")
        self.assertEqual((c["move"], c["turn"]), (0, 90.0))

    def test_backs_out_of_a_corridor_rather_than_turning_around(self):
        t = telemetry(CLEAR_FWD=60, CLEAR_MAP_FWD=60, CLEAR_BACK=600)
        s = dg.build_state(t, "EXPLORE", CFG)
        self.assertEqual(dg.travel_controls(s, "behind")["move"], -1)


class GoalHasAnEffect(unittest.TestCase):
    """Issue 12: four graph versions edited goal criteria that no code path could act on."""

    def test_the_goal_weights_the_sector_that_holds_its_item(self):
        t = telemetry(HEALTH_ITEM_DIST=150, HEALTH_BEARING=90.0)
        s = dg.build_state(t, "RESTORE_HEALTH", CFG)
        self.assertEqual(s["sectors"]["left"]["item_here"], "health")
        self.assertEqual(dg.goal_bonus(s, "left", "RESTORE_HEALTH", CFG), CFG["select"]["goal_bonus"])
        self.assertEqual(dg.goal_bonus(s, "left", "EXPLORE", CFG), 0.0)

    def test_the_goal_can_change_the_pick(self):
        mem = dg.NavMemory(CFG)
        t = telemetry(HEALTH_ITEM_DIST=150, HEALTH_BEARING=90.0)
        s = dg.build_state(t, "RESTORE_HEALTH", CFG)
        flat = {"s_%s" % d: {"type": "score", "score": 2.0, "confidence": 0.9} for d in dg.offered_sectors(s)}
        flat["s_ahead"] = {"type": "score", "score": 2.3, "confidence": 0.9}
        self.assertEqual(dg.pick_sector(flat, s, CFG, mem, 0.0, "RESTORE_HEALTH", pos=(0.0, 0.0))[0], "left")
        self.assertEqual(dg.pick_sector(flat, s, CFG, dg.NavMemory(CFG), 0.0, "EXPLORE", pos=(0.0, 0.0))[0], "ahead")


class DoorsAndNovelty(unittest.TestCase):
    """Issue 9: a door used to overwrite the novelty reading, so the state could not say both."""

    def test_a_door_and_new_ground_are_two_fields(self):
        t = telemetry(DOOR_LEFT=5, NEW_LEFT=255)           # 5 * 8 = 40 units
        s = dg.build_state(t, "EXPLORE", CFG)
        self.assertEqual(s["sectors"]["left"]["door"], "point blank")
        self.assertEqual(s["sectors"]["left"]["ground"], "never explored")

    def test_an_old_log_without_the_door_channel_still_replays(self):
        t = telemetry()
        for _, nk, dk in dg.DIR_KEYS.values():
            del t[dk]
        t["NEW_LEFT"] = 210                                   # the legacy overload: a door at 80 units
        s = dg.build_state(t, "EXPLORE", CFG)
        self.assertEqual(s["sectors"]["left"]["door"], "close")
        self.assertEqual(s["sectors"]["left"]["ground"], "unknown")   # the novelty really was lost


if __name__ == "__main__":
    unittest.main()
