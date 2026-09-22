"""The System One decision graph as data: what jev is asked, in which words, with which numbers.

jev is a System One model: it classifies a structured state in one pass. So the graph holds only the two
judgments that have no exact rule behind them -- how promising each open sector is (`sector`, a Score
asked once per offered direction) and how dangerous the scene is (`danger`, a Score) -- plus the `goal`
Choice, which code turns into a weight on the sector scores. Everything else is code.

System Two (Sonnet) rewrites the wording, the rubric levels and the numbers between episodes. `validate`
**rejects** a bad revision instead of quietly trimming it: a reviewer that cannot see its edit fail cannot
learn from it, and silent truncation is what made ten of the last eleven reviews re-fix the same bug.
Versions live in ground/graph/.
"""
import copy
import json
from pathlib import Path

import decision_graph as dg

GRAPH_DIR = Path(__file__).resolve().parent / "graph"
TEXT_LIMIT = 220          # one criterion, one instruction field: long criteria are a symptom, not a fix
ORDER_LIMIT = 200         # the standing order, carried on the goal question only
RATIONALE_LIMIT = 800
MIN_LEVELS, MAX_LEVELS = 2, 10        # a Score rubric, per the System One API

DEFAULT = {
    "version": 1,
    "model": "jev-1.13.0",            # pinned: thresholds here are tuned against this version (issue 14)
    "standing_order": "Find the level exit alive: walk into ground not yet walked, open every door, press the exit switch.",
    "goal_every": 10,
    "thresholds": {
        "crosshair_deg": 8, "fire_range": 450, "blocked_units": 48, "tight_units": 90,
        "health_critical": 35, "health_low": 50, "max_aim_deg": 60, "max_turn_deg": 135, "turn_settle_deg": 8,
    },
    # Everything here that weighs a Score is in rubric levels, the units the rubric is written in, so a
    # margin of 0.6 means six tenths of a level however many levels the rubric has.
    "select": {
        "sector_margin": 0.6,         # levels another sector must beat the committed one by to take over
        "commit_bonus": 0.3,          # extra levels asked for while a commitment is still fresh
        "commit_ticks": 6,            # ticks a commitment counts as fresh (a whole level always wins)
        # Calibrated, not guessed. Replaying 150 logged states three times (tools/replay.py --passes 3)
        # and sweeping this number gives a cost/benefit curve, not a clean cutoff: at 0.00 jev decides all
        # 141 judged states and 30 of its commands differ between identical passes; at 0.20 it decides 51
        # and 2 differ; buying the last two costs another 23 states of its authority. 0.20 is the knee.
        # Re-run the sweep against the labelled boundary set before moving it.
        "unsure_gap": 0.20,           # levels between the top two under which the answer is "cannot tell"
        "unsure_conf": 0.5,           # confidence under which the answer counts as "cannot tell"
        "goal_bonus": 1.0,            # levels the goal head is worth on the sector it favours
        "tried_penalty": 1.0,         # levels a direction loses after being held without getting anywhere
        "tried_cooldown": 40,         # ticks a direction keeps that penalty
        "danger_sidestep": 1.5,       # danger level at or above which code sidesteps
        "danger_retreat": 2.5,        # danger level at or above which code backs off
        "operate_units": 80,          # arm's length: a door this close puts the pilot in OPERATE
        "door_tries": 4,              # presses on one door before giving up on it
        "recover_ticks": 12,          # ticks in RECOVER before returning to EXPLORE regardless
        "fight_linger_ticks": 6,      # ticks FIGHT is held after the last enemy left view
    },
    "questions": {
        "sector": {
            "type": "score",
            "instructions": {
                "question": "How promising is the {dir} sector for reaching the level exit?",
                "inspect": "`sectors.{dir}`"},
            "criteria": [
                "dead end: `sectors.{dir}.space` blocked or tight, `sectors.{dir}.ground` walked before",
                "leads on but old: `sectors.{dir}.ground` walked or partly walked, `sectors.{dir}.space` open or long",
                "worth a look: `sectors.{dir}.ground` new, or `sectors.{dir}.door` close, or `sectors.{dir}.hint_here` yes",
                "the way on: `sectors.{dir}.ground` never explored, or `sectors.{dir}.exit_here` or `sectors.{dir}.key_here` yes"]},
        "danger": {
            "type": "score",
            "instructions": {
                "question": "How dangerous is the scene around the player right now?",
                "inspect": "`combat`, `player.health`, `player.ammunition`, `sectors`"},
            "criteria": [
                "no danger: `combat.enemy_visible` is no, or the one in view is far off and `player.health` is fine or full",
                "a fight to win: one enemy at mid-range, `player.health` fine or better, `player.ammunition` ready",
                "under fire: an enemy close or point blank, or `combat.enemies_in_view` above one, or `player.health` low",
                "get out: `player.health` critical, or several enemies with `player.ammunition` empty or scarce"]},
        "goal": {
            "type": "choice",
            "instructions": {"question": "What is the immediate priority?",
                             "inspect": "`player`, `combat`, `seen`, `here`"},
            "criteria": {
                "Kill enemies": {"what": "`combat.enemy_visible` yes at close or mid range, `player.health` not critical, `player.ammunition` ready"},
                "Restore health": {"what": "`player.health` critical, or low while `seen.health_pickup` is seen and no enemy is close"},
                "Stock ammo": {"what": "`player.ammunition` empty or scarce and `seen.ammo_pickup` is seen"},
                "Add armor": {"what": "`player.armor` none, `seen.armor_pickup` seen, `player.health` fine, no enemy, `seen.exit` not seen"},
                "Scout": {"what": "`seen.exit`, `seen.key` and every pickup read not seen, and `seen.ground_hint` is none: push for a different part of the level"},
                "Explore": {"what": "otherwise: keep walking into ground not yet walked, toward the exit",
                            "examples": ["no enemy, health fine, exit not seen"]}}},
    },
}

