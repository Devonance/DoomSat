"""The System One decision graph as data: what jev is asked, in which words, with which thresholds.

System Two (Sonnet) edits this between episodes; code validates every revision before it is used.
Versions live in ground/graph/: graph_current.json plus graph_v<N>.json and CHANGELOG.md.
"""
import copy
import json
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent / "graph"

DEFAULT = {
    "version": 1,
    "standing_order": "Find the level exit alive; fight what blocks the way; pick up supplies when they are needed.",
    "goal_every": 4,
    "thresholds": {
        "aligned_deg": 35, "crosshair_deg": 8, "fire_range": 450, "danger_dist": 180,
        "blocked_units": 45, "tight_units": 70, "health_critical": 35, "health_low": 50,
    },
    "turn_deg": {"Hard left": 60, "Left": 25, "Fine left": 8, "Hold": 0, "Fine right": -8, "Right": -25, "Hard right": -60, "Turn around": 150},
    "questions": {
        "steer": {
            "question": "Which way now? The map's route goes {route_where}. Space ahead: {ahead}, left: {left}, right: {right}, behind: {behind}. Stuck: {stuck}.",
            "criteria": {
                "Follow route": "Stuck is no and the space in the route's direction is clear or tight: keep following the route.",
                "Left": "The route's way is blocked or stuck is yes, and space left is clear: turn left and go that way.",
                "Right": "The route's way is blocked or stuck is yes, left is not clear, and space right is clear: turn right and go that way.",
                "Back": "The route's way is blocked or stuck is yes, neither side is clear, and space behind is clear: back out.",
                "Turn around": "Blocked or stuck with nothing known clear on any side: turn around and look."}},
        "dodge": {
            "question": "Sidestep away from an enemy? Threat: {threat} ({enemy_where}). Space left: {left}, right: {right}, behind: {behind}.",
            "criteria": {
                "Carry on": "Threat is safe. Do not dodge just because an enemy exists.",
                "Dodge left": "Threat is danger and space left is clear.",
                "Dodge right": "Threat is danger, left is not clear, space right is clear.",
                "Dodge back": "Threat is danger, sides not clear, space behind is clear."}},
        "move": {
            "question": "Advance now? Route aligned ahead: {aligned}. Space ahead: {ahead}. Stuck: {stuck}. Space behind: {behind}. Navigator: {mode}.",
            "criteria": {
                "Forward": "Route aligned ahead is yes and space ahead is clear or tight. Also forward to close on a distant enemy, and forward when at a door (walk up to it while it opens).",
                "Hold": "Route aligned ahead is no (turn first), or space ahead is blocked and not at a door, or the destination is here, or stuck with nothing known clear around (turn instead).",
                "Backward": "Stuck is yes and space behind is clear."}},
        "strafe": {
            "question": "Recovery sidestep? Stuck: yes. Space left: {left}, right: {right}.",
            "criteria": {
                "Hold": "Neither side is known clear: turn instead.",
                "Strafe left": "Space left is clear.",
                "Strafe right": "Left is blocked, space right is clear."}},
        "turn": {
            "question": "Turn to put {aim_target} in the crosshair. It is now: {aim}.",
            "criteria": {
                "Hard left": "It is far left.", "Left": "It is left.", "Fine left": "It is slightly left or just left of the crosshair.",
                "Hold": "It is centered.",
                "Fine right": "It is slightly right or just right of the crosshair.", "Right": "It is right.", "Hard right": "It is far right.",
                "Turn around": "It is behind."}},
        "fire": {
            "question": "Pull the trigger? Living enemy in the crosshair: {in_crosshair} ({enemy_where}). Equipped ammunition: {equipped_ammo}. Never shoot at the route waypoint.",
            "criteria": {
                "Fire": "Enemy in the crosshair is yes and equipped ammunition is more than zero.",
                "Hold fire": "Enemy in the crosshair is no, or equipped ammunition is zero."}},
        "weapon": {
            "question": "Which weapon? Equipped: {equipped}. Shotgun shells: {shells}. Pistol bullets: {bullets}. Owns shotgun: {owns_shotgun}.",
            "criteria": {
                "Keep": "The equipped weapon still has ammunition.",
                "Pistol": "Shotgun shells are zero and pistol bullets remain.",
                "Shotgun": "Owns a shotgun with shells and the pistol is equipped."}},
        "use": {
            "question": "Press use (open a door, flip a switch, try a wall)? Navigator: {mode}. Route blocked at arm length: {blocked_route}. Stuck: {stuck}.",
            "criteria": {
                "Use": "Route blocked at arm length is yes, or stuck is yes, or the navigator is at a door, at the exit line, or trying walls: press it.",
                "Wait": "Nothing within reach to operate."}},
        "goal": {
            "question": "Immediate priority? Level {level}. Health: {health}. Threat: {threat} ({enemy_where}). Ammunition: {ammo}. Armor: {armor}. Nearby pickups: health {health_pickup}, ammo {ammo_pickup}, armor {armor_pickup}. Unexplored frontiers: {frontiers}. Navigator: {mode}.",
            "criteria": {
                "Kill enemies": "An enemy is visible at close or mid range, health is not critical and ammunition is ready.",
                "Restore health": "Health is critical, or low with a health pickup seen and no close enemy.",
                "Stock ammo": "Ammunition is empty or scarce and an ammo pickup was seen.",
                "Add armor": "Armor is none, an armor pickup was seen, health fine, no close enemy.",
                "Explore": "No close enemy, health fine, ammunition ready: keep exploring toward the nearest frontier to find the exit. Also Explore whenever the navigator is at a door, fetching a key, heading for the exit or trying walls: let it finish.",
                "Scout": "The nearest frontier is exhausted or the player keeps getting stuck: head for a far unexplored part of the map.",
                "Upgrade weapon": "No shotgun owned, a weapon was seen, no close enemy."}},
    },
}

