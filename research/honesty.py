"""The seven honesty tests of charter 2.4, written once.

`tests/test_honesty.py` runs these on Windows with no game and no network; `research/preflight.py` runs
the same functions plus the live ones before every bench or flight run. One implementation, so the suite
that gates a run and the suite that gates a commit cannot drift apart.

The checks are deliberately source-level. A leak is a property of the code, not of one execution: the
payload that kept its map across `RESET_GAME` passed every runtime assertion anyone thought to write,
because nobody thought to assert on the second episode. Reading the source catches that class of thing
before it flies, and the canary (`CANARIES` below) proves the reading is not vacuous.

    python research/honesty.py            # report
    python research/honesty.py --canary   # also prove a planted leak is caught
"""
import os
import re
import sys
from collections import namedtuple

Finding = namedtuple("Finding", "test ok detail")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The code the pilot process actually runs. Everything else in the repo (tools/, research/, tests/) is
# developer-side: it may read the WAD, name levels and do whatever it likes, because it never flies.
PAYLOAD = "payload/doom_payload.py"
GROUND = ["ground/decision_graph.py", "ground/graph_config.py", "ground/pilot.py", "ground/after_action.py",
          "ground/providers.py", "ground/metrics.py"]
KNOWLEDGE = ["knowledge/doom_rules.yaml"]
PILOT_SIDE = [PAYLOAD] + GROUND + KNOWLEDGE

# ViZDoom calls and console commands that hand over more than a player can see.
CHEATS = ["am_cheat", "iddt", "idclev", "idbehold", "idclip", "idkfa", "iddqd", "notarget", "god ",
          "AutomapMode.WHOLE", "AutomapMode.OBJECTS", "set_objects_info_enabled(True)",
          "set_sectors_info_enabled(True)", "get_available_game_variables_of_all", "viz_debug"]
# Reading the level file. Only the grader may do this, and only in its own process. The lump names are
# matched as string literals: `SECTORS` on its own is a perfectly innocent identifier (the ground code's
# eight directions are called that), while `"SECTORS"` is a lump being pulled out of a WAD.
WAD_READING = ['"LINEDEFS"', '"VERTEXES"', '"SIDEDEFS"', '"SECTORS"', '"THINGS"', "'LINEDEFS'", "'THINGS'",
               "wad_stats", "wad_map", "research.grader", "from grader", "import grader"]
LEVEL_NAME = re.compile(r"\bE\dM\d\b|\bMAP\d\d\b")
# Lines in the payload where a level name is a launch parameter, not knowledge: which map to start on and
# what the next one is called. Naming the successor of a map is knowledge about the engine's level order,
# which every player has; it is not knowledge about any level.
LAUNCH_CONTEXT = re.compile(r"add_argument|default=|set_doom_map|re\.fullmatch|return f\"|honesty: launch")


def read_sources(root=ROOT, paths=PILOT_SIDE):
    out = {}
    for rel in paths:
        p = os.path.join(root, rel.replace("/", os.sep))
        out[rel] = open(p, encoding="utf-8").read() if os.path.isfile(p) else None
    return out


