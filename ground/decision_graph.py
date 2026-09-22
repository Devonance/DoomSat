"""The System One decision graph for the Doom pilot, driven by graph_config.

Code turns telemetry numbers into words, asks jev narrow typed questions (one per control head,
each stating the facts it depends on), and maps the typed answers back onto the CONTROL command.
Nothing here reasons; the model only judges. Which options a head is offered is decided by code
(a Backward that cannot apply is not on the menu). The wording, criteria and thresholds come from
the graph config, which System Two revises between episodes.
"""

GOALS = ["EXPLORE", "KILL_ENEMY", "STOCK_AMMO", "RESTORE_HEALTH", "ADD_ARMOR", "UPGRADE_WEAPON", "SCOUT", "HOLD"]
CONTROL_HEADS = ("steer", "dodge", "move", "strafe", "turn", "fire", "weapon", "use")
GOAL_FROM_CHOICE = {"Kill enemies": "KILL_ENEMY", "Restore health": "RESTORE_HEALTH", "Stock ammo": "STOCK_AMMO",
                    "Add armor": "ADD_ARMOR", "Explore": "EXPLORE", "Scout": "SCOUT", "Upgrade weapon": "UPGRADE_WEAPON"}
DESTINATION = {"FRONTIER": "the nearest unexplored edge of the map", "FAR_FRONTIER": "a far unexplored part of the map",
               "ENEMY": "the enemy", "HEALTH": "a health pickup seen earlier", "AMMO": "an ammo pickup seen earlier",
               "ARMOR": "an armor pickup seen earlier", "WEAPON": "a weapon seen earlier", "NONE": "nowhere yet",
               "KEY": "a key card seen earlier", "SWITCH": "a wall or switch to try", "EXIT": "the exit line seen on the map"}
MODE = {"EXPLORE": "exploring toward the nearest unexplored frontier", "DOOR": "at a door on the route, it needs Use",
        "KEY": "going to pick up a key seen earlier", "HUNT": "nothing left to explore, trying walls and switches to find the exit",
        "IDLE": "nothing known to head for", "ITEM": "going to a pickup", "ENEMY": "closing on an enemy",
        "EXIT": "heading for the exit line seen on the map"}


def keys_words(bits):
    held = [name for bit, name in ((1, "red"), (2, "blue"), (4, "yellow")) if int(bits or 0) & bit]
    return " and ".join(held) if held else "none"


def choice(question, criteria):
    return {"type": "choice", "instructions": {"question": question}, "criteria": {k: {"what": v} for k, v in criteria.items()}}


# ---------------------------------------------------------------- numbers -> words
def dist_words(d):
    return "none" if d <= 0 else "point blank" if d < 70 else "close" if d < 180 else "mid-range" if d < 450 else "far"


def bearing_words(b):
    a = abs(b)
    side = "left" if b > 0 else "right"
    if a <= 3:
        return "centered"
    if a <= 8:
        return f"just {side} of the crosshair"
    if a <= 15:
        return f"slightly {side}"
    if a <= 50:
        return f"{side}"
    if a <= 150:
        return f"far {side}"
    return "behind"


def route_words(b):
    a = abs(b)
    if a <= 30:
        return "straight ahead"
    if a <= 120:
        return "to the left" if b > 0 else "to the right"
    return "behind"


