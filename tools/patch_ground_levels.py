"""One-off patch: teach the ground software about levels, keys and the navigator mode (run from the repo root)."""
import os
import shutil
import subprocess
import sys


def edit(path, pairs):
    s = open(path, encoding="utf-8").read()
    for old, new in pairs:
        if old not in s:
            raise SystemExit(f"{path}: pattern not found: {old[:60]!r}")
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="\n").write(s)


edit("ground/pilot.py", [
    ('"FRAMES_SENT", "CHUNKS_SENT", "FRAME_BYTES", "PAYLOAD_LINK", "CMDS_RECEIVED", "EXPLORED_CELLS", "FRONTIERS"]',
     '"FRAMES_SENT", "CHUNKS_SENT", "FRAME_BYTES", "PAYLOAD_LINK", "CMDS_RECEIVED", "EXPLORED_CELLS", "FRONTIERS",\n'
     '                   "LEVEL", "KEYS", "NAV_MODE", "DOORS_KNOWN", "HUNT_LEFT"]'),
    ('RAW_KEYS = ("ROUTE_BEARING", "CLEAR_FWD", "CLEAR_LEFT", "CLEAR_RIGHT", "STUCK", "POS_X", "POS_Y", "ANGLE", "ENEMY_COUNT", "EXPLORED_CELLS")',
     'RAW_KEYS = ("ROUTE_BEARING", "CLEAR_FWD", "CLEAR_LEFT", "CLEAR_RIGHT", "STUCK", "POS_X", "POS_Y", "ANGLE", "ENEMY_COUNT", "EXPLORED_CELLS",\n'
     '            "LEVEL", "NAV_MODE", "KEYS", "DOORS_KNOWN", "HUNT_LEFT")'),
    ('        self.episode = None\n        self.episode_start_row = 0',
     '        self.episode = None\n        self.level = None\n        self.episode_start_row = 0'),
    ('                self.episode = ep\n                self.goal = "EXPLORE"',
     '                self.episode = ep\n                self.goal = "EXPLORE"\n'
     '            lv = self.telemetry.get("LEVEL")\n'
     '            if lv is not None and lv != self.level:\n'
     '                if self.level is not None:\n'
     '                    print(f"[pilot] *** LEVEL {self.level} FINISHED -> level {lv} ***", flush=True)\n'
     '                    self.log.write(json.dumps({"t": time.time(), "kind": "level", "finished": self.level, "started": lv, "controls": self.control_count}) + "\\n")\n'
     '                self.level = lv'),
])

edit("ground/decision_graph.py", [
    ('               "ARMOR": "an armor pickup seen earlier", "WEAPON": "a weapon seen earlier", "NONE": "nowhere yet"}',
     '               "ARMOR": "an armor pickup seen earlier", "WEAPON": "a weapon seen earlier", "NONE": "nowhere yet",\n'
     '               "KEY": "a key card seen earlier", "SWITCH": "a wall or switch to try", "EXIT": "the exit line seen on the map"}\n'
     'MODE = {"EXPLORE": "exploring toward the nearest unexplored frontier", "DOOR": "at a door on the route, it needs Use",\n'
     '        "KEY": "going to pick up a key seen earlier", "HUNT": "nothing left to explore, trying walls and switches to find the exit",\n'
     '        "IDLE": "nothing known to head for", "ITEM": "going to a pickup", "ENEMY": "closing on an enemy",\n'
     '        "EXIT": "heading for the exit line seen on the map"}\n'
     '\n'
     '\n'
     'def keys_words(bits):\n'
     '    held = [name for bit, name in ((1, "red"), (2, "blue"), (4, "yellow")) if int(bits or 0) & bit]\n'
     '    return " and ".join(held) if held else "none"'),
    ('        "frontiers": "none" if t.get("FRONTIERS", 0) == 0 else "few" if t.get("FRONTIERS", 0) < 10 else "many",',
     '        "frontiers": "none" if t.get("FRONTIERS", 0) == 0 else "few" if t.get("FRONTIERS", 0) < 10 else "many",\n'
     '        "mode": MODE.get(str(t.get("NAV_MODE", "EXPLORE")), "exploring"),\n'
     '        "level": str(t.get("LEVEL", 1)),\n'
     '        "keys": keys_words(t.get("KEYS", 0)),'),
    ('                       "blocked_where_the_route_goes": f["blocked_route"], "map_explored_cells": f["explored"], "unexplored_frontiers": f["frontiers"]},',
     '                       "blocked_where_the_route_goes": f["blocked_route"], "map_explored_cells": f["explored"], "unexplored_frontiers": f["frontiers"],\n'
     '                       "navigator": f["mode"], "level": f["level"], "keys_held": f["keys"]},'),
])