def _method_body(text, name):
    """The lines of `def name(...)` at class level, without the signature."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"\s*def %s\s*\(" % re.escape(name), line):
            indent = len(line) - len(line.lstrip())
            body = []
            for nxt in lines[i + 1:]:
                if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                    break
                body.append(nxt)
            return body
    return None


# ---------------------------------------------------------------- the seven checks
def test_automap_normal(src):
    """1. The automap shows only what the player has walked past, and no cheat is enabled."""
    text = src.get(PAYLOAD)
    if text is None:
        return Finding("test_automap_normal", False, "%s is missing" % PAYLOAD)
    bad = []
    modes = re.findall(r"set_automap_mode\(\s*vzd\.AutomapMode\.(\w+)", text)
    if modes != ["NORMAL"]:
        bad.append("automap mode is %s, must be exactly ['NORMAL']" % (modes or "never set"))
    for rel, body in src.items():
        for cheat in CHEATS:
            if body and cheat in body:
                bad.append("%s contains %r" % (rel, cheat))
    return Finding("test_automap_normal", not bad, "; ".join(bad) or "automap NORMAL, no cheat CVAR or command")


def test_no_whole_level_info(src):
    """2. No whole-level object or sector tables, and no pilot-side code opens the WAD."""
    bad = []
    text = src.get(PAYLOAD) or ""
    for call in ("set_objects_info_enabled", "set_sectors_info_enabled"):
        for arg in re.findall(re.escape(call) + r"\(\s*(\w+)", text):
            if arg != "False":
                bad.append("%s(%s)" % (call, arg))
    for attr in ("state.objects", "state.sectors", ".get_objects(", ".get_sectors("):
        if attr in text:
            bad.append("%s reads %s" % (PAYLOAD, attr))
    for rel, body in src.items():
        if body is None:
            continue
        for token in WAD_READING:
            if token in body:
                bad.append("%s reads the level file (%r)" % (rel, token))
    return Finding("test_no_whole_level_info", not bad,
                   "; ".join(bad) or "objects/sectors info off, no pilot-side WAD reading")


def test_memory_empty_at_level_start(src):
    """3. Every episode builds a new world model. Charter 2.2: no map survives an attempt."""
    text = src.get(PAYLOAD)
    body = _method_body(text, "new_episode") if text else None
    if body is None:
        return Finding("test_memory_empty_at_level_start", False, "no Payload.new_episode found")
    builds = [ln for ln in body if "self.explorer = Explorer(" in ln]
    if not builds:
        return Finding("test_memory_empty_at_level_start", False, "new_episode never builds a fresh Explorer")
    # Unconditional means at the method's own indentation: not inside an `if map changed` branch.
    top = min(len(ln) - len(ln.lstrip()) for ln in body if ln.strip())
    nested = [ln for ln in builds if len(ln) - len(ln.lstrip()) > top]
    if nested:
        return Finding("test_memory_empty_at_level_start", False,
                       "the Explorer is rebuilt conditionally, so a retry can inherit a map: %r" % nested[0].strip())
    if len(builds) > 1:
        return Finding("test_memory_empty_at_level_start", False, "more than one Explorer build in new_episode")
    wiped = [w for w in ("self.door_presses", "self.positions.clear()") if not any(w in ln for ln in body)]
    if wiped:
        return Finding("test_memory_empty_at_level_start", False, "new_episode does not clear %s" % ", ".join(wiped))
    return Finding("test_memory_empty_at_level_start", True,
                   "new_episode rebuilds the world model unconditionally and clears the door and motion history")


def test_no_level_identifiers(src):
    """4. Nothing the pilot runs may branch on which level it is."""
    bad = []
    for rel in GROUND + KNOWLEDGE:
        for i, line in enumerate(( src.get(rel) or "").splitlines(), 1):
            if LEVEL_NAME.search(line):
                bad.append("%s:%d %s" % (rel, i, line.strip()[:70]))
    for i, line in enumerate((src.get(PAYLOAD) or "").splitlines(), 1):
        if LEVEL_NAME.search(line) and not LAUNCH_CONTEXT.search(line):
            bad.append("%s:%d %s" % (PAYLOAD, i, line.strip()[:70]))
    return Finding("test_no_level_identifiers", not bad,
                   "; ".join(bad) or "no level names outside launch parameters, no sector or coordinate tables")


def test_seen_only(src):
    """5. Everything remembered was sensed this attempt, and carries when it was sensed."""
    text = src.get(PAYLOAD) or ""
    bad = []
    body = _method_body(text, "remember_items")
    if body is None or not any('"seen"' in ln for ln in body):
        bad.append("remember_items does not stamp every object with when it was seen")
    if "labels" not in (text[:text.find("def remember_items") + 400] if "def remember_items" in text else ""):
        bad.append("remember_items is not fed from the labels buffer")
    # The only writer of map classes is stamp(), which reads the rendered automap. Anything else writing an
    # EXIT or a locked door into the raster would be inventing a line that was never drawn.
    inside_stamp = set()
    if "def stamp(" in text:
        lines = text.splitlines()
        start = next(i for i, ln in enumerate(lines) if re.match(r"\s*def stamp\s*\(", ln))
        indent = len(lines[start]) - len(lines[start].lstrip())
        for j in range(start + 1, len(lines)):
            if lines[j].strip() and len(lines[j]) - len(lines[j].lstrip()) <= indent:
                break
            inside_stamp.add(j + 1)
    for name in ("EXIT", "LOCK_RED", "LOCK_BLUE", "LOCK_YELLOW", "LOCKED"):
        for i, line in enumerate(text.splitlines(), 1):
            if i not in inside_stamp and re.search(r"raster\[[^]]*\]\s*=\s*%s\b" % name, line):
                bad.append("line %d writes %s into the raster outside the automap stamp" % (i, name))
    return Finding("test_seen_only", not bad,
                   "; ".join(bad) or "objects come from the labels buffer with a seen time; map classes only from the automap")


def test_grader_isolation(src, root=ROOT):
    """6. The pilot process cannot import the grader and never reads its output."""
    bad = []
    for rel, body in src.items():
        if body and re.search(r"^\s*(from|import)\s+.*grader", body, re.M):
            bad.append("%s imports the grader" % rel)
        if body and "research/out" in body:
            bad.append("%s reads the grader's output directory" % rel)
    guard = os.path.join(root, "research", "grader", "__init__.py")
    if not os.path.isfile(guard):
        bad.append("research/grader/__init__.py is missing")
    elif "DOOMSAT_ROLE" not in open(guard, encoding="utf-8").read():
        bad.append("the grader package does not refuse to load in a pilot process")
    return Finding("test_grader_isolation", not bad,
                   "; ".join(bad) or "no pilot-side import of the grader; the grader refuses to load under DOOMSAT_ROLE=pilot")


CHECKS = (test_automap_normal, test_no_whole_level_info, test_memory_empty_at_level_start,
          test_no_level_identifiers, test_seen_only, test_grader_isolation)


def source_checks(src, root=ROOT):
    out = []
    for fn in CHECKS:
        out.append(fn(src, root) if fn is test_grader_isolation else fn(src))
    return out


def run(root=ROOT):
    return source_checks(read_sources(root), root)


# ---------------------------------------------------------------- 7. the canary
# Each entry plants a leak that a real mistake would look like. If the checker still passes, the checker
# is broken and says nothing about the runs it has been gating.
CANARIES = [
    ("automap set to WHOLE", PAYLOAD,
     "g.set_automap_mode(vzd.AutomapMode.NORMAL)", "g.set_automap_mode(vzd.AutomapMode.WHOLE)",
     "test_automap_normal"),
    ("the whole-level object table switched on", PAYLOAD,
     "g.set_labels_buffer_enabled(True)", "g.set_labels_buffer_enabled(True)\n        g.set_objects_info_enabled(True)",
     "test_no_whole_level_info"),
    ("the map kept for a second attempt at the same level", PAYLOAD,
     "        self.explorer = Explorer(", "        if self.explorer_map != self.map:\n            self.explorer = Explorer(",
     "test_memory_empty_at_level_start"),
    ("the graph told which level it is on", "ground/decision_graph.py",
     "JUDGED_MODES = ", "LEVEL_HINTS = {\"E1M1\": \"go north\"}\nJUDGED_MODES = ",
     "test_no_level_identifiers"),
    ("an exit invented into the map instead of seen on it", PAYLOAD,
     "    def sweep(self, x, y, angle, depth_row):",
     "    def cheat(self, ix, iy):\n        self.raster[iy, ix] = EXIT\n\n    def sweep(self, x, y, angle, depth_row):",
     "test_seen_only"),
    ("the pilot importing the grader", "ground/pilot.py",
     "import after_action", "import after_action\nfrom research.grader import score",
     "test_grader_isolation"),
]


def run_canaries(root=ROOT):
    """Apply each planted leak to a copy of the sources and report whether the named check caught it."""
    out = []
    for name, rel, find, replace, expect in CANARIES:
        src = read_sources(root)
        if src.get(rel) is None or find not in src[rel]:
            out.append(Finding("canary: " + name, False, "could not plant it: %r not found in %s" % (find, rel)))
            continue
        src[rel] = src[rel].replace(find, replace, 1)
        caught = [f for f in source_checks(src, root) if not f.ok]
        names = [f.test for f in caught]
        out.append(Finding("canary: " + name, expect in names,
                           "caught by %s" % ", ".join(names) if caught else "NOT CAUGHT by any check"))
    return out


def main():
    root = ROOT
    findings = run(root)
    if "--canary" in sys.argv:
        findings += run_canaries(root)
    width = max(len(f.test) for f in findings)
    for f in findings:
        print("%-4s %-*s  %s" % ("ok" if f.ok else "FAIL", width, f.test, f.detail))
    bad = [f for f in findings if not f.ok]
    print("\n%d checks, %d failed" % (len(findings), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
