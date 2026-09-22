"""One-off patch: eight directions in the state, a per-direction way head built from a template, command mapping."""
import ast
import json
import os
import shutil
import sys

p = "ground/decision_graph.py"
s = open(p, encoding="utf-8").read()


def rep(old, new):
    global s
    assert old in s, old[:80]
    s = s.replace(old, new, 1)


rep('''WAY_TURN = {"Ahead": 0.0, "Left": 90.0, "Right": -90.0, "Back": 0.0, "Turn around": 180.0}''',
    '''WAY_TURN = {"ahead": 0.0, "ahead-left": 45.0, "left": 90.0, "behind-left": 135.0, "behind": 180.0,
            "behind-right": -135.0, "right": -90.0, "ahead-right": -45.0}
DIR_KEYS = {"ahead": ("CLEAR_FWD", "NEW_FWD"), "ahead-left": ("CLEAR_AL", "NEW_AL"), "left": ("CLEAR_LEFT", "NEW_LEFT"),
            "behind-left": ("CLEAR_BL", "NEW_BL"), "behind": ("CLEAR_BACK", "NEW_BACK"), "behind-right": ("CLEAR_BR", "NEW_BR"),
            "right": ("CLEAR_RIGHT", "NEW_RIGHT"), "ahead-right": ("CLEAR_AR", "NEW_AR")}''')
rep('''    space = lambda c: "blocked" if c < th["blocked_units"] else "tight" if c < th["tight_units"] else "open" if c < 300 else "opens up far"''',
    '''    space = lambda c: "blocked" if c < th["blocked_units"] else "tight" if c < th["tight_units"] else "open" if c < 220 else "long (a passage or a big room)"''')
rep('''        "surroundings": {"ahead": ahead,
                         "left": {"space": space(t.get("CLEAR_LEFT", 999)), "ground": ground_words(t.get("NEW_LEFT", 100))},
                         "right": {"space": space(t.get("CLEAR_RIGHT", 999)), "ground": ground_words(t.get("NEW_RIGHT", 100))},
                         "behind": {"space": space(t.get("CLEAR_BACK", 999)), "ground": ground_words(t.get("NEW_BACK", 100))}},''',
    '''        "surroundings": {"ahead": ahead, **{d: {"space": space(t.get(ck, 999)), "ground": ground_words(t.get(nk, 100))}
                                            for d, (ck, nk) in DIR_KEYS.items() if d != "ahead"}},''')
rep('''    sur = s["surroundings"]
    ways = ["Ahead", "Left", "Right", "Back", "Turn around"]
    if sur["behind"]["space"] == "blocked":
        ways.remove("Back")
    heads = {"way": _question(cfg, "way", ways), "advance": _question(cfg, "advance"), "fire": _question(cfg, "fire"),
             "weapon": _question(cfg, "weapon")}''',
    '''    sur = s["surroundings"]
    ways = [d for d in WAY_TURN if sur[d]["space"] != "blocked"] or ["behind"]   # never offer a blocked direction
    heads = {"way": _way_question(cfg, sur, ways), "advance": _question(cfg, "advance"), "fire": _question(cfg, "fire"),
             "weapon": _question(cfg, "weapon")}''')
rep('''def goal_question(t, cfg):''', '''def _way_question(cfg, sur, ways):
    """The way head: one option per open direction, each described from the same template (System Two edits the template)."""
    spec = cfg["questions"]["way"]
    tpl = spec["criteria"]["direction"]
    crit = {}
    for d in ways:
        crit[d] = {k: (v.replace("{dir}", d) if isinstance(v, str) else [x.replace("{dir}", d) for x in v]) for k, v in tpl.items()}
        crit[d]["now"] = f"space {sur[d]['space']}, ground {sur[d]['ground']}"
    return {"type": "choice", "instructions": copy.deepcopy(spec["instructions"]), "criteria": crit}


def goal_question(t, cfg):''')
rep('''    turn = WAY_TURN.get(way, 0.0)
    move = 0
    if way == "Ahead":
        move = 1 if advance else 0
        if "turn" in a:   # fighting: aim at the enemy instead of steering
            turn = float(cfg["turn_deg"].get(a["turn"].get("choice", "Hold"), 0.0))
        elif t is not None:
            # keep the nose in the open: a small correction toward the freer side of the camera view
            fl, fr, fw = t.get("CLEAR_FL", 999), t.get("CLEAR_FR", 999), t.get("CLEAR_FWD", 999)
            if fw < 160 and abs(fl - fr) > 40:
                turn = 20.0 if fl > fr else -20.0
    elif way == "Back":
        move = -1''', '''    turn = WAY_TURN.get(way, 0.0)
    move = 0
    if way == "ahead":
        move = 1 if advance else 0
        if "turn" in a:   # fighting: aim at the enemy instead of steering
            turn = float(cfg["turn_deg"].get(a["turn"].get("choice", "Hold"), 0.0))
        elif t is not None:
            # keep the nose in the open: a small correction toward the freer side of the camera view
            fl, fr, fw = t.get("CLEAR_FL", 999), t.get("CLEAR_FR", 999), t.get("CLEAR_FWD", 999)
            if fw < 160 and abs(fl - fr) > 40:
                turn = 20.0 if fl > fr else -20.0
    elif way == "behind" and t is not None and t.get("CLEAR_BACK", 0) > t.get("CLEAR_FWD", 0):
        move, turn = -1, 0.0   # back out rather than turn when the way behind is open''')
