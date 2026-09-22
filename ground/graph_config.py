"""The System One decision graph as data: what jev is asked, in which words, with which thresholds.

jev is a System One model: it classifies a structured state in one pass. So every head is one narrow
question, options carry contrastive criteria (what / not_for / examples), yes-no heads are Nouls, and
code combines the answers. System Two (Sonnet) edits the wording, criteria and thresholds between
episodes; code validates every revision before it is used. Versions live in ground/graph/.
"""
import copy
import json
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent / "graph"

DEFAULT = {
    "version": 1,
    "standing_order": "Find the level exit alive, fast: keep moving into ground not yet walked, open every door, press the exit switch.",
    "goal_every": 8,
    "thresholds": {
        "aligned_deg": 35, "crosshair_deg": 8, "fire_range": 450, "danger_dist": 180,
        "blocked_units": 48, "tight_units": 90, "health_critical": 35, "health_low": 50,
    },
    "turn_deg": {"Hard left": 60, "Left": 25, "Fine left": 8, "Hold": 0, "Fine right": -8, "Right": -25, "Hard right": -60, "Turn around": 150},
    "way_margin": 0.15,
    "questions": {
        "way": {
            "type": "choice",
            "instructions": {
                "question": "Which of the offered directions should the player go now? Each option is a direction around the player, with what the map says there under `now`.",
                "inspect": "surroundings, seen.exit, seen.key, seen.ground_hint, stuck",
                "focus": "Prefer the direction of the exit, then a door, then unexplored ground (never seen), then long space with new ground, then open new ground. A walked-before direction only when nothing else is offered."},
            "criteria": {
                "direction": {"what": "go {dir}: best when its ground is unexplored, or its space is long or open with new ground, or the exit, a door, the key or ground_hint lies {dir}",
                              "not_for": "its ground is walked before while another offered direction is unexplored or new",
                              "examples": ["{dir}: ground unexplored (never seen)", "{dir}: space long, ground new", "exit {dir}"]}}},
        "advance": {
            "type": "noul",
            "instructions": {"question": "Should the player walk forward right now?", "inspect": "surroundings.ahead, stuck"},
            "criteria": {
                "true": {"what": "surroundings.ahead.space is open or tight, or a door or the exit switch is at arm's length ahead (walk up to it)",
                         "examples": ["ahead open", "ahead tight", "a door at arm's length"]},
                "false": {"what": "surroundings.ahead.space is blocked by a wall, bars, a barrel or a monster at point blank, or the player is stuck",
                          "examples": ["ahead blocked, a wall at arm's length", "stuck yes"]}}},
        "use": {
            "type": "noul",
            "instructions": {"question": "Is there something to operate at arm's length ahead?", "inspect": "surroundings.ahead.at_arms_length, stuck"},
            "criteria": {
                "true": {"what": "a door, the exit switch or a locked door is at arm's length ahead, or the player is stuck (try the wall)",
                         "examples": ["a door at arm's length", "the exit switch at arm's length"]},
                "false": {"what": "nothing near, or a plain wall, bars or a monster ahead", "examples": ["nothing near", "a wall"]}}},
        "fire": {
            "type": "noul",
            "instructions": {"question": "Should the trigger be pulled?", "inspect": "combat, player.equipped_ammo"},
            "criteria": {
                "true": {"what": "combat.enemy_in_crosshair is yes and player.equipped_ammo is more than zero"},
                "false": {"what": "no enemy in the crosshair, or equipped ammunition is zero"}}},
        "dodge": {
            "type": "choice",
            "instructions": {"question": "Sidestep to avoid the enemy?", "inspect": "combat, surroundings"},
            "criteria": {
                "Carry on": {"what": "combat.threat is safe", "not_for": "a close enemy attacking"},
                "Dodge left": {"what": "combat.threat is danger and surroundings.left is open"},
                "Dodge right": {"what": "combat.threat is danger, left not open, surroundings.right open"},
                "Dodge back": {"what": "combat.threat is danger, sides not open, surroundings.behind open"}}},
        "turn": {
            "type": "choice",
            "instructions": {"question": "Turn to put the enemy in the crosshair. Where is it now?", "inspect": "combat.enemy_where"},
            "criteria": {
                "Hard left": {"what": "far left"}, "Left": {"what": "left"}, "Fine left": {"what": "slightly left or just left of the crosshair"},
                "Hold": {"what": "centered"},
                "Fine right": {"what": "slightly right or just right of the crosshair"}, "Right": {"what": "right"}, "Hard right": {"what": "far right"},
                "Turn around": {"what": "behind"}}},
        "weapon": {
            "type": "choice",
            "instructions": {"question": "Which weapon?", "inspect": "player"},
            "criteria": {
                "Keep": {"what": "the equipped weapon still has ammunition"},
                "Pistol": {"what": "shotgun shells are zero and pistol bullets remain"},
                "Shotgun": {"what": "owns a shotgun with shells and the pistol is equipped"}}},
        "goal": {
            "type": "choice",
            "instructions": {"question": "What is the immediate priority?", "inspect": "player, combat, seen"},
            "criteria": {
                "Kill enemies": {"what": "an enemy visible at close or mid range, health not critical, ammunition ready"},
                "Restore health": {"what": "health critical, or low with a health pickup seen close and no close enemy"},
                "Stock ammo": {"what": "ammunition empty or scarce and an ammo pickup seen close"},
                "Add armor": {"what": "armor none, an armor pickup seen close, health fine, no close enemy, exit not seen yet"},
                "Explore": {"what": "otherwise: keep exploring toward new ground and the exit", "examples": ["no enemy, health fine, exit not seen"]}}},
    },
}