edit("ground/graph_config.py", [
    ('             "armor", "destination", "dest_dist", "health_pickup", "ammo_pickup", "armor_pickup", "frontiers", "explored"]',
     '             "armor", "destination", "dest_dist", "health_pickup", "ammo_pickup", "armor_pickup", "frontiers", "explored",\n'
     '             "mode", "level", "keys"]'),
    ('            "question": "Advance now? Route aligned ahead: {aligned}. Space ahead: {ahead}. Stuck: {stuck}. Space behind: {behind}.",\n'
     '            "criteria": {\n'
     '                "Forward": "Route aligned ahead is yes and space ahead is clear or tight. Also forward to close on a distant enemy.",\n'
     '                "Hold": "Route aligned ahead is no (turn first), or space ahead is blocked, or the destination is here, or stuck with nothing known clear around (turn instead).",',
     '            "question": "Advance now? Route aligned ahead: {aligned}. Space ahead: {ahead}. Stuck: {stuck}. Space behind: {behind}. Navigator: {mode}.",\n'
     '            "criteria": {\n'
     '                "Forward": "Route aligned ahead is yes and space ahead is clear or tight. Also forward to close on a distant enemy, and forward when at a door (walk up to it while it opens).",\n'
     '                "Hold": "Route aligned ahead is no (turn first), or space ahead is blocked and not at a door, or the destination is here, or stuck with nothing known clear around (turn instead).",'),
    ('            "question": "Press use (open a door, flip a switch)? Route blocked at arm length: {blocked_route}. Stuck: {stuck}. Walls in this game are often doors.",\n'
     '            "criteria": {\n'
     '                "Use": "Route blocked at arm length is yes, or stuck is yes: try the door or switch.",\n'
     '                "Wait": "Neither: nothing to operate."}},',
     '            "question": "Press use (open a door, flip a switch, try a wall)? Navigator: {mode}. Route blocked at arm length: {blocked_route}. Stuck: {stuck}.",\n'
     '            "criteria": {\n'
     '                "Use": "Route blocked at arm length is yes, or stuck is yes, or the navigator is at a door, at the exit line, or trying walls: press it.",\n'
     '                "Wait": "Nothing within reach to operate."}},'),
    ('            "question": "Immediate priority? Health: {health}. Threat: {threat} ({enemy_where}). Ammunition: {ammo}. Armor: {armor}. Nearby pickups: health {health_pickup}, ammo {ammo_pickup}, armor {armor_pickup}. Unexplored frontiers: {frontiers}.",',
     '            "question": "Immediate priority? Level {level}. Health: {health}. Threat: {threat} ({enemy_where}). Ammunition: {ammo}. Armor: {armor}. Nearby pickups: health {health_pickup}, ammo {ammo_pickup}, armor {armor_pickup}. Unexplored frontiers: {frontiers}. Navigator: {mode}.",'),
    ('                "Explore": "No close enemy, health fine, ammunition ready: keep exploring toward the nearest frontier to find the exit.",',
     '                "Explore": "No close enemy, health fine, ammunition ready: keep exploring toward the nearest frontier to find the exit. Also Explore whenever the navigator is at a door, fetching a key, heading for the exit or trying walls: let it finish.",'),
])

edit("ground/after_action.py", [
    ('    return {\n        "graph_version": cfg.get("version"),\n        "outcome": outcome,',
     '    modes = Counter(str(r.get("NAV_MODE")) for r in raw if r.get("NAV_MODE") is not None)\n'
     '    return {\n        "graph_version": cfg.get("version"),\n        "outcome": outcome,\n'
     '        "level": max((r.get("LEVEL", 0) or 0) for r in raw) if raw else None,\n'
     '        "navigator_modes_ticks": dict(modes.most_common()),\n'
     '        "doors_seen": max((r.get("DOORS_KNOWN", 0) or 0) for r in raw) if raw else None,\n'
     '        "keys_held_at_end": (raw[-1].get("KEYS") if raw else None),'),
])

for f in ("ground/pilot.py", "ground/decision_graph.py", "ground/graph_config.py", "ground/after_action.py"):
    subprocess.run([sys.executable, "-c", f"import ast;ast.parse(open('{f}',encoding='utf-8').read())"], check=True)
    print(f, "ok")

# fresh graph campaign: archive the earlier versions, seed v1 from the new defaults
if os.path.isdir("ground/graph") and not os.path.isdir("ground/graph_archive_freedoom_run"):
    shutil.move("ground/graph", "ground/graph_archive_freedoom_run")
sys.path.insert(0, "ground")
import graph_config as gc          # noqa: E402
import decision_graph as dg        # noqa: E402
cfg = gc.load()
print("graph v", cfg["version"])
t = {"HEALTH": 80, "NAV_MODE": "DOOR", "LEVEL": 2, "KEYS": 3, "TARGET_KIND": "EXIT", "DOOR_AHEAD": True}
q = dg.control_questions(t, "EXPLORE", cfg)
print(list(q), "|", q["use"]["instructions"]["question"])
print(dg.goal_question(t, cfg)["goal"]["instructions"]["question"][:170])
print(dg.build_state(t, "EXPLORE", cfg)["navigation"])
