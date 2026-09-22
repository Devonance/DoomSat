"""The System One decision graph for the Doom pilot.

Code turns telemetry numbers into words, asks jev narrow typed questions (one per control
head) with the relevant facts stated inside each question, and maps the typed answers back
onto the CONTROL command. Nothing here reasons; the model only judges. The heads follow
TypeSafe's Jev Doom demo (dodge, move, strafe, turn, fire, weapon, use).

Telemetry in (dict keyed by channel name, e.g. HEALTH, ENEMY_BEARING) -> (state, questions)
Answers in (dict qid -> {"choice": ...}) -> CONTROL args
"""

GOALS = ["EXPLORE", "KILL_ENEMY", "STOCK_AMMO", "RESTORE_HEALTH", "ADD_ARMOR", "UPGRADE_WEAPON", "SCOUT", "HOLD"]
CONTROL_HEADS = ("dodge", "move", "strafe", "turn", "fire", "weapon", "use")


def choice(question, criteria, focus=None):
    q = {"type": "choice", "instructions": {"question": question}, "criteria": {k: {"what": v} for k, v in criteria.items()}}
    if focus:
        q["instructions"]["focus"] = focus
    return q


# ---------------------------------------------------------------- numbers -> words
def health_words(h):
    return "critical" if h < 35 else "low" if h < 50 else "fine" if h < 90 else "full"


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


def clear_words(c):
    return "blocked" if c < 45 else "tight" if c < 70 else "clear"


def side_words(c):
    """Sides come from the self-built map when the camera cannot see them; 24 is the payload code for unknown."""
    return "unknown" if c == 24 else clear_words(c)


def ammo_words(t):
    shells, bullets = t.get("SHELLS", 0), t.get("BULLETS", 0)
    if shells == 0 and bullets == 0:
        return "empty"
    if shells == 0 and bullets < 12:
        return "scarce"
    return "ready"


DESTINATION = {"FRONTIER": "the nearest unexplored edge of the map", "FAR_FRONTIER": "a far unexplored part of the map",
               "ENEMY": "the enemy", "HEALTH": "a health pickup seen earlier", "AMMO": "an ammo pickup seen earlier",
               "ARMOR": "an armor pickup seen earlier", "WEAPON": "a weapon seen earlier", "NONE": "nowhere yet"}


def facts(t, goal):
    """The handful of facts every question refers to, computed once from the telemetry."""
    enemy = t.get("ENEMY_COUNT", 0) > 0
    e_bearing, e_dist = t.get("ENEMY_BEARING", 0.0), t.get("ENEMY_DIST", 0)
    aiming_enemy = goal == "KILL_ENEMY" and enemy
    aim = e_bearing if aiming_enemy else t.get("ROUTE_BEARING", 0.0)
    return {
        "enemy": enemy,
        "enemy_where": (bearing_words(e_bearing) + ", " + dist_words(e_dist)) if enemy else "no enemy in view",
        "threat": "danger" if enemy and e_dist < 180 else "safe",
        "in_crosshair": enemy and abs(e_bearing) <= 8 and e_dist <= 450,
        "ammo": ammo_words(t),
        "equipped_ammo": t.get("SHELLS", 0) if str(t.get("WEAPON")) == "SHOTGUN" else t.get("BULLETS", 0),
        "aim_target": "the enemy" if aiming_enemy else "the route waypoint",
        "aim": bearing_words(aim),
        "aligned": abs(t.get("ROUTE_BEARING", 0.0)) <= 35,
        "ahead": clear_words(t.get("CLEAR_FWD", 999)),
        "left": side_words(t.get("CLEAR_LEFT", 999)),
        "right": side_words(t.get("CLEAR_RIGHT", 999)),
        "behind": side_words(t.get("CLEAR_BACK", 999)),
        "stuck": bool(t.get("STUCK", False)),
        "blocked_route": bool(t.get("DOOR_AHEAD", False)),
        "destination": DESTINATION.get(str(t.get("TARGET_KIND", "FRONTIER")), "the frontier"),
        "dest_dist": dist_words(t.get("TARGET_DIST", 0)) if t.get("TARGET_DIST", 0) else "here",
    }


