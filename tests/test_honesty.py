"""Charter 2.4: the honesty suite, and the canary that proves the suite is not vacuous.

These run in the ordinary test suite, on Windows, with no game and no network, because a leak is a
property of the code and not of one execution. The payload that kept its map across RESET_GAME passed
every runtime assertion anyone had thought to write.
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))

import honesty      # noqa: E402


class TestTheRepoIsHonest(unittest.TestCase):
    def test_every_check_passes(self):
        for f in honesty.run(ROOT):
            self.assertTrue(f.ok, "%s: %s" % (f.test, f.detail))

    def test_every_check_ran(self):
        """Charter 2.4's six, plus the two t3 added for geometry and for the oracle ladder."""
        names = [f.test for f in honesty.run(ROOT)]
        self.assertEqual(len(names), len(honesty.CHECKS), names)
        self.assertIn("test_geometry_seen_only", names)
        self.assertIn("test_oracle_inert", names)
        self.assertEqual(len(set(names)), len(honesty.CHECKS), "a check is reported twice: %s" % names)

    def test_the_automap_is_normal_and_no_cheat_is_set(self):
        text = honesty.read_sources(ROOT)[honesty.PAYLOAD]
        self.assertIn("set_automap_mode(vzd.AutomapMode.NORMAL)", text)
        for cheat in ("AutomapMode.WHOLE", "AutomapMode.OBJECTS", "am_cheat", "iddt"):
            self.assertNotIn(cheat, text)

    def test_the_world_model_is_rebuilt_every_episode(self):
        body = honesty._method_body(honesty.read_sources(ROOT)[honesty.PAYLOAD], "new_episode")
        builds = [ln for ln in body if "self.explorer = Explorer(" in ln]
        self.assertEqual(len(builds), 1, "expected exactly one unconditional rebuild, got %r" % builds)
        top = min(len(ln) - len(ln.lstrip()) for ln in body if ln.strip())
        self.assertEqual(len(builds[0]) - len(builds[0].lstrip()), top,
                         "the rebuild is nested, so some path can inherit a map")

    def test_the_ground_code_never_names_a_level(self):
        src = honesty.read_sources(ROOT)
        for rel in honesty.GROUND + honesty.KNOWLEDGE:
            self.assertIsNotNone(src[rel], "%s is missing" % rel)
            self.assertIsNone(honesty.LEVEL_NAME.search(src[rel]), "%s names a level" % rel)


class TestTheCanary(unittest.TestCase):
    """Charter 2.4 item 7. If a planted leak does not fail the suite, the suite says nothing."""

    def test_every_planted_leak_is_caught_by_the_check_that_should_catch_it(self):
        results = honesty.run_canaries(ROOT)
        self.assertEqual(len(results), len(honesty.CANARIES))
        for f in results:
            self.assertTrue(f.ok, "%s -- %s" % (f.test, f.detail))

    def test_a_clean_tree_is_not_reported_as_a_leak(self):
        # the other half of the canary: the checks must not fire on everything
        self.assertTrue(all(f.ok for f in honesty.run(ROOT)))

    def test_the_checker_reads_the_text_it_is_given_not_the_disk(self):
        src = honesty.read_sources(ROOT)
        src[honesty.PAYLOAD] = src[honesty.PAYLOAD].replace(
            "g.set_automap_mode(vzd.AutomapMode.NORMAL)", "g.set_automap_mode(vzd.AutomapMode.WHOLE)", 1)
        failed = [f.test for f in honesty.source_checks(src, ROOT) if not f.ok]
        self.assertIn("test_automap_normal", failed)


class TestTheGraderCannotBeReachedFromAPilot(unittest.TestCase):
    def test_the_guard_is_in_the_package(self):
        guard = open(os.path.join(ROOT, "research", "grader", "__init__.py"), encoding="utf-8").read()
        self.assertIn("DOOMSAT_ROLE", guard)
        self.assertIn("raise ImportError", guard)

    def test_importing_the_grader_as_a_pilot_raises(self):
        import subprocess
        env = dict(os.environ, DOOMSAT_ROLE="pilot", PYTHONPATH=os.path.join(ROOT, "research"))
        r = subprocess.run([sys.executable, "-c", "import grader"], env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0, "the grader loaded inside a pilot process")
        self.assertIn("ImportError", r.stderr + r.stdout)

    def test_the_runner_declares_itself_a_pilot(self):
        text = open(os.path.join(ROOT, "research", "runner.py"), encoding="utf-8").read()
        before_imports = text[:text.index("import decision_graph")]
        self.assertIn('os.environ.setdefault("DOOMSAT_ROLE", "pilot")', before_imports,
                      "the runner must claim the pilot role before it imports anything else")


class TestTheKnowledgeFileIsRulesNotLevels(unittest.TestCase):
    def setUp(self):
        import yaml
        self.rules = yaml.safe_load(open(os.path.join(ROOT, "knowledge", "doom_rules.yaml"), encoding="utf-8"))

    def test_it_names_no_level_and_no_coordinate_table(self):
        text = open(os.path.join(ROOT, "knowledge", "doom_rules.yaml"), encoding="utf-8").read()
        self.assertIsNone(honesty.LEVEL_NAME.search(text))
        self.assertIsNone(re.search(r"\bx\s*:\s*-?\d{3,}", text), "a coordinate is level knowledge")

    def test_the_facts_a_decision_needs_are_there(self):
        self.assertEqual(self.rules["monsters"]["BaronOfHell"]["hp"], 1000)   # charter 3.5: E1M8
        self.assertEqual(self.rules["monsters"]["Zombieman"]["hp"], 20)
        self.assertIn("BaronOfHell", self.rules["boss_classes"])
        self.assertEqual(self.rules["ammo"]["shells"]["max"], 50)
        self.assertEqual(self.rules["weapons"]["RocketLauncher"]["slot"], 5)
        self.assertTrue(self.rules["weapons"]["RocketLauncher"]["splash"])

    def test_every_monster_the_payload_can_name_is_ranked(self):
        text = open(os.path.join(ROOT, "payload", "doom_payload.py"), encoding="utf-8").read()
        block = text[text.index("ENEMIES = {"):text.index("ITEM_KIND")]
        named = set(re.findall(r'"(\w+)"', block))
        missing = named - set(self.rules["monsters"])
        self.assertFalse(missing, "the payload can label these but the knowledge file does not rank them: %s" % missing)

    def test_every_pickup_the_payload_can_name_is_described(self):
        text = open(os.path.join(ROOT, "payload", "doom_payload.py"), encoding="utf-8").read()
        block = text[text.index("ITEM_KIND = {"):text.index("KEY_COLOUR")]
        named = set(re.findall(r'"(\w+)":', block))
        missing = named - set(self.rules["pickups"]) - set(self.rules["keys"]["things"])
        self.assertFalse(missing, "the payload can label these pickups but the knowledge file omits them: %s" % missing)


if __name__ == "__main__":
    unittest.main()
