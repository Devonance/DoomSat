"""One-shot patch (already applied): move the ground side from "reach the known exit" to "explore to find it"."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

p = ROOT / "ground/decision_graph.py"; s = p.read_text(encoding="utf-8")
s = s.replace('GOALS = ["REACH_EXIT", "KILL_ENEMY", "STOCK_AMMO", "RESTORE_HEALTH", "ADD_ARMOR", "UPGRADE_WEAPON", "SCOUT", "HOLD"]',
              'GOALS = ["EXPLORE", "KILL_ENEMY", "STOCK_AMMO", "RESTORE_HEALTH", "ADD_ARMOR", "UPGRADE_WEAPON", "SCOUT", "HOLD"]')
s = s.replace('            "destination": str(t.get("TARGET_KIND", "EXIT")).lower().replace("unexplored", "unexplored area"),',
              '            "destination": {"FRONTIER": "the nearest unexplored edge of the map", "FAR_FRONTIER": "a far unexplored part of the map",\n'
              '                            "ENEMY": "the enemy", "HEALTH": "a health pickup seen earlier", "AMMO": "an ammo pickup seen earlier",\n'
              '                            "ARMOR": "an armor pickup seen earlier", "WEAPON": "a weapon seen earlier", "NONE": "nowhere"}.get(str(t.get("TARGET_KIND", "FRONTIER")), "the frontier"),')
s = s.replace('            "space_behind": clear_words(t.get("CLEAR_BACK", 999)),',
              '            "space_behind": "unknown" if t.get("CLEAR_BACK", 999) == 24 else clear_words(t.get("CLEAR_BACK", 999) * 3),')
s = s.replace('            "door_or_switch_ahead": bool(t.get("DOOR_AHEAD", False)),\n        },',
              '            "blocked_where_the_route_goes": bool(t.get("DOOR_AHEAD", False)),\n'
              '            "map_explored_cells": "few" if t.get("EXPLORED_CELLS", 0) < 40 else "some" if t.get("EXPLORED_CELLS", 0) < 150 else "many",\n'
              '            "unexplored_frontiers": "none" if t.get("FRONTIERS", 0) == 0 else "few" if t.get("FRONTIERS", 0) < 10 else "many",\n        },')
for kind in ("HEALTH", "AMMO", "ARMOR"):
    s = s.replace(f'if t.get("{kind}_ITEM_DIST", 65535) < 900 else "none near",', f'if t.get("{kind}_ITEM_DIST", 65535) < 900 else "none seen near",')
old_use = s[s.index('        "use": choice('):s.index('    }\n\n\ndef goal_question')]
new_use = ('        "use": choice(\n'
           '            "Should the player press use (open a door, flip a switch)? `navigation.blocked_where_the_route_goes` says the route is blocked at arm length; walls in this game are often doors.",\n'
           '            {"Use": "The route is blocked at arm length, or the player is stuck: try the door or switch.",\n'
           '             "Wait": "Nothing blocks the route at arm length."}),\n')
s = s.replace(old_use, new_use)
s = s.replace('         "Reach exit": "No close enemy, health fine, ammunition ready.",\n'
              '         "Scout": "The destination is here or the player is stuck with the route blocked.",',
              '         "Explore": "No close enemy, health fine, ammunition ready: keep exploring toward the nearest frontier to find the exit.",\n'
              '         "Scout": "The nearest frontier is exhausted or the player keeps getting stuck: head for a far unexplored part of the map.",')
s = s.replace('"Add armor": "ADD_ARMOR", "Reach exit": "REACH_EXIT", "Scout": "SCOUT", "Upgrade weapon": "UPGRADE_WEAPON"}',
              '"Add armor": "ADD_ARMOR", "Explore": "EXPLORE", "Scout": "SCOUT", "Upgrade weapon": "UPGRADE_WEAPON"}')
p.write_text(s, encoding="utf-8", newline="\n")

p = ROOT / "ground/providers.py"; s = p.read_text(encoding="utf-8")
s = s.replace('"enum": ["REACH_EXIT", "KILL_ENEMY", "STOCK_AMMO", "RESTORE_HEALTH", "ADD_ARMOR", "UPGRADE_WEAPON", "SCOUT", "HOLD"]},',
              '"enum": ["EXPLORE", "KILL_ENEMY", "STOCK_AMMO", "RESTORE_HEALTH", "ADD_ARMOR", "UPGRADE_WEAPON", "SCOUT", "HOLD"]},\n'
              '        "steer_hint": {"type": "string", "enum": ["none", "ahead", "left", "right", "behind"]},')
s = s.replace('"Choose the goal for the next few seconds. Prefer survival, then combat, then supplies, then the exit. "',
              '"Nobody knows the level layout: the onboard navigator builds its own map from a range camera and explores toward "\n'
              '    "unexplored frontiers; pickups and enemies count only once they have been seen. Choose the goal for the next few seconds. "\n'
              '    "Prefer survival, then combat, then supplies, then exploring to find the exit. If the frame shows an opening, a door, "\n'
              '    "a lit corridor or an exit sign worth heading for, give steer_hint (ahead/left/right/behind) and the navigator will favour "\n'
              '    "frontiers that way for a while; otherwise say none. "')
s = s.replace('"ADD_ARMOR, UPGRADE_WEAPON, SCOUT, HOLD), rationale, frame_note."',
              '"ADD_ARMOR, UPGRADE_WEAPON, SCOUT, HOLD), steer_hint (none|ahead|left|right|behind), rationale, frame_note."')
p.write_text(s, encoding="utf-8", newline="\n")

p = ROOT / "ground/pilot.py"; s = p.read_text(encoding="utf-8")
s = s.replace('"FRAMES_SENT", "CHUNKS_SENT", "FRAME_BYTES", "PAYLOAD_LINK", "CMDS_RECEIVED"]',
              '"FRAMES_SENT", "CHUNKS_SENT", "FRAME_BYTES", "PAYLOAD_LINK", "CMDS_RECEIVED", "EXPLORED_CELLS", "FRONTIERS"]')
s = s.replace('        self.goal = "REACH_EXIT"', '        self.goal = "EXPLORE"')
s = s.replace('            self.set_goal(plan.get("goal", self.goal), self.system_two.name, plan)\n',
              '            self.set_goal(plan.get("goal", self.goal), self.system_two.name, plan)\n'
              '            hint = {"ahead": 0, "left": 60, "right": -60, "behind": 180}.get(plan.get("steer_hint"))\n'
              '            if hint is not None:\n'
              '                self.command("EXPLORE_HINT", {"bearing": hint, "ttl": int(self.args.plan_every * 1.5)})\n')
s = s.replace("\"Plan\": f\"{plan.get('goal')}: {plan.get('rationale', '')}",
              "\"Plan\": f\"{plan.get('goal')}{(' / steer ' + plan['steer_hint']) if plan.get('steer_hint') not in (None, 'none') else ''}: {plan.get('rationale', '')}")
s = s.replace('default="Reach the level exit alive; fight what blocks the way; pick up supplies when they are needed."',
              'default="Find the level exit alive; fight what blocks the way; pick up supplies when they are needed."')
p.write_text(s, encoding="utf-8", newline="\n")

for f in ("ground/decision_graph.py", "ground/providers.py", "ground/pilot.py"):
    ast.parse((ROOT / f).read_text(encoding="utf-8"))
print("ground patched")
