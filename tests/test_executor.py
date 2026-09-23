"""The onboard executor: what the player does between decisions. Charter 3.1.

Every freeze this project has had was a property of a sequence of tics, not of one tic, and every one of
them passed the unit suite and the replay gate on its way into a live run. So these tests drive sequences:
a hundred tics of an expiring intent, two hundred of a player that is not moving, a recovery that has to
keep pushing because the payload's stuck detector only learns about a wall by being pressed into it.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "payload"))

import executor as ex            # noqa: E402
import world_model as wm         # noqa: E402


class NoWorld:
    plan = None

    def clear_plan(self):
        self.plan = None


def obs(**kw):
    base = {"x": 0.0, "y": 0.0, "angle": 0.0, "clear_fwd": 400, "clear_fl": 400, "clear_fr": 400,
            "clear_back": 400, "enemies": [], "ahead_kind": "nothing", "ahead_dist": 0,
            "all_blocked": False, "expire_barriers": lambda: None, "has_ammo": True}
    base.update(kw)
    return base


def enemy(bearing, dist):
    return [(abs(bearing), bearing, dist, None)]


def settled(e, at=(0.0, 0.0)):
    """An executor that has already taken its panorama here, so a test can watch it move."""
    e.looked.append(at)
    return e


class TestTheIntentAndItsTimeToLive(unittest.TestCase):
    def setUp(self):
        self.e = settled(ex.Executor(NoWorld()))

    def intent(self, **kw):
        kw.setdefault("ttl_ms", 1000)
        it = ex.Intent(**kw)
        self.e.set_intent(it, now=0.0)
        return it

    def test_it_runs_toward_a_target(self):
        self.intent(target_x=1000.0, target_y=0.0, has_target=True)
        cmd = self.e.step(obs(), 0.1)
        self.assertEqual(cmd["move"], ex.RUN_DELTA)
        self.assertAlmostEqual(cmd["turn"], 0.0, places=6)

    def test_it_turns_toward_a_target_behind_it(self):
        self.intent(target_x=-1000.0, target_y=0.0, has_target=True)
        cmd = self.e.step(obs(), 0.1)
        self.assertAlmostEqual(abs(cmd["turn"]), ex.TURN_PER_TIC, places=6)
        self.assertEqual(cmd["move"], 0.0, "no running off at full speed while facing the wrong way")

    def test_it_walks_while_only_a_little_off_line(self):
        self.intent(target_x=1000.0, target_y=700.0, has_target=True)   # about 35 degrees
        cmd = self.e.step(obs(), 0.1)
        self.assertGreater(cmd["move"], 0.0)
        self.assertLess(cmd["move"], ex.RUN_DELTA)

    def test_an_intent_outlives_the_decision_that_made_it(self):
        """The whole point of charter 3.1: the player does not stand still waiting for the next answer."""
        self.intent(target_x=1000.0, target_y=0.0, has_target=True, ttl_ms=1500)
        for t in (0.1, 0.5, 1.0, 1.4):
            self.assertEqual(self.e.step(obs(), t)["move"], ex.RUN_DELTA, "stopped at t=%.1f" % t)

    def test_a_lapsed_intent_falls_back_to_safe_behaviour(self):
        self.intent(target_x=1000.0, target_y=0.0, has_target=True, ttl_ms=500)
        self.assertEqual(self.e.step(obs(), 2.0)["move"], 0.0)
        self.assertGreater(self.e.stats["safe_ticks"], 0)

    def test_safe_behaviour_faces_an_attacker_and_shoots_only_what_is_on_top_of_it(self):
        cmd = self.e.step(obs(enemies=enemy(30.0, 100.0)), 0.0)
        self.assertGreater(cmd["turn"], 0.0, "turn toward it")
        self.assertEqual(cmd["fire"], 0, "not lined up yet")
        cmd = self.e.step(obs(enemies=enemy(2.0, 100.0)), 0.0)
        self.assertEqual(cmd["fire"], 1)
        cmd = self.e.step(obs(enemies=enemy(2.0, 800.0)), 0.0)
        self.assertEqual(cmd["fire"], 0, "safe mode does not start fights at range")

    def test_an_answer_older_than_one_already_applied_is_dropped(self):
        self.e.set_intent(ex.Intent(intent_id=2, based_on_tic=200, mode="EXPLORE"), now=0.0)
        ok = self.e.set_intent(ex.Intent(intent_id=1, based_on_tic=100, mode="FIGHT"), now=0.1)
        self.assertFalse(ok)
        self.assertEqual(self.e.intent.intent_id, 2)
        self.assertEqual(self.e.stats["stale_dropped"], 1)

    def test_a_newer_answer_replaces_the_current_one(self):
        self.e.set_intent(ex.Intent(intent_id=1, based_on_tic=100), now=0.0)
        self.assertTrue(self.e.set_intent(ex.Intent(intent_id=2, based_on_tic=140), now=0.1))
        self.assertEqual(self.e.intent.intent_id, 2)


class TestLocalAvoidance(unittest.TestCase):
    """Sidestepping a doorframe is not a question worth half a second of latency."""

    def setUp(self):
        self.e = settled(ex.Executor(NoWorld()))
        self.e.set_intent(ex.Intent(target_x=1000.0, target_y=0.0, has_target=True, ttl_ms=5000), now=0.0)

    def test_it_steps_toward_the_freer_shoulder(self):
        left = self.e.step(obs(clear_fwd=40, clear_fl=300, clear_fr=50), 0.1)
        self.assertGreater(left["strafe"], 0.0)
        right = self.e.step(obs(clear_fwd=40, clear_fl=50, clear_fr=300), 0.1)
        self.assertLess(right["strafe"], 0.0)

    def test_it_slows_but_does_not_stop_when_something_is_close(self):
        cmd = self.e.step(obs(clear_fwd=40), 0.1)
        self.assertGreater(cmd["move"], 0.0, "stopping dead is what the stuck detector cannot see past")
        self.assertLess(cmd["move"], ex.RUN_DELTA)

    def test_it_does_not_sidestep_away_from_a_door_it_is_walking_into(self):
        cmd = self.e.step(obs(clear_fwd=40, ahead_kind="door", ahead_dist=40), 0.1)
        self.assertEqual(cmd["strafe"], 0.0)
        self.assertEqual(cmd["move"], ex.RUN_DELTA)


class TestFiringAndUsing(unittest.TestCase):
    def setUp(self):
        self.e = settled(ex.Executor(NoWorld()))

    def arm(self, **kw):
        kw.setdefault("ttl_ms", 5000)
        self.e.set_intent(ex.Intent(**kw), now=0.0)

    def test_it_shoots_what_is_in_the_crosshair_and_in_range(self):
        self.arm(target_x=100.0, has_target=True)
        self.assertEqual(self.e.step(obs(enemies=enemy(3.0, 300.0)), 0.1)["fire"], 1)
        self.assertEqual(self.e.step(obs(enemies=enemy(30.0, 300.0)), 0.1)["fire"], 0)
        self.assertEqual(self.e.step(obs(enemies=enemy(3.0, 5000.0)), 0.1)["fire"], 0)

    def test_it_does_not_fire_an_empty_weapon(self):
        self.arm(target_x=100.0, has_target=True)
        self.assertEqual(self.e.step(obs(enemies=enemy(3.0, 300.0), has_ammo=False), 0.1)["fire"], 0)

    def test_a_retreat_does_not_stop_to_shoot(self):
        self.arm(mode="RETREAT", stance="retreat", fire_policy=ex.FIRE_NONE)
        self.assertEqual(self.e.step(obs(enemies=enemy(1.0, 100.0)), 0.1)["fire"], 0)

    def test_use_is_pulsed_not_held(self):
        """Doom triggers Use on the press edge, so holding it opens one door and then nothing."""
        self.arm(mode="OPERATE", target_x=10.0, target_y=0.0, has_target=True, use_at_target=True)
        presses = [self.e.step(obs(ahead_kind="door", ahead_dist=40), 0.1 + i * 0.03)["use"]
                   for i in range(24)]
        self.assertGreater(sum(presses), 0, "it never pressed")
        self.assertLess(sum(presses), len(presses) / 2, "it is holding the button, not pressing it")

    def test_it_does_not_press_use_at_nothing(self):
        self.arm(mode="EXPLORE", target_x=1000.0, has_target=True, use_at_target=False)
        self.assertEqual(self.e.step(obs(), 0.1)["use"], 0)


class TestTheWatchdog(unittest.TestCase):
    """Charter phase 2: invariants that pull the player out of a freeze. Each is one of September's."""

    def setUp(self):
        self.e = settled(ex.Executor(NoWorld()))
        self.e.set_intent(ex.Intent(target_x=1000.0, has_target=True, ttl_ms=100000), now=0.0)

    def run_tics(self, n, **kw):
        out = []
        for i in range(n):
            out.append(self.e.step(obs(**kw), i / 35.0))
        return out

    def test_a_player_that_is_not_moving_is_pulled_out(self):
        self.run_tics(250)
        self.assertTrue(self.e.watchdog.trips, "four seconds without displacement went unnoticed")
        self.assertGreater(self.e.stats["recover_ticks"], 0)

    def test_a_player_that_is_moving_is_left_alone(self):
        for i in range(250):
            self.e.looked.append((i * 20.0, 0.0))     # not testing the panorama here
            self.e.step(obs(x=i * 20.0), i / 35.0)
        self.assertFalse(self.e.watchdog.trips, "it was making progress and got interrupted anyway")

    def test_every_direction_blocked_expires_the_barrier_marks(self):
        """Late in a run every sector reads blocked because the barrier marks never expire."""
        expired = []
        for i in range(200):
            self.e.looked.append((i * 20.0, 0.0))
            self.e.step(obs(x=i * 20.0, all_blocked=True, expire_barriers=lambda: expired.append(1)),
                        i / 35.0)
        self.assertTrue(expired, "nothing ever cleared the barriers")

    def test_recovery_always_commands_motion(self):
        """The payload's stuck detector learns about a wall by being pressed into it. A recovery that
        stands still deadlocks it -- 553 decisions in one spot with STUCK false, in September."""
        cmds = self.run_tics(250)
        recovering = [c for c in cmds if c["move"] != 0 or c["strafe"] != 0]
        self.assertTrue(recovering)
        for c in cmds[-10:]:
            self.assertTrue(c["move"] != 0 or c["strafe"] != 0 or c["turn"] != 0)

    def test_recovery_ends_and_normal_service_resumes(self):
        self.run_tics(250)
        for i in range(250, 500):
            self.e.step(obs(x=(i - 250) * 20.0), i / 35.0)
        self.assertFalse(self.e.watchdog.recovering(500 / 35.0))


