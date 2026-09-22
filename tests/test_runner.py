"""The bench's model of the flight link, pinned against the flight software.

The bench is only worth running if the state it hands the decision graph is the state Yamcs would have
handed it. Nothing enforces that at runtime -- the two paths never meet -- so it is enforced here, against
Doom.fpp itself: every channel the payload packs must arrive under the name the flight software gives it,
with the same type, and every enum must arrive as the name the ground sees rather than as an integer.

If this file fails after a change to the payload or to Doom.fpp, the bench numbers taken since that change
are not comparable with flight and the ledger rows that used them should say so.
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROLE = os.environ.get("DOOMSAT_ROLE")
sys.path.insert(0, os.path.join(ROOT, "research"))
sys.path.insert(0, os.path.join(ROOT, "ground"))

import runner                                   # noqa: E402  (this sets DOOMSAT_ROLE=pilot)

if _ROLE is None:
    os.environ.pop("DOOMSAT_ROLE", None)         # leave the process as we found it
else:
    os.environ["DOOMSAT_ROLE"] = _ROLE

FPP = open(os.path.join(ROOT, "flight", "Components", "Doom", "Doom.fpp"), encoding="utf-8").read()
PAYLOAD = open(os.path.join(ROOT, "payload", "doom_payload.py"), encoding="utf-8").read()

# Channels the flight software produces itself; the payload never packs them.
FLIGHT_ONLY = {"FRAMES_SENT", "CHUNKS_SENT", "FRAME_BYTES", "PAYLOAD_LINK", "CMDS_RECEIVED", "FRAME_CHUNK",
               "INTENT_ID", "WATCHDOG_TRIPS"}
# The candidate targets ride in their own block rather than as named fields, so they are checked by shape
# (below) rather than by name.
CAND_CHANNELS = {"CAND%d" % i for i in range(8)}


def fpp_channels():
    return [m.group(1) for m in re.finditer(r"telemetry (\w+):", FPP)]


def packed_keys():
    """The observation keys pack_status sends, in order."""
    body = PAYLOAD[PAYLOAD.index("def pack_status"):]
    body = body[:body.index("\n    # ")]
    return re.findall(r'o\["(\w+)"\]', body)


class TestTheBenchSpeaksTheSameLanguageAsFlight(unittest.TestCase):
    def test_every_packed_field_becomes_the_channel_the_flight_software_declares(self):
        declared = [c for c in fpp_channels() if c not in FLIGHT_ONLY and c not in CAND_CHANNELS]
        mapped = [runner.RENAME.get(k, k.upper()) for k in packed_keys()]
        self.assertEqual(sorted(mapped), sorted(declared),
                         "the bench's channel names have drifted from Doom.fpp")

    def test_no_channel_is_produced_twice(self):
        mapped = [runner.RENAME.get(k, k.upper()) for k in packed_keys()]
        self.assertEqual(len(mapped), len(set(mapped)), "two payload fields map to one channel")

    def test_the_candidate_block_is_the_same_shape_on_both_sides(self):
        """The one part of the status the flight software decodes by offset rather than by name, so a
        change in the payload's packing is silent until the numbers come out wrong."""
        cpp = open(os.path.join(ROOT, "flight", "Components", "Doom", "Doom.cpp"), encoding="utf-8").read()
        n = int(re.search(r"MAX_CANDIDATES = (\d+)", cpp).group(1))
        each = int(re.search(r"CAND_LEN = (\d+)", cpp).group(1))
        self.assertEqual(len(CAND_CHANNELS), n, "Doom.fpp declares a different number of candidate slots")
        self.assertEqual(int(re.search(r"MAX_CANDIDATES = (\d+)", PAYLOAD).group(1)), n)
        # kind U8 + x F32 + y F32 + pathUnits U16 + novelty U8 + flags U8 + threatClass U8 + threatCount U8
        self.assertEqual(each, 15)
        self.assertEqual(re.search(r'CAND_FMT = "(\w+)"', PAYLOAD).group(1), "BffHBBBB")
        core = int(re.search(r"STATUS_CORE_LEN = (\d+)", cpp).group(1))
        self.assertEqual(core, 120, "the pre-charter part of the status changed size")

    def test_the_intent_command_matches_the_payload_struct(self):
        cpp = open(os.path.join(ROOT, "flight", "Components", "Doom", "Doom.cpp"), encoding="utf-8").read()
        self.assertIn("U8 body[23];", cpp, "the flight side packs a different number of INTENT bytes")
        self.assertEqual(re.search(r'INTENT_FMT = "(\S+)"', PAYLOAD).group(1), "!HIBffBBBBBBH")
        import struct as _s
        self.assertEqual(_s.calcsize("!HIBffBBBBBBH"), 23)

    def test_the_enums_match_the_flight_software(self):
        for enum_name, table in (("AheadKind", runner.AHEAD_KIND), ("Weapon", runner.WEAPON), ("Goal", runner.GOAL)):
            block = FPP[FPP.index("enum %s" % enum_name):]
            block = block[:block.index("}")]
            names = [m.group(1) for m in re.finditer(r"^\s*(\w+) = (\d+)", block, re.M)]
            self.assertEqual(table, names, "%s has drifted from Doom.fpp" % enum_name)

    def test_an_observation_arrives_the_way_the_ground_reads_it(self):
        t = runner.telemetry_from({"x": 10.0, "y": -20.0, "angle": 90.0, "ahead_kind": 3, "weapon": 2,
                                   "goal": 0, "stuck": 0, "dead": 1, "explored": 5, "health_item": 128})
        self.assertEqual(t["POS_X"], 10.0)
        self.assertEqual(t["POS_Y"], -20.0)
        self.assertEqual(t["AHEAD_KIND"], "EXIT")
        self.assertEqual(t["WEAPON"], "SHOTGUN")
        self.assertEqual(t["GOAL"], "EXPLORE")
        self.assertEqual(t["EXPLORED_CELLS"], 5)
        self.assertEqual(t["HEALTH_ITEM_DIST"], 128)

    def test_a_false_bool_is_false_and_not_a_truthy_string(self):
        """F' bools arrive from Yamcs as the strings "True"/"False"; the pilot converts them, and so must
        the bench, or every `if stuck:` in the graph is true forever."""
        t = runner.telemetry_from({"stuck": 0, "dead": 0, "door_ahead": 1})
        self.assertIs(t["STUCK"], False)
        self.assertIs(t["DEAD"], False)
        self.assertIs(t["DOOR_AHEAD"], True)

    def test_an_unknown_enum_value_falls_back_rather_than_crashing(self):
        self.assertEqual(runner.telemetry_from({"ahead_kind": 99})["AHEAD_KIND"], "NOTHING")