THRESHOLD_RANGES = {"aligned_deg": (10, 80), "crosshair_deg": (3, 20), "fire_range": (100, 1200), "danger_dist": (60, 500),
                    "blocked_units": (24, 120), "tight_units": (40, 220), "health_critical": (10, 60), "health_low": (20, 80)}


class GraphError(ValueError):
    pass


def _clean_entry(v, depth=0):
    """Instructions/criteria may be strings, objects or arrays (System One understands structure); bound their size."""
    if isinstance(v, str):
        return v[:400]
    if isinstance(v, list) and depth < 3:
        return [_clean_entry(x, depth + 1) for x in v[:8]]
    if isinstance(v, dict) and depth < 3:
        return {str(k)[:40]: _clean_entry(x, depth + 1) for k, x in list(v.items())[:8]}
    return str(v)[:400]


def validate(cfg):
    """Return a cleaned copy of cfg or raise GraphError. Heads, their types and option names are fixed: code maps them to buttons."""
    if not isinstance(cfg, dict):
        raise GraphError("config must be an object")
    out = copy.deepcopy(DEFAULT)
    out["standing_order"] = str(cfg.get("standing_order", out["standing_order"]))[:300]
    out["goal_every"] = int(max(1, min(20, cfg.get("goal_every", out["goal_every"]))))
    try:
        out["way_margin"] = float(max(0.0, min(0.5, float(cfg.get("way_margin", out["way_margin"])))))
    except (TypeError, ValueError):
        raise GraphError("way_margin is not a number")
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
    for head, spec in out["questions"].items():
        new = cfg.get("questions", {}).get(head, {})
        if "instructions" in new:
            spec["instructions"] = _clean_entry(new["instructions"])
        crit = new.get("criteria", {})
        if not isinstance(crit, dict):
            raise GraphError(f"criteria of {head} must be an object")
        for opt in spec["criteria"]:
            if opt in crit:
                spec["criteria"][opt] = _clean_entry(crit[opt])
    out["version"] = int(cfg.get("version", out["version"]))
    return out


def load():
    GRAPH_DIR.mkdir(exist_ok=True)
    path = GRAPH_DIR / "graph_current.json"
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            if set(cfg.get("questions", {})) == set(DEFAULT["questions"]) and "way" in cfg["questions"]:
                return validate(cfg)
            print("[graph] current graph is from an older layout; using defaults")
        except (GraphError, ValueError) as e:
            print(f"[graph] current graph invalid ({e}); using defaults")
    return save(copy.deepcopy(DEFAULT), "Initial graph: one narrow question per head, structured criteria, Nouls for yes-no heads.", model="defaults")


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
    for k in ("standing_order", "goal_every", "way_margin"):
        if old.get(k) != new.get(k):
            out.append(f"{k}: {old.get(k)!r} -> {new.get(k)!r}")
    for k in old["thresholds"]:
        if old["thresholds"][k] != new["thresholds"][k]:
            out.append(f"thresholds.{k}: {old['thresholds'][k]} -> {new['thresholds'][k]}")
    for k in old["turn_deg"]:
        if old["turn_deg"][k] != new["turn_deg"][k]:
            out.append(f"turn_deg.{k}: {old['turn_deg'][k]} -> {new['turn_deg'][k]}")
    for head in old["questions"]:
        if old["questions"][head]["instructions"] != new["questions"][head]["instructions"]:
            out.append(f"questions.{head}.instructions reworded")
        for opt in old["questions"][head]["criteria"]:
            if old["questions"][head]["criteria"][opt] != new["questions"][head]["criteria"].get(opt):
                out.append(f"questions.{head}.criteria[{opt}] reworded")
    return out


# JSON schema handed to System Two for its structured reply (config + rationale + issues)
def review_schema():
    entry = {"anyOf": [{"type": "string"}, {"type": "object"}, {"type": "array"}]}
    q_props = {head: {"type": "object", "properties": {"instructions": entry,
                                                        "criteria": {"type": "object", "properties": {opt: entry for opt in spec["criteria"]},
                                                                     "additionalProperties": False}},
                      "additionalProperties": False}
               for head, spec in DEFAULT["questions"].items()}
    return {
        "type": "object",
        "properties": {
            "config": {"type": "object", "properties": {
                "standing_order": {"type": "string"},
                "goal_every": {"type": "integer"},
                "way_margin": {"type": "number"},
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
