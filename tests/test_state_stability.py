"""The state jev reads has to hold still long enough to be worth committing to.

The first live run of the rewritten graph walked worse than the graph it replaced, and the cause was not
the model: on decision pairs where the state was byte-identical jev's scores moved a median of 0.01 rubric
levels, while 3.4 of 8 sectors changed their `space` word between consecutive half-second decisions. These
tests pin the three things that were done about it.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ground"))

import decision_graph as dg          # noqa: E402
import graph_config as gc            # noqa: E402

CFG = gc.validate(gc.DEFAULT)


class GoodNewsIsConfirmed(unittest.TestCase):
    """A better reading has to be seen `confirm_ticks` times; a worse one is believed at once."""

    def setUp(self):
        self.m = dg.SectorMemory(confirm=3)

    def test_the_first_reading_is_taken_as_is(self):
        self.assertEqual(self.m.settle(90.0, "space", "open"), "open")

    def test_a_better_reading_waits_for_confirmation(self):
        self.m.settle(90.0, "space", "tight")
        self.assertEqual(self.m.settle(90.0, "space", "long"), "tight")
        self.assertEqual(self.m.settle(90.0, "space", "long"), "tight")
        self.assertEqual(self.m.settle(90.0, "space", "long"), "long")

    def test_a_worse_reading_is_believed_at_once(self):
        self.m.settle(90.0, "space", "long")
        self.assertEqual(self.m.settle(90.0, "space", "blocked"), "blocked")

    def test_flicker_does_not_accumulate(self):
        self.m.settle(90.0, "space", "tight")
        for word in ("long", "open", "long", "open"):        # never the same twice running
            self.assertEqual(self.m.settle(90.0, "space", word), "tight")

    def test_it_follows_the_world_not_the_label(self):
        # the ray that was "left" at heading 0 is "ahead" at heading 90: same world direction, same slot
        self.m.settle(dg.world_bearing(0.0, "left"), "ground", "walked before")
        self.assertEqual(self.m.settle(dg.world_bearing(90.0, "ahead"), "ground", "never explored"),
                         "walked before")

    def test_a_different_world_direction_gets_its_own_slot(self):
        self.m.settle(0.0, "ground", "walked before")
        self.assertEqual(self.m.settle(180.0, "ground", "never explored"), "never explored")

    def test_unknown_passes_straight_through(self):
        self.m.settle(0.0, "space", "long")
        self.assertEqual(self.m.settle(0.0, "space", dg.UNKNOWN), dg.UNKNOWN)


class TheRubricHasResolution(unittest.TestCase):
    """Four levels put almost everything early in a level into the top one, and tied the exit with any
    fresh corridor. The rule and the rubric have to stay in step, level for level."""

    def sector(self, **over):
        s = {"space": "open", "ground": "walked before", "door": "none", "exit_here": "no",
             "key_here": "no", "item_here": "none", "hint_here": "no", "tried_recently": "no"}
        s.update(over)
        return s

    def test_the_exit_outranks_any_unexplored_ground(self):
        exit_there = dg.rule_score(self.sector(exit_here="yes"))
        unexplored = dg.rule_score(self.sector(ground="never explored", space="long"))
        self.assertGreater(exit_there, unexplored)

    def test_unexplored_ground_is_split_by_how_much_room_it_has(self):
        self.assertGreater(dg.rule_score(self.sector(ground="never explored", space="long")),
                           dg.rule_score(self.sector(ground="never explored", space="tight")))

    def test_the_ordering_runs_all_the_way_down_to_a_dead_end(self):
        ranked = [self.sector(exit_here="yes"),
                  self.sector(ground="never explored", space="long"),
                  self.sector(door="close"),
                  self.sector(ground="never explored", space="tight"),
                  self.sector(ground="new"),
                  self.sector(hint_here="yes"),
                  self.sector(ground="partly walked", space="open"),
                  self.sector(ground="walked before", space="open"),
                  self.sector(ground="walked before", space="tight")]
        scores = [dg.rule_score(s) for s in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True), scores)
        self.assertEqual(len(set(scores)), len(scores), "levels must be distinct, not clustered")

    def test_the_rule_spans_the_rubric(self):
        levels = dg.levels_of(CFG)
        self.assertEqual(levels, dg.RULE_LEVELS)
        self.assertAlmostEqual(dg.rule_score(self.sector(exit_here="yes"), levels), levels - 1)
        self.assertAlmostEqual(dg.rule_score(self.sector(ground="walked before", space="tight")), 0.0)


class ApproachIsAMode(unittest.TestCase):
    """It used to score sectors like EXPLORE, and so turned away from the door it was approaching."""

    def telemetry(self, **over):
        t = {"ANGLE": 0.0, "POS_X": 0.0, "POS_Y": 0.0, "HEALTH": 100, "ARMOR": 0, "SHELLS": 0,
             "BULLETS": 50, "WEAPON": "PISTOL", "OWN_SHOTGUN": False, "ENEMY_COUNT": 0,
             "ENEMY_BEARING": 0.0, "ENEMY_DIST": 0, "AHEAD_KIND": "NOTHING", "AHEAD_DIST": 0,
             "STUCK": False, "LEVEL": 1, "KEYS": 0, "EXIT_DIST": 0, "KEY_DIST": 0,
             "HEALTH_ITEM_DIST": 0, "AMMO_ITEM_DIST": 0, "ARMOR_ITEM_DIST": 0,
             "HINT_ACTIVE": False, "HINT_REL": 0, "CLEAR_MAP_FWD": 400}
        for ck, nk, dk in dg.DIR_KEYS.values():
            t[ck], t[nk], t[dk] = 400, 255, 0
        t.update(over)
        return t

    def test_jev_is_not_asked_to_pick_a_direction_in_approach(self):
        self.assertNotIn("APPROACH", dg.JUDGED_MODES)

    def test_it_steers_at_the_door(self):
        t = self.telemetry(DOOR_LEFT=8)                       # a door 64 units to the left
        mem = dg.NavMemory(CFG)
        state = dg.build_state(t, "EXPLORE", CFG, mem)
        self.assertEqual(dg.next_mode(state, t, mem, CFG), "APPROACH")
        self.assertEqual(dg.approach_target(state, t)[0], dg.SECTORS["left"])
        self.assertEqual(dg.control_args(state, t, CFG, mem, "APPROACH", {})["turn"], 90.0)

    def test_the_exit_beats_a_door(self):
        t = self.telemetry(DOOR_LEFT=8, EXIT_DIST=200, EXIT_BEARING=-30.0)
        state = dg.build_state(t, "EXPLORE", CFG, dg.NavMemory(CFG))
        bearing, what = dg.approach_target(state, t)
        self.assertEqual((round(bearing), what), (-30, "the exit"))

    def test_operate_gives_up_and_leaves(self):
        # Without this the pilot stood at one door for 1,172 consecutive decisions, commanding nothing.
        t = self.telemetry(AHEAD_KIND="DOOR", AHEAD_DIST=40)
        mem = dg.NavMemory(CFG)
        modes = []
        for _ in range(CFG["select"]["door_tries"] + 4):
            mem.step()
            state = dg.build_state(t, "EXPLORE", CFG, mem)
            mode = dg.next_mode(state, t, mem, CFG)
            modes.append(mode)
            dg.control_args(state, t, CFG, mem, mode, {})
        self.assertIn("OPERATE", modes)
        self.assertEqual(modes[-1], "EXPLORE", modes)

    def test_a_door_it_gave_up_on_is_not_re_entered_or_re_approached(self):
        t = self.telemetry(AHEAD_KIND="DOOR", AHEAD_DIST=40, DOOR_FWD=5)
        mem = dg.NavMemory(CFG)
        mem.give_up_here(t)
        state = dg.build_state(t, "EXPLORE", CFG, mem)
        self.assertNotEqual(dg.next_mode(state, t, mem, CFG), "OPERATE")
        self.assertIsNone(dg.approach_target(state, t, mem, CFG["select"]["door_retry_ticks"]))

    def test_it_is_worth_another_try_much_later(self):
        t = self.telemetry(AHEAD_KIND="DOOR", AHEAD_DIST=40)
        mem = dg.NavMemory(CFG)
        mem.give_up_here(t)
        for _ in range(CFG["select"]["door_retry_ticks"] + 1):
            mem.step()
        state = dg.build_state(t, "EXPLORE", CFG, mem)
        self.assertEqual(dg.next_mode(state, t, mem, CFG), "OPERATE")

    def test_it_gives_up_on_a_door_it_cannot_reach(self):
        t = self.telemetry(DOOR_LEFT=8)
        mem = dg.NavMemory(CFG)
        for _ in range(CFG["select"]["approach_ticks"] + 1):
            mem.step()
            state = dg.build_state(t, "EXPLORE", CFG, mem)
            mode = dg.next_mode(state, t, mem, CFG)
        self.assertEqual(mode, "EXPLORE")


class AFightNeedsAThreat(unittest.TestCase):
    """The pilot spent 211 consecutive decisions in FIGHT staring at an enemy 2,139 units away,
    commanding move 0, turn 0, fire 0, because the mode triggered on bare visibility."""

    def telemetry(self, **over):
        t = {"ANGLE": 0.0, "POS_X": 0.0, "POS_Y": 0.0, "HEALTH": 100, "ARMOR": 0, "SHELLS": 0,
             "BULLETS": 50, "WEAPON": "PISTOL", "OWN_SHOTGUN": False, "ENEMY_COUNT": 0,
             "ENEMY_BEARING": 0.0, "ENEMY_DIST": 0, "AHEAD_KIND": "NOTHING", "AHEAD_DIST": 0,
             "STUCK": False, "LEVEL": 1, "KEYS": 0, "EXIT_DIST": 0, "KEY_DIST": 0,
             "HEALTH_ITEM_DIST": 0, "AMMO_ITEM_DIST": 0, "ARMOR_ITEM_DIST": 0,
             "HINT_ACTIVE": False, "HINT_REL": 0, "CLEAR_MAP_FWD": 400}
        for ck, nk, dk in dg.DIR_KEYS.values():
            t[ck], t[nk], t[dk] = 400, 255, 0
        t.update(over)
        return t

    def mode_for(self, **over):
        t = self.telemetry(**over)
        mem = dg.NavMemory(CFG)
        return dg.next_mode(dg.build_state(t, "EXPLORE", CFG, mem), t, mem, CFG), t

    def test_an_enemy_across_the_level_is_not_a_fight(self):
        mode, _ = self.mode_for(ENEMY_COUNT=1, ENEMY_DIST=2139)
        self.assertEqual(mode, "EXPLORE")

    def test_an_enemy_within_range_is(self):
        mode, _ = self.mode_for(ENEMY_COUNT=1, ENEMY_DIST=200)
        self.assertEqual(mode, "FIGHT")

    def test_any_enemy_is_a_fight_once_health_is_down(self):
        mode, _ = self.mode_for(ENEMY_COUNT=1, ENEMY_DIST=2139, HEALTH=20)
        self.assertEqual(mode, "FIGHT")

    def test_the_danger_head_is_not_asked_about_scenery(self):
        t = self.telemetry(ENEMY_COUNT=1, ENEMY_DIST=2139)
        state = dg.build_state(t, "EXPLORE", CFG, dg.NavMemory(CFG))
        threat = dg.threatened(state, t, CFG)
        self.assertFalse(threat)
        self.assertNotIn("danger", dg.questions_for(state, CFG, "EXPLORE", threat=threat))

    def test_it_still_shoots_what_lines_up_while_exploring(self):
        t = self.telemetry(ENEMY_COUNT=1, ENEMY_DIST=300, ENEMY_BEARING=0.0)
        mem = dg.NavMemory(CFG)
        state = dg.build_state(t, "EXPLORE", CFG, mem)
        self.assertEqual(state["combat"]["enemy_in_crosshair"], "yes")
        self.assertTrue(dg.control_args(state, t, CFG, mem, "EXPLORE", {}, pick="ahead")["fire"])


class ItNoticesWhenItHasGoneNowhere(unittest.TestCase):
    """The payload reports STUCK only once a motion command has been held without progress, and the reflex
    layer refuses to walk into what the map calls a wall. A pilot that believes it is walled in therefore
    commands nothing, never pushes, and is never told it is stuck: it sat at one position, with
    STUCK false, for 553 consecutive decisions."""

    def walled_in(self):
        t = {"ANGLE": 0.0, "POS_X": 1126.0, "POS_Y": -2897.0, "HEALTH": 100, "ARMOR": 0, "SHELLS": 0,
             "BULLETS": 50, "WEAPON": "PISTOL", "OWN_SHOTGUN": False, "ENEMY_COUNT": 0,
             "ENEMY_BEARING": 0.0, "ENEMY_DIST": 0, "AHEAD_KIND": "BARRIER", "AHEAD_DIST": 43,
             "STUCK": False, "LEVEL": 1, "KEYS": 0, "EXIT_DIST": 0, "KEY_DIST": 0,
             "HEALTH_ITEM_DIST": 0, "AMMO_ITEM_DIST": 0, "ARMOR_ITEM_DIST": 0,
             "HINT_ACTIVE": False, "HINT_REL": 0, "CLEAR_MAP_FWD": 43}
        for ck, nk, dk in dg.DIR_KEYS.values():
            t[ck], t[nk], t[dk] = 20, 0, 0          # every direction blocked, every sector walked before
        return t

    def test_standing_still_eventually_forces_recover(self):
        t = self.walled_in()
        mem = dg.NavMemory(CFG)
        modes = []
        for _ in range(CFG["select"]["idle_ticks"] * 2 + 3):
            mem.step()
            mem.note_position((t["POS_X"], t["POS_Y"]), window=CFG["select"]["idle_ticks"])
            state = dg.build_state(t, "EXPLORE", CFG, mem)
            modes.append(dg.next_mode(state, t, mem, CFG))
        self.assertEqual(modes[-1], "RECOVER", modes)
        self.assertFalse(t["STUCK"], "the payload never said stuck; the pilot worked it out itself")

    def test_recover_always_commands_motion(self):
        t = self.walled_in()
        mem = dg.NavMemory(CFG)
        c = dg.control_args(dg.build_state(t, "EXPLORE", CFG, mem), t, CFG, mem, "RECOVER", {})
        self.assertNotEqual((c["move"], c["strafe"], c["turn"]), (0, 0, 0.0))

    def test_the_wall_guard_stands_down_while_recovering(self):
        t = self.walled_in()
        mem = dg.NavMemory(CFG)
        state = dg.build_state(t, "EXPLORE", CFG, mem)
        self.assertEqual(dg.reflex({**dg.STOP, "move": 1}, state, t, CFG, mode="EXPLORE")["move"], 0)
        self.assertEqual(dg.reflex({**dg.STOP, "move": 1}, state, t, CFG, mode="RECOVER")["move"], 1)

    def test_moving_clears_the_idle_count(self):
        mem = dg.NavMemory(CFG)
        for _ in range(30):
            mem.step()
            mem.note_position((0.0, 0.0), window=CFG["select"]["idle_ticks"])
        self.assertGreaterEqual(mem.idle_ticks, CFG["select"]["idle_ticks"])
        for i in range(CFG["select"]["idle_ticks"]):
            mem.step()
            mem.note_position((100.0 * i, 0.0), window=CFG["select"]["idle_ticks"])
        self.assertEqual(mem.idle_ticks, 0)

    def test_drifting_a_few_units_a_tick_still_counts_as_idle(self):
        # the second freeze was not a freeze: the player crept a few units per decision for a thousand
        # decisions, which a "did it move since last time" test reads as movement
        mem = dg.NavMemory(CFG)
        for i in range(40):
            mem.step()
            mem.note_position((i * 3.0, 0.0), window=CFG["select"]["idle_ticks"])
        self.assertGreaterEqual(mem.idle_ticks, 1)


class TurningDoesNotMeanStopping(unittest.TestCase):
    def state(self, ahead="long"):
        return {"sectors": {d: {"space": ahead if d == "ahead" else "long", "ground": "new",
                                "door": "none"} for d in dg.SECTORS}}

    def test_a_small_correction_is_taken_while_walking(self):
        c = dg.travel_controls(self.state(), "ahead-left")
        self.assertEqual((c["move"], c["turn"]), (1, 45.0))

    def test_a_big_turn_still_stops_first(self):
        self.assertEqual(dg.travel_controls(self.state(), "left")["move"], 0)

    def test_it_does_not_arc_into_a_wall(self):
        self.assertEqual(dg.travel_controls(self.state(ahead="blocked"), "ahead-left")["move"], 0)

    def test_behind_means_a_full_half_turn(self):
        # clamped at 135 the player ended up facing sideways and needing another correction, which the
        # spin metric then counted
        self.assertEqual(dg.SECTORS["behind"], 180.0)
        self.assertGreaterEqual(CFG["thresholds"]["max_turn_deg"], 180.0)


if __name__ == "__main__":
    unittest.main()