class TestTheContractWithThePayload(unittest.TestCase):
    def test_the_executor_and_the_payload_agree_on_the_running_delta(self):
        src = open(os.path.join(ROOT, "payload", "doom_payload.py"), encoding="utf-8").read()
        import re
        m = re.search(r"RUN_FORWARD, RUN_STRAFE = (\d+), (\d+)", src)
        self.assertEqual(float(m.group(1)), ex.RUN_DELTA)
        self.assertEqual(float(m.group(2)), ex.STRAFE_DELTA)

    def test_running_is_the_engine_s_running_speed_and_not_a_guess(self):
        """payload/speed_probe.py: delta 50 reaches 507 units/s and the engine caps there; the 14 used
        before reached 141, so every speed measured before the charter had a ceiling of 28% of running."""
        self.assertEqual(ex.RUN_DELTA, 50.0)

    def test_the_modes_and_stances_match_the_flight_software(self):
        fpp = open(os.path.join(ROOT, "flight", "Components", "Doom", "Doom.fpp"), encoding="utf-8").read()
        import re
        for enum_name, table in (("IntentMode", ex.MODES), ("Stance", ex.STANCES)):
            block = fpp[fpp.index("enum %s" % enum_name):]
            block = block[:block.index("}")]
            names = [m.group(1) for m in re.finditer(r"^\s*(\w+) = \d+", block, re.M)]
            self.assertEqual([n.upper() for n in table], names, "%s has drifted" % enum_name)