THRESHOLD_RANGES = {"crosshair_deg": (3, 20), "fire_range": (100, 1200), "blocked_units": (24, 120),
                    "tight_units": (40, 220), "health_critical": (10, 60), "health_low": (20, 80),
                    "max_aim_deg": (10, 90), "max_turn_deg": (30, 180), "turn_settle_deg": (2, 30)}
SELECT_RANGES = {"sector_margin": (0.0, 3.0), "commit_bonus": (0.0, 2.0), "commit_ticks": (1, 30),
                 "unsure_gap": (0.0, 2.0), "unsure_conf": (0.0, 1.0), "goal_bonus": (0.0, 3.0),
                 "tried_penalty": (0.0, 3.0), "tried_cooldown": (5, 200),
                 "danger_sidestep": (0.0, 9.0), "danger_retreat": (0.0, 9.0), "operate_units": (24, 120),
                 "door_tries": (1, 12), "recover_ticks": (2, 60), "fight_linger_ticks": (0, 40)}
INT_KEYS = ("commit_ticks", "tried_cooldown", "door_tries", "recover_ticks", "fight_linger_ticks")


class GraphError(ValueError):
    """A revision code refuses. The message goes back to System Two so the next attempt can fix it."""


def _text(v, name, limit=TEXT_LIMIT):
    if not isinstance(v, str):
        raise GraphError("%s must be a string" % name)
    if len(v) > limit:
        raise GraphError("%s is %d characters; the limit is %d" % (name, len(v), limit))
    return v


def _entry(v, name, depth=0):
    """Instructions and Choice criteria may be a string, an object or an array; every string is bounded."""
    if isinstance(v, str):
        return _text(v, name)
    if depth >= 3:
        raise GraphError("%s is nested too deeply" % name)
    if isinstance(v, list):
        if len(v) > 8:
            raise GraphError("%s has %d items; the limit is 8" % (name, len(v)))
        return [_entry(x, "%s[%d]" % (name, i), depth + 1) for i, x in enumerate(v)]
    if isinstance(v, dict):
        if len(v) > 8:
            raise GraphError("%s has %d fields; the limit is 8" % (name, len(v)))
        return {_text(str(k), "%s key" % name, 40): _entry(x, "%s.%s" % (name, k), depth + 1) for k, x in v.items()}
    raise GraphError("%s must be a string, an object or an array" % name)


def _number(v, name, lo, hi, as_int=False):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise GraphError("%s is not a number" % name)
    if not lo <= f <= hi:
        raise GraphError("%s=%g is outside [%g, %g]" % (name, f, lo, hi))
    return int(round(f)) if as_int else f


def _rubric(levels, name):
    if not isinstance(levels, list):
        raise GraphError("%s must be an array of level descriptions" % name)
    if not MIN_LEVELS <= len(levels) <= MAX_LEVELS:
        raise GraphError("%s has %d levels; a Score takes %d to %d" % (name, len(levels), MIN_LEVELS, MAX_LEVELS))
    return [_text(x, "%s[%d]" % (name, i)) for i, x in enumerate(levels)]


