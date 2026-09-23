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
# t3: exact geometry is allowed as a SOURCE, and this is the one module permitted to touch it. The whole
# knowledge boundary for geometry lives in its `_admit` gate, so the check below reads this file rather
# than trusting that a switch is off.
SENSOR = "payload/seen_geometry.py"
GROUND = ["ground/decision_graph.py", "ground/graph_config.py", "ground/pilot.py", "ground/after_action.py",
          "ground/providers.py", "ground/metrics.py"]
KNOWLEDGE = ["knowledge/doom_rules.yaml"]
PILOT_SIDE = [PAYLOAD, SENSOR] + GROUND + KNOWLEDGE

# ViZDoom calls and console commands that hand over more than a player can see.
CHEATS = ["am_cheat", "iddt", "idclev", "idbehold", "idclip", "idkfa", "iddqd", "notarget", "god ",
          "AutomapMode.WHOLE", "AutomapMode.OBJECTS", "set_objects_info_enabled(True)",
          "get_available_game_variables_of_all", "viz_debug"]
# Reading the level file. Only the grader may do this, and only in its own process. The lump names are
# matched as string literals: `SECTORS` on its own is a perfectly innocent identifier (the ground code's
# eight directions are called that), while `"SECTORS"` is a lump being pulled out of a WAD.
#
# t3 narrows this to MAP lumps, as the brief asks. Texture and sprite graphics are assets the game ships
# and every level shares -- recognising an exit switch on screen means having a picture of one, and that
# picture comes from the IWAD like every other pixel the player sees. What stays forbidden is the part of
# the file that says what THIS level is shaped like.
WAD_READING = ['"LINEDEFS"', '"VERTEXES"', '"SIDEDEFS"', '"SECTORS"', '"THINGS"', "'LINEDEFS'", "'THINGS'",
               "'VERTEXES'", "'SECTORS'", "'SIDEDEFS'", '"NODES"', '"SEGS"', '"SSECTORS"', '"BLOCKMAP"',
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
    """2. No whole-level object table, no map lumps, and sector info only through the gate.

    Amended for t3. The brief of 23 September makes exact geometry a legitimate SOURCE, because colour
    cannot tell a doorway from a ledge and a sensor that cannot do that leaves the pilot pressing Use on
    light recesses. What it does not make legitimate is the pilot KNOWING the whole level, so the test
    moves from "is the switch off" to "where is the filter": `state.sectors` may be read in exactly one
    place, that place hands it straight to the sensor, and the sensor only releases a line the automap
    has already drawn (test 2b).
    """
    bad = []
    text = src.get(PAYLOAD) or ""
    for arg in re.findall(r"set_objects_info_enabled\(\s*(\w+)", text):
        if arg != "False":
            bad.append("set_objects_info_enabled(%s): the whole-level object table stays off" % arg)
    for attr in ("state.objects", ".get_objects(", ".get_sectors("):
        if attr in text:
            bad.append("%s reads %s" % (PAYLOAD, attr))
    reads = [ln.strip() for ln in text.splitlines()
             if "state.sectors" in ln and not ln.strip().startswith("#")]
    if len(reads) > 1:
        bad.append("%s reads state.sectors in %d places; it may do so in one" % (PAYLOAD, len(reads)))
    elif reads and not re.match(r"self\.geom\.observe\(state\.sectors[,)]", reads[0]):
        bad.append("%s reads state.sectors outside the sensor: %r" % (PAYLOAD, reads[0][:70]))
    for rel, body in src.items():
        if body is None:
            continue
        for token in WAD_READING:
            if token in body:
                bad.append("%s reads the level file (%r)" % (rel, token))
    return Finding("test_no_whole_level_info", not bad,
                   "; ".join(bad) or "no object table, no map lumps; sector info only via the sensor gate")


def test_geometry_seen_only(src):
    """2b. A line reaches the pilot only once the automap has drawn it.

    The brief's own words: every line in the world model must have automap pixels. That is a runtime
    property and `research/preflight.py` asserts it on the live payload; this is the source half, which
    is what catches the gate being removed rather than the gate being wrong.
    """
    text = src.get(SENSOR)
    if text is None:
        return Finding("test_geometry_seen_only", True, "no geometry sensor in this tree: nothing to gate")
    bad = []
    body = _method_body(text, "_admit")
    if body is None:
        bad.append("%s has no _admit: nothing is gating the lines" % SENSOR)
    else:
        joined = "\n".join(body)
        if "drawn_fraction" not in joined:
            bad.append("_admit does not consult drawn_fraction: lines are released unchecked")
        if 'self.reveal == "all"' not in joined:
            bad.append("_admit has no named ORACLE branch, so a diagnostic cannot be told from a run")
    if "def drawn_fraction" in text and "drawn = getattr(ex" not in text:
        bad.append("drawn_fraction does not read the automap record")
    # The one place the gate may be opened is the oracle, reached by a flag. Not a default in the payload.
    if re.search(r'reveal\s*=\s*"all"', src.get(PAYLOAD) or ""):
        bad.append("%s asks the sensor for reveal='all' directly; that belongs to the oracle" % PAYLOAD)
    return Finding("test_geometry_seen_only", not bad,
                   "; ".join(bad) or "geometry is released only where the automap has drawn it")


def test_oracle_inert(src, root=ROOT):
    """2c. The diagnostic ladder exists, and an honest run cannot wander into it.

    `payload/oracle.py` is deliberately dishonest -- it opens the level file and writes an exit into the
    map -- so the question is not whether it is allowed but whether it can happen by accident. It may
    only be imported inside the branch that the `--oracle` flag turns on, and that flag defaults to off.
    """
    text = src.get(PAYLOAD) or ""
    bad = []
    if not os.path.isfile(os.path.join(root, "payload", "oracle.py")):
        return Finding("test_oracle_inert", True, "no oracle in this tree")
    for i, line in enumerate(text.splitlines(), 1):
        if re.search(r"^\s*(import oracle|from oracle)", line):
            if not line.startswith("            "):
                bad.append("line %d imports the oracle outside the --oracle branch" % i)
    m = re.search(r'add_argument\("--oracle",\s*default="(\w+)"', text)
    if not m:
        bad.append("no --oracle flag: the ladder cannot be told from a run")
    elif m.group(1) != "off":
        bad.append("--oracle defaults to %r, so an ordinary run is a diagnostic" % m.group(1))
    return Finding("test_oracle_inert", not bad,
                   "; ".join(bad) or "the oracle is reachable only through --oracle, which is off by default")


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


CHECKS = (test_automap_normal, test_no_whole_level_info, test_geometry_seen_only, test_oracle_inert,
          test_memory_empty_at_level_start, test_no_level_identifiers, test_seen_only,
          test_grader_isolation)


def source_checks(src, root=ROOT):
    out = []
    for fn in CHECKS:
        out.append(fn(src, root) if fn in (test_grader_isolation, test_oracle_inert) else fn(src))
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
    # t3, and the canary the brief asks for by name: a line the automap never drew, reaching the world
    # model. If removing the gate does not fail the suite, the suite says nothing about geometry.
    ("the geometry gate opened, so unseen lines reach the pilot", SENSOR,
     'if self.reveal == "all" or self.drawn_fraction(rec) >= SEEN_FRACTION:',
     "if True:  # every line, drawn or not",
     "test_geometry_seen_only"),
    ("the pilot reading the sector table for itself", PAYLOAD,
     "self.geom.observe(state.sectors, x, y)", "self.every_line = list(state.sectors)",
     "test_no_whole_level_info"),
    ("the diagnostic ladder left switched on", PAYLOAD,
     'p.add_argument("--oracle", default="off"', 'p.add_argument("--oracle", default="L0"',
     "test_oracle_inert"),
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