def build_state(t, goal, standing_order):
    """t: latest telemetry values by channel name (numbers). Returns the state jev sees."""
    f = facts(t, goal)
    return {
        "standing_order": standing_order,
        "committed_goal": goal.replace("_", " ").lower(),
        "player": {
            "health": health_words(t.get("HEALTH", 100)),
            "armor": "none" if t.get("ARMOR", 0) <= 0 else "some" if t.get("ARMOR", 0) < 50 else "good",
            "ammunition": f["ammo"],
            "equipped_weapon": str(t.get("WEAPON", "PISTOL")).lower(),
            "shotgun_shells": "none" if t.get("SHELLS", 0) == 0 else "a few" if t.get("SHELLS", 0) < 6 else "plenty",
            "pistol_bullets": "none" if t.get("BULLETS", 0) == 0 else "a few" if t.get("BULLETS", 0) < 12 else "plenty",
            "owns_shotgun": bool(t.get("OWN_SHOTGUN", False)),
        },
        "combat": {"enemy_visible": f["enemy"], "enemy_where": f["enemy_where"], "enemy_in_crosshair": f["in_crosshair"]},
        "navigation": {
            "destination": f["destination"], "destination_distance": f["dest_dist"],
            "route_aligned_ahead": f["aligned"], "aim_target": f["aim_target"], "aim_offset": f["aim"],
            "space_ahead": f["ahead"], "space_left": f["left"], "space_right": f["right"], "space_behind": f["behind"],
            "stuck": f["stuck"], "blocked_where_the_route_goes": f["blocked_route"],
            "map_explored_cells": "few" if t.get("EXPLORED_CELLS", 0) < 40 else "some" if t.get("EXPLORED_CELLS", 0) < 150 else "many",
            "unexplored_frontiers": "none" if t.get("FRONTIERS", 0) == 0 else "few" if t.get("FRONTIERS", 0) < 10 else "many",
        },
        "supplies_nearby": {
            "health_pickup": dist_words(t.get("HEALTH_ITEM_DIST", 0)) if t.get("HEALTH_ITEM_DIST", 65535) < 900 else "none seen near",
            "ammo_pickup": dist_words(t.get("AMMO_ITEM_DIST", 0)) if t.get("AMMO_ITEM_DIST", 65535) < 900 else "none seen near",
            "armor_pickup": dist_words(t.get("ARMOR_ITEM_DIST", 0)) if t.get("ARMOR_ITEM_DIST", 65535) < 900 else "none seen near",
        },
    }


def control_questions(t, goal):
    """Seven control heads, each stating the facts it depends on. All independent, asked in one request."""
    f = facts(t, goal)
    yn = lambda b: "yes" if b else "no"
    heads = {
        "dodge": choice(
            f"Sidestep away from an enemy? Threat: {f['threat']} ({f['enemy_where']}). Space left: {f['left']}, right: {f['right']}, behind: {f['behind']}.",
            {"Carry on": "Threat is safe. Do not dodge just because an enemy exists.",
             "Dodge left": "Threat is danger and space left is clear.",
             "Dodge right": "Threat is danger, left is not clear, space right is clear.",
             "Dodge back": "Threat is danger, sides not clear, space behind is clear."}),
        "move": choice(
            f"Advance now? Route aligned ahead: {yn(f['aligned'])}. Space ahead: {f['ahead']}. Stuck: {yn(f['stuck'])}. Space behind: {f['behind']}.",
            {"Forward": "Route aligned ahead is yes and space ahead is clear or tight. Also forward to close on a distant enemy.",
             "Hold": "Route aligned ahead is no (turn first), or space ahead is blocked, or the destination is here, or stuck with nothing known clear around (turn instead).",
             **({"Backward": "Stuck is yes and space behind is clear."} if f["stuck"] and f["behind"] == "clear" else {})}),
        "strafe": choice(
            f"Recovery sidestep? Stuck: yes. Space left: {f['left']}, right: {f['right']}.",
            {"Hold": "Neither side is known clear: turn instead.",
             **({"Strafe left": "Space left is clear."} if f["left"] == "clear" else {}),
             **({"Strafe right": "Space right is clear."} if f["right"] == "clear" else {})}) if f["stuck"] and (f["left"] == "clear" or f["right"] == "clear") else None,
        "turn": choice(
            f"Turn to put {f['aim_target']} in the crosshair. It is now: {f['aim']}.",
            {"Hard left": "It is far left.", "Left": "It is left.", "Fine left": "It is slightly left or just left of the crosshair.",
             "Hold": "It is centered.",
             "Fine right": "It is slightly right or just right of the crosshair.", "Right": "It is right.", "Hard right": "It is far right.",
             "Turn around": "It is behind."}),
        "fire": choice(
            f"Pull the trigger? Living enemy in the crosshair: {yn(f['in_crosshair'])} ({f['enemy_where']}). Equipped ammunition: {f['equipped_ammo']}. Never shoot at the route waypoint.",
            {"Fire": "Enemy in the crosshair is yes and equipped ammunition is more than zero.",
             "Hold fire": "Enemy in the crosshair is no, or equipped ammunition is zero."}),
        "weapon": choice(
            f"Which weapon? Equipped: {str(t.get('WEAPON', 'PISTOL')).lower()}. Shotgun shells: {t.get('SHELLS', 0)}. Pistol bullets: {t.get('BULLETS', 0)}. Owns shotgun: {yn(t.get('OWN_SHOTGUN', False))}.",
            {"Keep": "The equipped weapon still has ammunition.",
             "Pistol": "Shotgun shells are zero and pistol bullets remain.",
             "Shotgun": "Owns a shotgun with shells and the pistol is equipped."}),
        "use": choice(
            f"Press use (open a door, flip a switch)? Route blocked at arm length: {yn(f['blocked_route'])}. Stuck: {yn(f['stuck'])}. Walls in this game are often doors.",
            {"Use": "Route blocked at arm length is yes, or stuck is yes: try the door or switch.",
             "Wait": "Neither: nothing to operate."}) if (f["blocked_route"] or f["stuck"]) else None,
    }
    return {k: v for k, v in heads.items() if v is not None}