def facts(t, goal, cfg):
    """Every word a question may use, computed once from the telemetry and the config thresholds."""
    th = cfg["thresholds"]
    clear = lambda c: "blocked" if c < th["blocked_units"] else "tight" if c < th["tight_units"] else "clear"
    side = lambda c: "unknown" if c == 24 else clear(c)   # 24 is the payload's code for "map does not know"
    yn = lambda b: "yes" if b else "no"
    enemy = t.get("ENEMY_COUNT", 0) > 0
    e_bearing, e_dist = t.get("ENEMY_BEARING", 0.0), t.get("ENEMY_DIST", 0)
    aiming_enemy = goal == "KILL_ENEMY" and enemy
    aim = e_bearing if aiming_enemy else t.get("ROUTE_BEARING", 0.0)
    shells, bullets, hp = t.get("SHELLS", 0), t.get("BULLETS", 0), t.get("HEALTH", 100)
    pick = lambda k: dist_words(t.get(k, 0)) if t.get(k, 65535) < 900 else "none seen near"
    f = {
        "enemy_visible": enemy,
        "threat": "danger" if enemy and e_dist < th["danger_dist"] else "safe",
        "enemy_where": (bearing_words(e_bearing) + ", " + dist_words(e_dist)) if enemy else "no enemy in view",
        "in_crosshair_bool": bool(enemy and abs(e_bearing) <= th["crosshair_deg"] and e_dist <= th["fire_range"]),
        "aligned_bool": abs(t.get("ROUTE_BEARING", 0.0)) <= th["aligned_deg"],
        "stuck_bool": bool(t.get("STUCK", False)),
        "blocked_route_bool": bool(t.get("DOOR_AHEAD", False)),
        "aim_target": "the enemy" if aiming_enemy else "the route waypoint",
        "aim": bearing_words(aim),
        "ahead": clear(t.get("CLEAR_FWD", 999)),
        "left": side(t.get("CLEAR_LEFT", 999)), "right": side(t.get("CLEAR_RIGHT", 999)), "behind": side(t.get("CLEAR_BACK", 999)),
        "equipped": str(t.get("WEAPON", "PISTOL")).lower(),
        "equipped_ammo": shells if str(t.get("WEAPON")) == "SHOTGUN" else bullets,
        "shells": shells, "bullets": bullets, "owns_shotgun": yn(t.get("OWN_SHOTGUN", False)),
        "health": "critical" if hp < th["health_critical"] else "low" if hp < th["health_low"] else "fine" if hp < 90 else "full",
        "ammo": "empty" if shells == 0 and bullets == 0 else "scarce" if shells == 0 and bullets < 12 else "ready",
        "armor": "none" if t.get("ARMOR", 0) <= 0 else "some" if t.get("ARMOR", 0) < 50 else "good",
        "destination": DESTINATION.get(str(t.get("TARGET_KIND", "FRONTIER")), "the frontier"),
        "dest_dist": dist_words(t.get("TARGET_DIST", 0)) if t.get("TARGET_DIST", 0) else "here",
        "health_pickup": pick("HEALTH_ITEM_DIST"), "ammo_pickup": pick("AMMO_ITEM_DIST"), "armor_pickup": pick("ARMOR_ITEM_DIST"),
        "frontiers": "none" if t.get("FRONTIERS", 0) == 0 else "few" if t.get("FRONTIERS", 0) < 10 else "many",
        "mode": MODE.get(str(t.get("NAV_MODE", "EXPLORE")), "exploring"),
        "route_where": route_words(t.get("ROUTE_BEARING", 0.0)) if t.get("TARGET_KIND", "NONE") != "NONE" else "nowhere (nothing known to head for)",
        "route_far": dist_words(t.get("ROUTE_DIST", 0)),
        "level": str(t.get("LEVEL", 1)),
        "keys": keys_words(t.get("KEYS", 0)),
        "explored": "few" if t.get("EXPLORED_CELLS", 0) < 40 else "some" if t.get("EXPLORED_CELLS", 0) < 150 else "many",
    }
    for k in ("in_crosshair", "aligned", "stuck", "blocked_route"):
        f[k] = yn(f[k + "_bool"])
    return f


