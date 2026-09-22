"""The System One decision graph for the Doom pilot, driven by graph_config.

Code turns telemetry numbers into a small structured state (words, not numbers), asks jev one narrow
typed question per head in a single call, and combines the answers into the CONTROL command with
deterministic rules. jev judges; it never reasons, plans or remembers. Which heads are asked and which
options are on the menu is decided by code (a Backward that cannot apply is not offered).

There is no route: the `way` head is the navigation. jev picks the direction from what is open around
the player, how much of it has been walked, what is at arm's length, and where the exit, a key or the
ground's hint lie. Code adds hysteresis from the option probabilities so the choice does not flicker.
"""
import copy

GOALS = ["EXPLORE", "KILL_ENEMY", "STOCK_AMMO", "RESTORE_HEALTH", "ADD_ARMOR", "UPGRADE_WEAPON", "SCOUT", "HOLD"]
CONTROL_HEADS = ("way", "advance", "use", "fire", "dodge", "turn", "weapon")
GOAL_FROM_CHOICE = {"Kill enemies": "KILL_ENEMY", "Restore health": "RESTORE_HEALTH", "Stock ammo": "STOCK_AMMO",
                    "Add armor": "ADD_ARMOR", "Explore": "EXPLORE", "Scout": "SCOUT", "Upgrade weapon": "UPGRADE_WEAPON"}
AHEAD_WORDS = {"NOTHING": "nothing near", "WALL": "a wall", "DOOR": "a door", "EXIT": "the exit switch",
               "LOCKED": "a locked door", "BARRIER": "bars or a blocked doorway the map does not show", "THING": "a monster or a barrel"}
WAY_TURN = {"Ahead": 0.0, "Left": 90.0, "Right": -90.0, "Back": 0.0, "Turn around": 180.0}


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


def where_words(b, d):
    """Where something seen lies: a coarse direction and a distance, or none."""
    if not d:
        return {"where": "not seen"}
    a = abs(b)
    direction = "ahead" if a <= 30 else ("to the left" if b > 0 else "to the right") if a <= 120 else "behind"
    return {"where": direction, "distance": dist_words(d)}


def ground_words(pct):
    return "new" if pct >= 60 else "partly walked" if pct >= 25 else "walked before"


def build_state(t, goal, cfg):
    """The structured state jev classifies: only what the heads need, in words."""
    th = cfg["thresholds"]
    space = lambda c: "blocked" if c < th["blocked_units"] else "tight" if c < th["tight_units"] else "open"
    yn = lambda b: "yes" if b else "no"
    enemy = t.get("ENEMY_COUNT", 0) > 0
    e_bearing, e_dist = t.get("ENEMY_BEARING", 0.0), t.get("ENEMY_DIST", 0)
    shells, bullets, hp = t.get("SHELLS", 0), t.get("BULLETS", 0), t.get("HEALTH", 100)
    ahead_kind = str(t.get("AHEAD_KIND", "NOTHING"))
    ahead_units = min(t.get("CLEAR_FWD", 999), t.get("CLEAR_MAP_FWD", 999))
    hint_rel = t.get("HINT_REL", 0)
    keys = int(t.get("KEYS", 0) or 0)
    held = [name for bit, name in ((1, "red"), (2, "blue"), (4, "yellow")) if keys & bit]
    ahead = {"space": space(ahead_units), "ground": ground_words(t.get("NEW_FWD", 100)),
             "at_arms_length": AHEAD_WORDS.get(ahead_kind, ahead_kind.lower())}
    if ahead_kind != "NOTHING":
        ahead["at_arms_length_distance"] = dist_words(t.get("AHEAD_DIST", 0))
    return {
        "standing_order": cfg["standing_order"],
        "committed_goal": goal.replace("_", " ").lower(),
        "player": {"health": "critical" if hp < th["health_critical"] else "low" if hp < th["health_low"] else "fine" if hp < 90 else "full",
                   "armor": "none" if t.get("ARMOR", 0) <= 0 else "some" if t.get("ARMOR", 0) < 50 else "good",
                   "ammunition": "empty" if shells == 0 and bullets == 0 else "scarce" if shells == 0 and bullets < 12 else "ready",
                   "equipped_weapon": str(t.get("WEAPON", "PISTOL")).lower(),
                   "equipped_ammo": shells if str(t.get("WEAPON")) == "SHOTGUN" else bullets,
                   "shotgun_shells": shells, "pistol_bullets": bullets, "owns_shotgun": yn(t.get("OWN_SHOTGUN", False))},
        "combat": {"enemy_visible": yn(enemy),
                   "enemy_where": (bearing_words(e_bearing) + ", " + dist_words(e_dist)) if enemy else "no enemy in view",
                   "threat": "danger" if enemy and e_dist < th["danger_dist"] else "safe",
                   "enemy_in_crosshair": yn(enemy and abs(e_bearing) <= th["crosshair_deg"] and e_dist <= th["fire_range"])},
        "surroundings": {"ahead": ahead,
                         "left": {"space": space(t.get("CLEAR_LEFT", 999)), "ground": ground_words(t.get("NEW_LEFT", 100))},
                         "right": {"space": space(t.get("CLEAR_RIGHT", 999)), "ground": ground_words(t.get("NEW_RIGHT", 100))},
                         "behind": {"space": space(t.get("CLEAR_BACK", 999)), "ground": ground_words(t.get("NEW_BACK", 100))}},
        "stuck": yn(t.get("STUCK", False)),
        "seen": {"exit": where_words(t.get("EXIT_BEARING", 0.0), t.get("EXIT_DIST", 0)),
                 "key": where_words(t.get("KEY_BEARING", 0.0), t.get("KEY_DIST", 0)),
                 "health_pickup": where_words(t.get("HEALTH_BEARING", 0.0), t.get("HEALTH_ITEM_DIST", 0)),
                 "ammo_pickup": where_words(t.get("AMMO_BEARING", 0.0), t.get("AMMO_ITEM_DIST", 0)),
                 "armor_pickup": where_words(t.get("ARMOR_BEARING", 0.0), t.get("ARMOR_ITEM_DIST", 0)),
                 "ground_hint": ("ahead" if abs(hint_rel) <= 30 else ("to the left" if hint_rel > 0 else "to the right") if abs(hint_rel) <= 120 else "behind")
                 if t.get("HINT_ACTIVE", False) else "none",
                 "level": str(t.get("LEVEL", 1)), "keys_held": " and ".join(held) if held else "none"},
    }