def goal_question(t):
    """System One fallback planner (used only when System Two is unavailable)."""
    f = facts(t, "EXPLORE")
    return {"goal": choice(
        f"Immediate priority? Health: {health_words(t.get('HEALTH', 100))}. Threat: {f['threat']} ({f['enemy_where']}). Ammunition: {f['ammo']}. Armor: {t.get('ARMOR', 0)}.",
        {"Kill enemies": "An enemy is visible at close or mid range, health is not critical and ammunition is ready.",
         "Restore health": "Health is critical, or low with a health pickup seen and no close enemy.",
         "Stock ammo": "Ammunition is empty or scarce and an ammo pickup was seen.",
         "Add armor": "Armor is none, an armor pickup was seen, health fine, no close enemy.",
         "Explore": "No close enemy, health fine, ammunition ready: keep exploring toward the nearest frontier to find the exit.",
         "Scout": "The nearest frontier is exhausted or the player keeps getting stuck: head for a far unexplored part of the map.",
         "Upgrade weapon": "No shotgun owned, a weapon was seen, no close enemy."})}


GOAL_FROM_CHOICE = {"Kill enemies": "KILL_ENEMY", "Restore health": "RESTORE_HEALTH", "Stock ammo": "STOCK_AMMO",
                    "Add armor": "ADD_ARMOR", "Explore": "EXPLORE", "Scout": "SCOUT", "Upgrade weapon": "UPGRADE_WEAPON"}

# Degrees to turn per decision (executed onboard as a heading setpoint); positive is left, like the bearings.
TURN_DEG = {"Hard left": 60.0, "Left": 25.0, "Fine left": 8.0, "Hold": 0.0, "Fine right": -8.0, "Right": -25.0, "Hard right": -60.0,
            "Turn around": 150.0}


def control_args(answers):
    """Typed answers -> CONTROL command arguments (the only place choices become buttons)."""
    a = {k: v["choice"] for k, v in answers.items() if k in CONTROL_HEADS}
    sideways = a.get("dodge", "Carry on")
    if sideways == "Carry on":
        sideways = a.get("strafe", "Hold")
    move = 1 if a.get("move") == "Forward" else -1 if a.get("move") == "Backward" or a.get("dodge") == "Dodge back" else 0
    strafe = -1 if sideways in ("Dodge left", "Strafe left") else 1 if sideways in ("Dodge right", "Strafe right") else 0
    weapon = {"Pistol": "PISTOL", "Shotgun": "SHOTGUN"}.get(a.get("weapon"), "FIST")
    return {"move": move, "strafe": strafe, "turn": TURN_DEG.get(a.get("turn", "Hold"), 0.0),
            "fire": a.get("fire") == "Fire", "use": a.get("use") == "Use", "weapon": weapon}