# Placeholders each question may use (System Two must keep at least the ones it needs; code renders with format_map).
FACT_KEYS = ["threat", "enemy_where", "left", "right", "behind", "ahead", "aligned", "stuck", "blocked_route", "aim_target",
             "aim", "in_crosshair", "equipped_ammo", "equipped", "shells", "bullets", "owns_shotgun", "health", "ammo",
             "armor", "destination", "dest_dist", "health_pickup", "ammo_pickup", "armor_pickup", "frontiers", "explored",
             "mode", "level", "keys", "route_where", "route_far"]

THRESHOLD_RANGES = {"aligned_deg": (10, 80), "crosshair_deg": (3, 20), "fire_range": (100, 1200), "danger_dist": (60, 500),
                    "blocked_units": (20, 120), "tight_units": (40, 200), "health_critical": (10, 60), "health_low": (20, 80)}


class GraphError(ValueError):
    pass


def validate(cfg):
    """Return a cleaned copy of cfg or raise GraphError. Options (criteria keys) are fixed: code maps them to buttons."""
    if not isinstance(cfg, dict):
        raise GraphError("config must be an object")
    out = copy.deepcopy(DEFAULT)
    out["standing_order"] = str(cfg.get("standing_order", out["standing_order"]))[:300]
    out["goal_every"] = int(max(1, min(20, cfg.get("goal_every", out["goal_every"]))))
    for k, (lo, hi) in THRESHOLD_RANGES.items():
        v = cfg.get("thresholds", {}).get(k, out["thresholds"][k])
        try:
            out["thresholds"][k] = float(max(lo, min(hi, float(v))))
        except (TypeError, ValueError):
            raise GraphError(f"threshold {k} is not a number")
    for k in out["turn_deg"]:
        v = cfg.get("turn_deg", {}).get(k, out["turn_deg"][k])
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise GraphError(f"turn_deg {k} is not a number")
        sign = 1 if out["turn_deg"][k] >= 0 else -1
        out["turn_deg"][k] = 0.0 if k == "Hold" else sign * max(3.0, min(180.0, abs(v)))
    dummy = {k: "x" for k in FACT_KEYS}
    for head, spec in out["questions"].items():
        new = cfg.get("questions", {}).get(head, {})
        q = str(new.get("question", spec["question"]))[:500]
        try:
            q.format_map(dummy)
        except (KeyError, ValueError, IndexError) as e:
            raise GraphError(f"question {head} uses an unknown placeholder: {e}")
        spec["question"] = q
        crit = new.get("criteria", {})
        if not isinstance(crit, dict):
            raise GraphError(f"criteria of {head} must be an object")
        for opt in spec["criteria"]:
            if opt in crit:
                spec["criteria"][opt] = str(crit[opt])[:300]
    out["version"] = int(cfg.get("version", out["version"]))
    return out