if __name__ == "__main__":
    unittest.main()


class TestThePanorama(unittest.TestCase):
    """A rover takes a picture at the end of a drive. With a 90 degree field of view the automap only
    fills in where the player happens to be facing, and it fills in slowly; one turn on the spot when it
    reaches ground it has not stood near is worth more map than a minute of walking and looking forward.
    Code owns it: it is a sensing routine and it decides nothing about where to go."""

    def setUp(self):
        self.e = ex.Executor(NoWorld())
        self.e.set_intent(ex.Intent(target_x=1000.0, has_target=True, ttl_ms=100000), now=0.0)

    def test_it_looks_around_on_arriving_somewhere_new(self):
        cmd = self.e.step(obs(), 0.0)
        self.assertEqual(cmd["move"], 0.0)
        self.assertNotEqual(cmd["turn"], 0.0)
        self.assertEqual(self.e.looks, 1)

    def test_a_panorama_is_a_full_turn_and_then_it_gets_on_with_it(self):
        for i in range(int(ex.LOOK_SECONDS * 35) + 2):
            self.e.step(obs(), i / 35.0)
        turned = ex.TURN_PER_TIC * ex.LOOK_SECONDS * 35
        self.assertGreaterEqual(turned, 360.0, "the look is too short to see all the way round")
        self.assertGreater(self.e.step(obs(), 3.0)["move"], 0.0, "it never stopped looking")

    def test_it_does_not_look_twice_in_the_same_place(self):
        for i in range(120):
            self.e.step(obs(), i / 35.0)
        self.assertEqual(self.e.looks, 1)

    def test_it_looks_again_somewhere_else(self):
        for i in range(120):
            self.e.step(obs(), i / 35.0)
        for i in range(120):
            self.e.step(obs(x=2000.0, y=2000.0), 10.0 + i / 35.0)
        self.assertEqual(self.e.looks, 2)

    def test_it_does_not_stand_and_spin_in_front_of_a_monster(self):
        """A second and a half turning on the spot in front of something is a second and a half of free
        shots for it."""
        cmd = self.e.step(obs(enemies=enemy(20.0, 200.0)), 0.0)
        self.assertEqual(self.e.looks, 0)
        self.assertNotEqual(cmd["move"], 0.0)

    def test_the_look_is_shorter_than_the_watchdog_s_patience(self):
        self.assertLess(ex.LOOK_SECONDS, ex.Watchdog.STILL_SECONDS,
                        "the panorama would trip the freeze watchdog")