def build_state(t, goal, cfg):
    """The state jev sees alongside the questions."""
    f = facts(t, goal, cfg)
    return {
        "standing_order": cfg["standing_order"],
        "committed_goal": goal.replace("_", " ").lower(),
        "player": {"health": f["health"], "armor": f["armor"], "ammunition": f["ammo"], "equipped_weapon": f["equipped"],
                   "shotgun_shells": f["shells"], "pistol_bullets": f["bullets"], "owns_shotgun": f["owns_shotgun"]},
        "combat": {"enemy_visible": f["enemy_visible"], "enemy_where": f["enemy_where"], "enemy_in_crosshair": f["in_crosshair"]},
        "navigation": {"destination": f["destination"], "destination_distance": f["dest_dist"], "route_aligned_ahead": f["aligned"],
                       "aim_target": f["aim_target"], "aim_offset": f["aim"], "space_ahead": f["ahead"], "space_left": f["left"],
                       "space_right": f["right"], "space_behind": f["behind"], "stuck": f["stuck"],
                       "blocked_where_the_route_goes": f["blocked_route"], "map_explored_cells": f["explored"], "unexplored_frontiers": f["frontiers"],
                       "navigator": f["mode"], "level": f["level"], "keys_held": f["keys"]},
        "supplies_seen": {"health_pickup": f["health_pickup"], "ammo_pickup": f["ammo_pickup"], "armor_pickup": f["armor_pickup"]},
    }


def _render(cfg, head, f, options=None):
    spec = cfg["questions"][head]
    crit = {k: v for k, v in spec["criteria"].items() if options is None or k in options}
    return choice(spec["question"].format_map(f), crit)


def control_questions(t, goal, cfg):
    """The control heads for this tick. Code decides which heads are asked and which options are on the menu."""
    f = facts(t, goal, cfg)
    stuck = f["stuck_bool"]
    heads = {
        "steer": _render(cfg, "steer", f),
        "dodge": _render(cfg, "dodge", f),
        "move": _render(cfg, "move", f, ["Forward", "Hold"] + (["Backward"] if f["behind"] == "clear" else [])),
        "turn": _render(cfg, "turn", f),
        "fire": _render(cfg, "fire", f),
        "weapon": _render(cfg, "weapon", f),
    }
    sides = ["Hold"] + (["Strafe left"] if f["left"] == "clear" else []) + (["Strafe right"] if f["right"] == "clear" else [])
    if stuck and len(sides) > 1:
        heads["strafe"] = _render(cfg, "strafe", f, sides)
    if stuck or f["blocked_route_bool"]:
        heads["use"] = _render(cfg, "use", f)
    return heads


def goal_question(t, cfg):
    return {"goal": _render(cfg, "goal", facts(t, "EXPLORE", cfg))}


def control_args(answers, cfg):
    """Typed answers -> CONTROL command arguments (the only place choices become buttons)."""
    a = {k: v["choice"] for k, v in answers.items() if k in CONTROL_HEADS}
    sideways = a.get("dodge", "Carry on")
    if sideways == "Carry on":
        sideways = a.get("strafe", "Hold")
    move = 1 if a.get("move") == "Forward" else -1 if a.get("move") == "Backward" or a.get("dodge") == "Dodge back" else 0
    strafe = -1 if sideways in ("Dodge left", "Strafe left") else 1 if sideways in ("Dodge right", "Strafe right") else 0
    weapon = {"Pistol": "PISTOL", "Shotgun": "SHOTGUN"}.get(a.get("weapon"), "FIST")
    turn = float(cfg["turn_deg"].get(a.get("turn", "Hold"), 0.0))
    steer = a.get("steer", "Follow route")
    if steer == "Left":          # jev picked a way of its own: turn there now, walk next tick
        turn, move = 90.0, 0
    elif steer == "Right":
        turn, move = -90.0, 0
    elif steer == "Back":
        turn, move = 0.0, -1
    elif steer == "Turn around":
        turn, move = 150.0, 0
    return {"move": move, "strafe": strafe, "turn": turn,
            "fire": a.get("fire") == "Fire", "use": a.get("use") == "Use", "weapon": weapon}