def _question(cfg, head, options=None):
    spec = cfg["questions"][head]
    q = {"type": spec["type"], "instructions": copy.deepcopy(spec["instructions"])}
    crit = spec["criteria"]
    if spec["type"] == "choice":
        q["criteria"] = {k: copy.deepcopy(v) for k, v in crit.items() if options is None or k in options}
    else:
        q["criteria"] = copy.deepcopy(crit)
    return q


def control_questions(t, goal, cfg):
    """The control heads for this tick. Code decides which heads are asked and which options are on the menu."""
    s = build_state(t, goal, cfg)
    sur = s["surroundings"]
    ways = ["Ahead", "Left", "Right", "Back", "Turn around"]
    if sur["behind"]["space"] == "blocked":
        ways.remove("Back")
    heads = {"way": _question(cfg, "way", ways), "advance": _question(cfg, "advance"), "fire": _question(cfg, "fire"),
             "weapon": _question(cfg, "weapon")}
    if str(t.get("AHEAD_KIND", "NOTHING")) in ("DOOR", "EXIT", "LOCKED") or s["stuck"] == "yes":
        heads["use"] = _question(cfg, "use")
    if s["combat"]["enemy_visible"] == "yes":
        dodges = ["Carry on"] + (["Dodge left"] if sur["left"]["space"] == "open" else []) + \
                 (["Dodge right"] if sur["right"]["space"] == "open" else []) + (["Dodge back"] if sur["behind"]["space"] == "open" else [])
        heads["dodge"] = _question(cfg, "dodge", dodges)
        if goal == "KILL_ENEMY":
            heads["turn"] = _question(cfg, "turn")
    return heads


def goal_question(t, cfg):
    return {"goal": _question(cfg, "goal")}


def answer_label(v):
    """A printable answer for any head type: the choice, or yes/no for a Noul."""
    if not isinstance(v, dict):
        return str(v)
    if v.get("type") == "noul" or "noul" in v:
        return "yes" if float(v.get("noul", 0.0)) >= 0.5 else "no"
    return v.get("choice")


def answer_confidence(v):
    if not isinstance(v, dict):
        return 0.0
    if "noul" in v:
        p = float(v["noul"])
        return max(p, 1.0 - p)
    return float(v.get("confidence", 0.0))


def control_args(answers, cfg, t=None, memory=None):
    """Typed answers -> CONTROL command arguments (the only place choices become buttons). `memory` keeps the last
    direction so the way only changes when jev is clearly surer of the new one (hysteresis on the probabilities)."""
    memory = memory if memory is not None else {}
    a = {k: v for k, v in answers.items() if k in CONTROL_HEADS}
    way_ans = a.get("way", {})
    way = way_ans.get("choice", "Ahead")
    probs = way_ans.get("probabilities") or {}
    advance = float(a.get("advance", {}).get("noul", 1.0)) >= 0.5
    prev = memory.get("way")
    prev_ok = prev in probs and probs.get(prev, 0.0) >= 0.3 and not (prev == "Ahead" and not advance)
    if prev and prev != way and prev_ok and probs.get(way, 0.0) < probs.get(prev, 0.0) + float(cfg.get("way_margin", 0.15)):
        way = prev
    memory["way"] = way
    use = float(a.get("use", {}).get("noul", 0.0)) >= 0.5 if "use" in a else False
    fire = float(a.get("fire", {}).get("noul", 0.0)) >= 0.5
    dodge = a.get("dodge", {}).get("choice", "Carry on")
    weapon = {"Pistol": "PISTOL", "Shotgun": "SHOTGUN"}.get(a.get("weapon", {}).get("choice"), "FIST")
    turn = WAY_TURN.get(way, 0.0)
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
        move = -1
    strafe = -1 if dodge == "Dodge left" else 1 if dodge == "Dodge right" else 0
    if dodge == "Dodge back":
        move = -1
    return {"move": move, "strafe": strafe, "turn": turn, "fire": fire, "use": use, "weapon": weapon}