rep('''    way = way_ans.get("choice", "Ahead")''', '''    way = way_ans.get("choice", "ahead")''')
rep('''    prev_ok = prev in probs and probs.get(prev, 0.0) >= 0.3 and not (prev == "Ahead" and not advance)''',
    '''    prev_ok = prev in probs and probs.get(prev, 0.0) >= 0.3 and not (prev == "ahead" and not advance)''')
open(p, "w", encoding="utf-8", newline="\n").write(s)
ast.parse(s)
print("decision_graph ok")

p = "ground/graph_config.py"
s = open(p, encoding="utf-8").read()
start = s.index('        "way": {')
end = s.index('        "advance": {')
WAY = '''        "way": {
            "type": "choice",
            "instructions": {
                "question": "Which of the offered directions should the player go now? Each option is a direction around the player, with what the map says there under `now`.",
                "inspect": "surroundings, seen.exit, seen.key, seen.ground_hint, stuck",
                "focus": "Prefer the direction of the exit, then a door, then long space with new ground, then open new ground. A walked-before direction only when nothing new is offered."},
            "criteria": {
                "direction": {"what": "go {dir}: best when its space is long or open and its ground is new, or the exit, a door, the key or ground_hint lies {dir}",
                              "not_for": "its space is tight, or its ground is walked before while another offered direction is long and new",
                              "examples": ["{dir}: space long, ground new", "exit {dir}"]}}},
'''
s = s[:start] + WAY + s[end:]
open(p, "w", encoding="utf-8", newline="\n").write(s)
ast.parse(s)
print("graph_config ok")

p = "ground/pilot.py"
s = open(p, encoding="utf-8").read()
rep('''                   "LEVEL_DONE", "EXPLORED_CELLS", "LEVEL", "KEYS", "HINT_ACTIVE", "HINT_REL",''',
    '''                   "LEVEL_DONE", "EXPLORED_CELLS", "LEVEL", "KEYS", "HINT_ACTIVE", "HINT_REL",
                   "CLEAR_AL", "CLEAR_AR", "CLEAR_BL", "CLEAR_BR", "NEW_AL", "NEW_AR", "NEW_BL", "NEW_BR",''')
rep('''RAW_KEYS = ("CLEAR_FWD", "CLEAR_LEFT", "CLEAR_RIGHT", "CLEAR_BACK", "NEW_FWD", "NEW_LEFT", "NEW_RIGHT", "NEW_BACK", "AHEAD_KIND",''',
    '''RAW_KEYS = ("CLEAR_FWD", "CLEAR_LEFT", "CLEAR_RIGHT", "CLEAR_BACK", "CLEAR_AL", "CLEAR_AR", "CLEAR_BL", "CLEAR_BR",
            "NEW_FWD", "NEW_LEFT", "NEW_RIGHT", "NEW_BACK", "NEW_AL", "NEW_AR", "NEW_BL", "NEW_BR", "AHEAD_KIND",''')
open(p, "w", encoding="utf-8", newline="\n").write(s)
ast.parse(s)
print("pilot ok")

if os.path.isdir("ground/graph"):
    shutil.rmtree("ground/graph")
sys.path.insert(0, "ground")
import graph_config as gc          # noqa: E402
import decision_graph as dg        # noqa: E402
cfg = gc.load()
t = {"HEALTH": 80, "CLEAR_FWD": 30, "CLEAR_MAP_FWD": 30, "CLEAR_LEFT": 300, "CLEAR_RIGHT": 20, "CLEAR_BACK": 200, "CLEAR_AL": 90,
     "CLEAR_AR": 400, "CLEAR_BL": 50, "CLEAR_BR": 100, "NEW_FWD": 10, "NEW_LEFT": 90, "NEW_RIGHT": 0, "NEW_BACK": 0, "NEW_AL": 50,
     "NEW_AR": 100, "NEW_BL": 0, "NEW_BR": 20, "AHEAD_KIND": "WALL", "AHEAD_DIST": 30, "EXIT_DIST": 0, "KEY_DIST": 0, "STUCK": False,
     "LEVEL": 1, "KEYS": 0, "HINT_ACTIVE": False, "ENEMY_COUNT": 0, "WEAPON": "SHOTGUN", "SHELLS": 4, "BULLETS": 30}
qs = dg.control_questions(t, "EXPLORE", cfg)
print("way options:", list(qs["way"]["criteria"]))
print(json.dumps(qs["way"]["criteria"]["ahead-right"]))
print(dg.control_args({"way": {"choice": "ahead-right", "probabilities": {"ahead-right": 0.9}}, "advance": {"noul": 0.2}}, cfg, t, {}))