def load():
    GRAPH_DIR.mkdir(exist_ok=True)
    path = GRAPH_DIR / "graph_current.json"
    if path.exists():
        try:
            return validate(json.loads(path.read_text(encoding="utf-8")))
        except (GraphError, ValueError) as e:
            print(f"[graph] current graph invalid ({e}); using defaults")
    return save(copy.deepcopy(DEFAULT), "Initial graph: the seven control heads and the goal head as designed by hand.", model="defaults")


def save(cfg, rationale, issues=None, model=None):
    """Store a new version, update the changelog, make it current."""
    GRAPH_DIR.mkdir(exist_ok=True)
    versions = [int(p.stem.split("_v")[1]) for p in GRAPH_DIR.glob("graph_v*.json")]
    cfg = copy.deepcopy(cfg)
    cfg["version"] = max(versions + [0]) + 1
    (GRAPH_DIR / f"graph_v{cfg['version']}.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    (GRAPH_DIR / "graph_current.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    with open(GRAPH_DIR / "CHANGELOG.md", "a", encoding="utf-8") as f:
        f.write(f"\n## v{cfg['version']}" + (f" ({model})" if model else "") + f"\n{rationale}\n")
        for i in issues or []:
            f.write(f"- issue: {i}\n")
    return cfg


def diff(old, new):
    """Human-readable list of what changed between two configs."""
    out = []
    for k in ("standing_order", "goal_every"):
        if old.get(k) != new.get(k):
            out.append(f"{k}: {old.get(k)!r} -> {new.get(k)!r}")
    for k in old["thresholds"]:
        if old["thresholds"][k] != new["thresholds"][k]:
            out.append(f"thresholds.{k}: {old['thresholds'][k]} -> {new['thresholds'][k]}")
    for k in old["turn_deg"]:
        if old["turn_deg"][k] != new["turn_deg"][k]:
            out.append(f"turn_deg.{k}: {old['turn_deg'][k]} -> {new['turn_deg'][k]}")
    for head in old["questions"]:
        if old["questions"][head]["question"] != new["questions"][head]["question"]:
            out.append(f"questions.{head}.question reworded")
        for opt in old["questions"][head]["criteria"]:
            if old["questions"][head]["criteria"][opt] != new["questions"][head]["criteria"][opt]:
                out.append(f"questions.{head}.criteria[{opt}] reworded")
    return out


# JSON schema handed to System Two for its structured reply (config + rationale + issues)
def review_schema():
    q_props = {head: {"type": "object", "properties": {"question": {"type": "string"},
                                                        "criteria": {"type": "object", "properties": {opt: {"type": "string"} for opt in spec["criteria"]},
                                                                     "additionalProperties": False}},
                      "additionalProperties": False}
               for head, spec in DEFAULT["questions"].items()}
    return {
        "type": "object",
        "properties": {
            "config": {"type": "object", "properties": {
                "standing_order": {"type": "string"},
                "goal_every": {"type": "integer"},
                "thresholds": {"type": "object", "properties": {k: {"type": "number"} for k in THRESHOLD_RANGES}, "additionalProperties": False},
                "turn_deg": {"type": "object", "properties": {k: {"type": "number"} for k in DEFAULT["turn_deg"]}, "additionalProperties": False},
                "questions": {"type": "object", "properties": q_props, "additionalProperties": False},
            }, "additionalProperties": False},
            "rationale": {"type": "string", "maxLength": 800},
            "issues": {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 8},
        },
        "required": ["config", "rationale"],
        "additionalProperties": False,
    }