def validate(cfg):
    """Return a cleaned copy of cfg or raise GraphError. Head names, head types and option names are fixed."""
    if not isinstance(cfg, dict):
        raise GraphError("config must be an object")
    unknown = set(cfg) - set(DEFAULT) - {"rationale", "issues"}
    if unknown:
        raise GraphError("unknown config keys: %s" % ", ".join(sorted(unknown)))
    out = copy.deepcopy(DEFAULT)
    out["standing_order"] = _text(cfg.get("standing_order", out["standing_order"]), "standing_order", ORDER_LIMIT)
    out["goal_every"] = _number(cfg.get("goal_every", out["goal_every"]), "goal_every", 1, 20, as_int=True)
    out["model"] = _text(cfg.get("model", out["model"]), "model", 40)

    for section, ranges in (("thresholds", THRESHOLD_RANGES), ("select", SELECT_RANGES)):
        given = cfg.get(section, {})
        if not isinstance(given, dict):
            raise GraphError("%s must be an object" % section)
        strange = set(given) - set(ranges)
        if strange:
            raise GraphError("unknown %s: %s" % (section, ", ".join(sorted(strange))))
        for k, (lo, hi) in ranges.items():
            out[section][k] = _number(given.get(k, out[section][k]), "%s.%s" % (section, k), lo, hi,
                                      as_int=(section == "select" and k in INT_KEYS))
    if out["thresholds"]["tight_units"] <= out["thresholds"]["blocked_units"]:
        raise GraphError("thresholds.tight_units must be greater than thresholds.blocked_units")
    if out["select"]["danger_retreat"] < out["select"]["danger_sidestep"]:
        raise GraphError("select.danger_retreat must be at least select.danger_sidestep")
    if out["select"]["sector_margin"] + out["select"]["commit_bonus"] >= 1.0:
        # Code caps the effective margin below one level anyway; say so rather than silently capping it.
        raise GraphError("select.sector_margin + select.commit_bonus must stay under 1.0 rubric levels, "
                         "or a sector a whole level better could never take over the commitment")

    given_q = cfg.get("questions", {})
    if not isinstance(given_q, dict):
        raise GraphError("questions must be an object")
    strange = set(given_q) - set(DEFAULT["questions"])
    if strange:
        raise GraphError("unknown heads: %s (head names are fixed)" % ", ".join(sorted(strange)))
    for head, spec in out["questions"].items():
        new = given_q.get(head, {})
        if not isinstance(new, dict):
            raise GraphError("questions.%s must be an object" % head)
        if "type" in new and new["type"] != spec["type"]:
            raise GraphError("questions.%s.type is fixed at %s" % (head, spec["type"]))
        if "instructions" in new:
            spec["instructions"] = _entry(new["instructions"], "questions.%s.instructions" % head)
        if "criteria" in new:
            if spec["type"] == "score":
                spec["criteria"] = _rubric(new["criteria"], "questions.%s.criteria" % head)
            else:
                crit = new["criteria"]
                if not isinstance(crit, dict):
                    raise GraphError("questions.%s.criteria must be an object" % head)
                strange = set(crit) - set(spec["criteria"])
                if strange:
                    raise GraphError("unknown options on %s: %s (option names are fixed)" % (head, ", ".join(sorted(strange))))
                for opt, v in crit.items():
                    spec["criteria"][opt] = _entry(v, "questions.%s.criteria[%s]" % (head, opt))

    bad = dg.lint(out)          # rule 5: a criterion may only name fields that exist in the state
    if bad:
        raise GraphError("criteria name state fields that do not exist: %s" % ", ".join(bad))
    out["version"] = _number(cfg.get("version", out["version"]), "version", 0, 1e6, as_int=True)
    return out


def load():
    GRAPH_DIR.mkdir(exist_ok=True)
    path = GRAPH_DIR / "graph_current.json"
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            if set(cfg.get("questions", {})) == set(DEFAULT["questions"]):
                return validate(cfg)
            print("[graph] current graph is from an older layout; using defaults")
        except (GraphError, ValueError) as e:
            print("[graph] current graph invalid (%s); using defaults" % e)
    return save(copy.deepcopy(DEFAULT),
                "Initial graph: one Score per open sector, one danger Score, one goal Choice; every exact rule in code.",
                model="defaults")


