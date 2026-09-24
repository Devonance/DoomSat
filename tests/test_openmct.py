"""The Open MCT displays (docs/OPENMCT.md) are generated, documented, current, and honest about what they read.

No network, no game, no browser: the displays and the operator reference are rebuilt in memory and compared
with what is committed, the custom views are checked against the reference, and the ground feed and the replay
builder are run on made-up rows.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "ground"))

import build_openmct_displays as bod   # noqa: E402
import openmct_docs                     # noqa: E402
import ops_telemetry                    # noqa: E402

WEB = ROOT / "ground" / "openmct"
LIVE_SCREENS = ("00 ", "10 ", "20 ", "30 ", "40 ", "60 ")
NOT_PANELS = {"conditionSet", "conditionWidget", "comps", "telemetry.correlator"}
BINS = {"DoomSat Displays", "Conditions", "Derived telemetry", "Parts (duplicate into My Items to build new screens)"}


class Displays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b, cls.root, cls.params, cls.drift = bod.build_all("live")

    def test_committed_displays_are_current(self):
        committed = (WEB / "displays" / "doomsat-displays.json").read_text(encoding="utf-8")
        self.assertEqual(committed, bod.display_json(self.b, self.root),
                         "run: python tools/build_openmct_displays.py --doc")

    def test_reference_doc_is_current(self):
        committed = (ROOT / "docs" / "OPENMCT.md").read_text(encoding="utf-8")
        self.assertEqual(committed, openmct_docs.render(self.b, self.root, self.params, self.drift),
                         "run: python tools/build_openmct_displays.py --doc")

    def test_every_panel_has_a_note(self):
        missing = sorted(o["name"] for o in self.b.objects.values()
                         if o["type"] not in NOT_PANELS and o["name"] not in BINS
                         and o["name"] not in openmct_docs.NOTES)
        self.assertEqual(missing, [], "add a line to NOTES in tools/openmct_docs.py")

    def test_every_parameter_has_a_meaning(self):
        used = set(self.b.used) | set(openmct_docs.SECTOR_RADAR_INPUTS) | set(openmct_docs.CANDIDATE_BOARD_INPUTS)
        missing = sorted(q for q in used if not openmct_docs.describe(q, self.params))
        self.assertEqual(missing, [], "add a meaning to GLOSSARY in tools/openmct_docs.py")

    def test_every_reference_is_known(self):
        for o in self.b.objects.values():
            for c in o.get("composition", []):
                if c["namespace"] == "taxonomy" and not c["key"].startswith("yamcs."):
                    self.assertIn(c["key"].replace("~", "/"), self.params, o["name"])

    def test_custom_views_read_what_the_reference_says(self):
        src = (WEB / "doomsat" / "plugin.js").read_text(encoding="utf-8")
        documented = {q.rsplit("/", 1)[1].split(".")[0] for q in
                      openmct_docs.SECTOR_RADAR_INPUTS + openmct_docs.CANDIDATE_BOARD_INPUTS}
        channels = {q.rsplit("/", 1)[1] for q in self.params if q.startswith(openmct_docs.DOOM + "/")}
        read = set(re.findall(r"'([A-Z][A-Z0-9_]{2,})'", src)) & channels
        self.assertEqual(sorted(read - documented), [], "plugin.js reads channels docs/OPENMCT.md does not list")

    def test_nothing_from_the_wad_on_a_live_screen(self):
        objs = self.b.objects

        def subtree(key, seen):
            if key in seen or key not in objs:
                return seen
            seen.add(key)
            for c in objs[key].get("composition", []):
                if c["namespace"] == "":
                    subtree(c["key"], seen)
            return seen
        for c in objs[self.root]["composition"]:
            o = objs[c["key"]]
            if not o["name"].startswith(LIVE_SCREENS):
                continue
            text = json.dumps([objs[k] for k in subtree(c["key"], set())]).lower()
            self.assertNotIn("grader", text, o["name"])
            self.assertNotIn("image-view", text, o["name"])

    def test_commanding_is_off_unless_asked_for(self):
        self.assertIn("Boolean(options.commanding)", (WEB / "doomsat" / "plugin.js").read_text(encoding="utf-8"))
        self.assertIn("commanding = false", (WEB / "doomsat" / "common.js").read_text(encoding="utf-8"))
        self.assertIn("get('commanding') === 'on'", (WEB / "index.js").read_text(encoding="utf-8"))
        self.assertIn("commanding: false", (WEB / "replay.js").read_text(encoding="utf-8"))


class FakeProcessor:
    def __init__(self):
        self.values = {}

    def set_parameter_value(self, name, value, expires_in=None):
        self.values[name] = value


def row(mode="EXPLORE", tx=1.0, pick=0, **select):
    return {"t": 1.0, "kind": "control", "mode": mode, "pick": pick, "select": {"gap": 0.5, "confidence": 0.7, **select},
            "answers": {"g_t0": "4.00", "g_t1": "2.00"}, "control": {"mode": mode, "target_x": tx, "target_y": 0.0},
            "latency_ms": 450, "tel_age_ms": 60, "cmd_ms": 40, "graph_version": 3, "episode": 1}


class GroundFeed(unittest.TestCase):
    def test_decision_sources(self):
        self.assertEqual(ops_telemetry.decision_source(row()), "JEV")
        self.assertEqual(ops_telemetry.decision_source(row(fallback="unsure gap")), "UNSURE_BAND")
        self.assertEqual(ops_telemetry.decision_source(row(held=True)), "HELD")
        self.assertEqual(ops_telemetry.decision_source(dict(row(), cached=True)), "CACHED")
        self.assertEqual(ops_telemetry.decision_source(dict(row(), answers={})), "UNAVAILABLE")

    def test_jev_share_counts_intent_changes_not_decisions(self):
        proc = FakeProcessor()
        ops = ops_telemetry.OpsTelemetry(proc, every_s=0)
        for _ in range(5):
            ops.update(row(tx=1.0), [{"kind": "frontier"}])                    # one intent, held by jev
        ops.update(row(tx=2.0, fallback="unsure gap"), [{"kind": "door"}])      # a second, by the fallback
        self.assertAlmostEqual(proc.values["/DoomGround/JevShare"], 0.5)
        self.assertAlmostEqual(proc.values["/DoomGround/FallbackRate"], 1 / 6)
        self.assertEqual(proc.values["/DoomGround/PickKind"], "DOOR")
        self.assertEqual(proc.values["/DoomGround/DecisionAgeMs"], 550.0)

    def test_the_sector_pilot_word_is_not_a_slot(self):
        proc = FakeProcessor()
        ops_telemetry.OpsTelemetry(proc, every_s=0).update(row(pick="ahead"), [])
        self.assertEqual(proc.values["/DoomGround/PickSlot"], 255)
        self.assertEqual(proc.values["/DoomGround/PickKind"], "NONE")

    def test_everything_published_is_in_the_ground_xtce(self):
        proc = FakeProcessor()
        ops_telemetry.OpsTelemetry(proc, every_s=0).update(dict(row(), answers={"g_t0": "1", "engage": "x"}),
                                                           [{"kind": "exit"}])
        params, _ = bod.doomdict.load()
        self.assertEqual(sorted(n for n in proc.values if n not in params), [])


class Replay(unittest.TestCase):
    def test_a_pack_from_three_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "decisions.jsonl"
            rows = []
            for i, (hp, mode) in enumerate([(100, "EXPLORE"), (40, "FIGHT"), (20, "FIGHT")]):
                r = row(mode=mode, tx=float(i))
                r.update(t=1790000000 + i, tic=400 + 35 * i, kills=i, goal="EXPLORE", candidates=1,
                         cand_xy=[{"kind": "frontier", "x": 1.0, "y": 2.0}],
                         raw={"HEALTH": hp, "STUCK": False, "POS_X": float(i), "POS_Y": 0.0, "WEAPON": "PISTOL"})
                rows.append(json.dumps(r))
            log.write_text("\n".join(rows))
            subprocess.run([sys.executable, str(ROOT / "tools" / "build_openmct_replay.py"), "--log", str(log),
                            "--out", str(Path(tmp) / "pack"), "--name", "t", "--no-displays"],
                           check=True, capture_output=True)
            pack = json.loads((Path(tmp) / "pack" / "pack.json").read_text())
        meta = pack["meta"]
        self.assertEqual(meta["rows"], 3)
        self.assertFalse(set(meta["provenance"]["recorded"]) & set(meta["provenance"]["derived"]))
        self.assertIn("/DoomSat_DoomSat/DoomSat/doom/HEALTH", meta["provenance"]["recorded"])
        self.assertIn("/DoomGround/JevShare", meta["provenance"]["derived"])
        self.assertTrue(all(e[3].startswith("[derived]") for e in pack["events"]))
        self.assertTrue(any("HEALTH fell through 25" in e[3] for e in pack["events"]))
        self.assertEqual(len(pack["commands"]), 3)


if __name__ == "__main__":
    unittest.main()