class TestTheTwoTiersPlayTheSameGame(unittest.TestCase):
    """A bench result and a flight result are only comparable if the game is set up the same way.

    The flight launcher used to take the payload's own default skill (2) while the harness ran the bench
    at the skill in levels.yaml (3). Nothing would have failed; the two tiers would simply have been
    measuring different games, and charter 6.3 step 7 would have read the disagreement as a pilot result.
    """

    def setUp(self):
        import yaml
        self.conf = yaml.safe_load(open(os.path.join(ROOT, "research", "levels.yaml"), encoding="utf-8"))
        self.launcher = open(os.path.join(ROOT, "scripts", "wsl_run_flight.sh"), encoding="utf-8").read()

    def test_the_flight_launcher_starts_the_payload_at_the_harness_skill(self):
        skills = set(re.findall(r"--skill \$\{SKILL:-(\d+)\}", self.launcher))
        self.assertTrue(skills, "the flight launcher does not set --skill at all")
        self.assertEqual(skills, {str(self.conf["run"]["skill"])},
                         "the flight stack and the bench are playing at different difficulties")

    def test_every_payload_launch_in_the_script_sets_it(self):
        launches = self.launcher.count("doom_payload.py --fps")
        self.assertEqual(self.launcher.count("--skill ${SKILL:-"), launches,
                         "one of the payload launches does not set the skill")


class TestTheCodeBaseline(unittest.TestCase):
    """Charter phase 2 measures the executor with this in the loop, so a gait result is not a model result."""

    def setUp(self):
        import graph_config as gc
        self.cfg = gc.load()
        self.dec = runner.CodeDecider(self.cfg)

    def test_it_answers_exactly_the_questions_it_was_asked(self):
        state = {"sectors": {"ahead": {"space": "long", "ground": "never explored", "door": "none",
                                       "exit_here": "no", "key_here": "no", "item_here": "none",
                                       "hint_here": "no"}},
                 "player": {"health": "healthy"}, "combat": {"enemy_distance": "far"}}
        r = self.dec.ask(state, {"s_ahead": {}, "danger": {}, "goal": {}})
        self.assertEqual(set(r["answers"]), {"s_ahead", "danger", "goal"})
        self.assertIn("score", r["answers"]["s_ahead"])
        self.assertEqual(r["model"], "code")

    def test_it_prefers_open_unexplored_ground_to_a_walked_dead_end(self):
        good = {"space": "long", "ground": "never explored", "door": "none", "exit_here": "no",
                "key_here": "no", "item_here": "none", "hint_here": "no"}
        bad = {"space": "blocked", "ground": "walked before", "door": "none", "exit_here": "no",
               "key_here": "no", "item_here": "none", "hint_here": "no"}
        r = self.dec.ask({"sectors": {"a": good, "b": bad}}, {"s_a": {}, "s_b": {}})
        self.assertGreater(r["answers"]["s_a"]["score"], r["answers"]["s_b"]["score"])

    def test_it_costs_no_tokens(self):
        r = self.dec.ask({"sectors": {}}, {})
        self.assertEqual(r["usage"]["input_tokens"], 0)
        self.assertEqual(r["latency_ms"], 0)


class TestLatencyPlayback(unittest.TestCase):
    def test_a_missing_log_falls_back_to_the_built_in_default(self):
        self.assertEqual(runner.latencies("no/such/log.jsonl"), list(runner.DEFAULT_LATENCY_MS))

    def test_it_reads_a_real_log_and_adds_the_command_hop(self):
        import json
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "d.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"kind": "control", "latency_ms": 400, "cmd_ms": 45}) + "\n")
            f.write(json.dumps({"kind": "after_action"}) + "\n")
            f.write("\n")
        self.assertEqual(runner.latencies(p), [445.0])


if __name__ == "__main__":
    unittest.main()