def save(cfg, rationale, issues=None, model=None):
    """Store a new version, update the changelog, make it current."""
    GRAPH_DIR.mkdir(exist_ok=True)
    versions = [int(p.stem.split("_v")[1]) for p in GRAPH_DIR.glob("graph_v*.json")]
    cfg = copy.deepcopy(cfg)
    cfg["version"] = max(versions + [0]) + 1
    (GRAPH_DIR / ("graph_v%d.json" % cfg["version"])).write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    (GRAPH_DIR / "graph_current.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    with open(GRAPH_DIR / "CHANGELOG.md", "a", encoding="utf-8") as f:
        f.write("\n## v%d%s\n%s\n" % (cfg["version"], (" (%s)" % model) if model else "", rationale))
        for i in issues or []:
            f.write("- issue: %s\n" % i)
    return cfg


def diff(old, new):
    """Human-readable list of what changed between two configs."""
    out = []
    for k in ("standing_order", "goal_every", "model"):
        if old.get(k) != new.get(k):
            out.append("%s: %r -> %r" % (k, old.get(k), new.get(k)))
    for section in ("thresholds", "select"):
        for k in old[section]:
            if old[section][k] != new[section][k]:
                out.append("%s.%s: %s -> %s" % (section, k, old[section][k], new[section][k]))
    for head, spec in old["questions"].items():
        if spec["instructions"] != new["questions"][head]["instructions"]:
            out.append("questions.%s.instructions reworded" % head)
        if spec["type"] == "score":
            if spec["criteria"] != new["questions"][head]["criteria"]:
                out.append("questions.%s rubric rewritten (%d -> %d levels)"
                           % (head, len(spec["criteria"]), len(new["questions"][head]["criteria"])))
        else:
            for opt in spec["criteria"]:
                if spec["criteria"][opt] != new["questions"][head]["criteria"].get(opt):
                    out.append("questions.%s.criteria[%s] reworded" % (head, opt))
    return out


# JSON schema handed to System Two for its structured reply (config + rationale + issues).
# Every bound code enforces is in the schema, so a rejected edit is visible before it is sent (issues 1 and 2).
def review_schema():
    text = {"type": "string", "maxLength": TEXT_LIMIT}
    entry = {"anyOf": [text, {"type": "object"}, {"type": "array"}]}
    rubric = {"type": "array", "minItems": MIN_LEVELS, "maxItems": MAX_LEVELS, "items": text}
    q_props = {}
    for head, spec in DEFAULT["questions"].items():
        crit = rubric if spec["type"] == "score" else {
            "type": "object", "properties": {opt: entry for opt in spec["criteria"]}, "additionalProperties": False}
        q_props[head] = {"type": "object", "properties": {"instructions": entry, "criteria": crit},
                         "additionalProperties": False}
    numbers = lambda ranges: {"type": "object", "additionalProperties": False,
                              "properties": {k: {"type": "number", "minimum": lo, "maximum": hi}
                                             for k, (lo, hi) in ranges.items()}}
    return {
        "type": "object",
        "properties": {
            "config": {"type": "object", "additionalProperties": False, "properties": {
                "standing_order": {"type": "string", "maxLength": ORDER_LIMIT},
                "goal_every": {"type": "integer", "minimum": 1, "maximum": 20},
                "thresholds": numbers(THRESHOLD_RANGES),
                "select": numbers(SELECT_RANGES),
                "questions": {"type": "object", "properties": q_props, "additionalProperties": False},
            }},
            "rationale": {"type": "string", "maxLength": RATIONALE_LIMIT},
            "issues": {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 8},
        },
        "required": ["config", "rationale"],
        "additionalProperties": False,
    }


def limits_note():
    """The same bounds in one paragraph, so System Two is told rather than left to discover them."""
    return ("Bounds code enforces (a revision outside them is rejected and sent back): every criterion and "
            "instruction string at most %d characters; the standing order at most %d; a Score rubric %d to %d "
            "levels; %s; %s. Head names, head types and option names are fixed. Criteria may only name state "
            "fields in backticks that exist: %s."
            % (TEXT_LIMIT, ORDER_LIMIT, MIN_LEVELS, MAX_LEVELS,
               ", ".join("thresholds.%s in [%g, %g]" % (k, lo, hi) for k, (lo, hi) in THRESHOLD_RANGES.items()),
               ", ".join("select.%s in [%g, %g]" % (k, lo, hi) for k, (lo, hi) in SELECT_RANGES.items()),
               ", ".join(sorted(_state_field_names()))))


def _state_field_names():
    out = []
    for top, fields in dg.STATE_PATHS.items():
        if isinstance(fields, dict):
            out += ["%s.<direction>.%s" % (top, f) for f in fields["*"]]
        else:
            out += ["%s.%s" % (top, f) for f in fields]
    return out
