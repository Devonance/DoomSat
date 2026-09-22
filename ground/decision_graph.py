"""The System One decision graph for the Doom pilot.

Code turns telemetry numbers into words, asks jev narrow typed questions (one per control
head), and maps the typed answers back onto the CONTROL command. Nothing here reasons; the
model only judges. Questions follow the shape of TypeSafe's Jev Doom demo (goal, dodge,
move, strafe, turn, fire, weapon, use).

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
    if a <= 2:
        return "centered"
    if a <= 7:
        return f"just {side} of the crosshair"
    if a <= 12:
        return f"slightly {side}"
    if a <= 45:
        return f"{side}"
    return f"far {side}"


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


def build_state(t, goal, standing_order):
    """t: latest telemetry values by channel name (numbers). Returns the state jev sees."""
    enemy = t.get("ENEMY_COUNT", 0) > 0
    return {
        "standing_order": standing_order,
        "committed_goal": goal.replace("_", " ").lower(),
        "player": {
            "health": health_words(t.get("HEALTH", 100)),
            "armor": "none" if t.get("ARMOR", 0) <= 0 else "some" if t.get("ARMOR", 0) < 50 else "good",
            "ammunition": ammo_words(t),
            "equipped_weapon": str(t.get("WEAPON", "PISTOL")).lower(),
            "shotgun_shells": "none" if t.get("SHELLS", 0) == 0 else "a few" if t.get("SHELLS", 0) < 6 else "plenty",
            "pistol_bullets": "none" if t.get("BULLETS", 0) == 0 else "a few" if t.get("BULLETS", 0) < 12 else "plenty",
            "owns_shotgun": bool(t.get("OWN_SHOTGUN", False)),
        },
        "combat": {
            "enemy_visible": enemy,
            "enemy_where": (bearing_words(t.get("ENEMY_BEARING", 0.0)) + ", " + dist_words(t.get("ENEMY_DIST", 0))) if enemy else "no enemy in view",
            "enemy_in_crosshair": enemy and abs(t.get("ENEMY_BEARING", 99)) <= 7 and t.get("ENEMY_DIST", 9999) <= 450,
        },
        "navigation": {
            "destination": {"FRONTIER": "the nearest unexplored edge of the map", "FAR_FRONTIER": "a far unexplored part of the map",
                            "ENEMY": "the enemy", "HEALTH": "a health pickup seen earlier", "AMMO": "an ammo pickup seen earlier",
                            "ARMOR": "an armor pickup seen earlier", "WEAPON": "a weapon seen earlier", "NONE": "nowhere"}.get(str(t.get("TARGET_KIND", "FRONTIER")), "the frontier"),
            "destination_distance": dist_words(t.get("TARGET_DIST", 0)) if t.get("TARGET_DIST", 0) else "here",
            "route_waypoint": bearing_words(t.get("ROUTE_BEARING", 0.0)),
            "route_aligned_ahead": abs(t.get("ROUTE_BEARING", 0.0)) <= 35,
            "aim_target": "the enemy" if goal == "KILL_ENEMY" and enemy else "the route waypoint",
            "aim_offset": bearing_words(t.get("ENEMY_BEARING", 0.0) if goal == "KILL_ENEMY" and enemy else t.get("ROUTE_BEARING", 0.0)),
            "space_ahead": clear_words(t.get("CLEAR_FWD", 999)),
            "space_left": side_words(t.get("CLEAR_LEFT", 999)),
            "space_right": side_words(t.get("CLEAR_RIGHT", 999)),
            "space_behind": side_words(t.get("CLEAR_BACK", 999)),
            "stuck": bool(t.get("STUCK", False)),
            "blocked_where_the_route_goes": bool(t.get("DOOR_AHEAD", False)),
            "map_explored_cells": "few" if t.get("EXPLORED_CELLS", 0) < 40 else "some" if t.get("EXPLORED_CELLS", 0) < 150 else "many",
            "unexplored_frontiers": "none" if t.get("FRONTIERS", 0) == 0 else "few" if t.get("FRONTIERS", 0) < 10 else "many",
        },
        "supplies_nearby": {
            "health_pickup": dist_words(t.get("HEALTH_ITEM_DIST", 0)) if t.get("HEALTH_ITEM_DIST", 65535) < 900 else "none seen near",
            "ammo_pickup": dist_words(t.get("AMMO_ITEM_DIST", 0)) if t.get("AMMO_ITEM_DIST", 65535) < 900 else "none seen near",
            "armor_pickup": dist_words(t.get("ARMOR_ITEM_DIST", 0)) if t.get("ARMOR_ITEM_DIST", 65535) < 900 else "none seen near",
        },
    }


def control_questions():
    """Seven control heads. All independent, asked in one request."""
    return {
        "dodge": choice(
            "Should the player sidestep away from an enemy right now? Look at `combat.enemy_where` and the free space in `navigation`.",
            {"Carry on": "No enemy at point blank or close range. Do not dodge just because an enemy exists.",
             "Dodge left": "Enemy close or point blank and `navigation.space_left` is clear.",
             "Dodge right": "Enemy close or point blank, left is not clear, `navigation.space_right` is clear.",
             "Dodge back": "Enemy point blank, both sides blocked or tight, `navigation.space_behind` is clear."}),
        "move": choice(
            "Should the player advance toward `navigation.destination` now? Use `navigation.route_aligned_ahead` and `navigation.space_ahead`.",
            {"Forward": "Route aligned ahead and space ahead is not blocked. Also forward when closing on a distant enemy.",
             "Hold": "Route not aligned ahead (turn first), or destination is here, or space ahead is blocked.",
             "Backward": "Stuck against an obstacle and space behind is clear."}),
        "strafe": choice(
            "Recovery sidestep. Only when `navigation.stuck` is true; otherwise Hold regardless of side space.",
            {"Hold": "Not stuck. Also hold if both sides are blocked.",
             "Strafe left": "Stuck and space left is clear.",
             "Strafe right": "Stuck, left not clear, space right is clear."}),
        "turn": choice(
            "Turn to bring `navigation.aim_target` to the crosshair. `navigation.aim_offset` says where it is now.",
            {"Hard left": "Aim offset is far left.", "Left": "Aim offset is left.", "Fine left": "Aim offset is slightly left or just left of the crosshair.",
             "Hold": "Aim offset is centered.",
             "Fine right": "Aim offset is slightly right or just right of the crosshair.", "Right": "Aim offset is right.", "Hard right": "Aim offset is far right."}),
        "fire": choice(
            "Should the player pull the trigger? Only at a living enemy in the crosshair with ammunition; never at the route waypoint.",
            {"Fire": "`combat.enemy_in_crosshair` is true and ammunition is not empty.",
             "Hold fire": "No enemy in the crosshair, or ammunition is empty."}),
        "weapon": choice(
            "Which weapon should be equipped, given `player.shotgun_shells`, `player.pistol_bullets` and `player.owns_shotgun`?",
            {"Keep": "The equipped weapon still has ammunition; no reason to switch.",
             "Pistol": "Shotgun shells are none and pistol bullets remain.",
             "Shotgun": "The player owns a shotgun with shells and is not holding it."}),
        "use": choice(
            "Should the player press use (open a door, flip a switch)? `navigation.blocked_where_the_route_goes` says the route is blocked at arm length; walls in this game are often doors.",
            {"Use": "The route is blocked at arm length, or the player is stuck: try the door or switch.",
             "Wait": "Nothing blocks the route at arm length."}),
    }


def goal_question():
    """System One fallback planner (used when System Two is unavailable or stale)."""
    return {"goal": choice(
        "Pick the immediate priority from the situation, not from `committed_goal`.",
        {"Kill enemies": "An enemy is visible at close or mid range, health is not critical and ammunition is ready.",
         "Restore health": "Health is critical, or low with a health pickup near and no close enemy.",
         "Stock ammo": "Ammunition is empty or scarce and an ammo pickup is near.",
         "Add armor": "Armor is none, an armor pickup is near, health fine, no close enemy.",
         "Explore": "No close enemy, health fine, ammunition ready: keep exploring toward the nearest frontier to find the exit.",
         "Scout": "The nearest frontier is exhausted or the player keeps getting stuck: head for a far unexplored part of the map.",
         "Upgrade weapon": "No shotgun owned, a weapon pickup is near, no close enemy."})}


GOAL_FROM_CHOICE = {"Kill enemies": "KILL_ENEMY", "Restore health": "RESTORE_HEALTH", "Stock ammo": "STOCK_AMMO",
                    "Add armor": "ADD_ARMOR", "Explore": "EXPLORE", "Scout": "SCOUT", "Upgrade weapon": "UPGRADE_WEAPON"}

TURN_RATE = {"Hard left": -5.0, "Left": -2.5, "Fine left": -0.8, "Hold": 0.0, "Fine right": 0.8, "Right": 2.5, "Hard right": 5.0}


def control_args(answers):
    """Typed answers -> CONTROL command arguments (the only place choices become buttons)."""
    a = {k: v["choice"] for k, v in answers.items() if k in CONTROL_HEADS}
    sideways = a.get("dodge", "Carry on")
    if sideways == "Carry on":
        sideways = a.get("strafe", "Hold")
    move = 1 if a.get("move") == "Forward" else -1 if a.get("move") == "Backward" or a.get("dodge") == "Dodge back" else 0
    strafe = -1 if sideways in ("Dodge left", "Strafe left") else 1 if sideways in ("Dodge right", "Strafe right") else 0
    weapon = {"Pistol": "PISTOL", "Shotgun": "SHOTGUN"}.get(a.get("weapon"), "FIST")
    return {"move": move, "strafe": strafe, "turn": TURN_RATE.get(a.get("turn", "Hold"), 0.0),
            "fire": a.get("fire") == "Fire", "use": a.get("use") == "Use", "weapon": weapon}
