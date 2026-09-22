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
        "threat_dist": 400,           # an enemy further off than this is scenery, not a fight
        "health_critical": 35, "health_low": 50, "max_aim_deg": 60,
        # 180, not 135: "behind" means 180, and clamping it left the player facing sideways and needing
        # another correction, which reads as a spin.
        "max_turn_deg": 180, "turn_settle_deg": 8,
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
        # Measured on the first live run (tools/churn_check.py), as sectors of 8 whose word changed
        # between consecutive decisions: 1 (off) 3.41 space / 3.05 ground, 2 -> 2.67 / 2.60,
        # 3 -> 2.25 / 2.28, 4 -> 2.00 / 2.07. The cost is lag, but only on good news -- a worse
        # reading is always believed at once -- so 3 buys a third less churn without risking a wall.
        "confirm_ticks": 3,           # senses a *better* sector word needs before it replaces the held one
        "danger_sidestep": 1.5,       # danger level at or above which code sidesteps
        "danger_retreat": 2.5,        # danger level at or above which code backs off
        "operate_units": 80,          # arm's length: a door this close puts the pilot in OPERATE
        "approach_ticks": 16,         # ticks APPROACH may hold before falling back to EXPLORE
        "door_tries": 4,              # presses on one door before giving up on it
        "door_retry_ticks": 80,       # ticks before a door that refused to open is worth trying again
        "idle_ticks": 8,              # decisions without moving before the pilot declares itself stuck
        "recover_ticks": 12,          # ticks in RECOVER before returning to EXPLORE regardless
        "fight_linger_ticks": 6,      # ticks FIGHT is held after the last enemy left view
        # Charter 3.1: an intent outlives the decision that made it, so the player never stands still
        # waiting for the next one. Long enough to cover a slow answer, short enough that a stale plan
        # stops rather than runs into a wall; the executor drops to safe behaviour when it lapses.
        "intent_ttl_ms": 1500,
        "target_give_up_ticks": 60,   # ticks a target the pilot gave up on stays unattractive
    },
    "questions": {
        "sector": {
            "type": "score",
            "instructions": {
                "question": "How promising is the {dir} sector for reaching the level exit?",
                "inspect": "`sectors.{dir}`"},
            # Nine levels, not four. With four, almost everything early in a level is "never explored" and
            # lands in the top one: on the first live run the scores clustered at 2.7 to 2.9 and the unsure
            # band fired on 43% of ticks. Worse, a visible exit tied with any fresh corridor. A Score takes
            # up to ten levels, so the exit gets its own, then the key, and unexplored ground is split by
            # how much room it has.
            "criteria": [
                "dead end: `sectors.{dir}.space` blocked or tight and `sectors.{dir}.ground` walked before",
                "walked before, but `sectors.{dir}.space` is open or long, so it leads on",
                "`sectors.{dir}.ground` partly walked with `sectors.{dir}.space` open or long",
                "`sectors.{dir}.hint_here` is yes: the ground crew pushed exploration this way",
                "`sectors.{dir}.ground` is new",
                "`sectors.{dir}.ground` is never explored but `sectors.{dir}.space` is tight",
                "`sectors.{dir}.door` is close or point blank: a door that leads somewhere unwalked",
                "`sectors.{dir}.ground` is never explored and `sectors.{dir}.space` is open or long",
                "`sectors.{dir}.exit_here` is yes, or `sectors.{dir}.key_here` is yes: the way out"]},
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
        # Charter 3.3. One Score per candidate the payload offers, on a shared rubric, in one call; code
        # picks with commitment and the unsure band. This is the navigator now -- the sector head below is
        # kept because the executor still uses it as local obstacle input and because every baseline before
        # the charter was measured with it.
        #
        # The levels are written as TRADE-OFFS, and that is the whole design. The first draft of this
        # rubric was a level-by-level restatement of `targeting.rule_score`, which guarantees the only
        # thing the model can do is reproduce the rule -- the same trap the sector rubric fell into, where
        # sharpening it drove agreement with ten lines of code from 79% to 89% and made the model
        # redundant by construction. A question worth half a second of latency has to weigh things no
        # single field settles: what is standing near the target against how much health and ammunition
        # there is to spend, how far it is compared with the other options rather than in the absolute,
        # and whether a detour answers a need that is real right now.
        #
        # `rule_score` is deliberately simpler than this: exit, then key, then an untried door, then the
        # nearest unexplored edge, and nothing else. It is the null hypothesis, not a shadow of the rubric.
        "target": {
            "type": "score",
            "instructions": {
                "question": "How well does going to {t} serve finding the level exit alive, weighed against "
                            "the other targets and what the player has left?",
                "inspect": "`targets.{t}`, the other entries in `targets`, `here`, `needs`"},
            "criteria": [
                "not reachable in any useful sense: `targets.{t}.locked` names a key the player does not hold, or `targets.{t}.tried_before` is several times and it has not opened",
                "a bad trade: `targets.{t}.threat` is dangerous or deadly while `here.health` is critical or low, or `here.ammunition` is empty",
                "not worth the walk: `targets.{t}.relative_distance` is the furthest and there is little behind it, with nothing in `needs` that it answers",
                "would be worth it nearer: it answers something in `needs`, but it is the furthest of the targets and `targets.{t}.threat` is not none",
                "a fair next step: unexplored ground at a distance in line with the others, and nothing dangerous standing near it",
                "worth a detour: it answers a need the player actually has, it is not the furthest, and `targets.{t}.threat` is none or a straggler",
                "the obvious move: close or the nearest of them, a lot of unseen ground behind it, and nothing near it worth avoiding",
                "the way on: an untried door or a key the player is missing, and what `targets.{t}.threat` says is standing there is worth facing with the health and ammunition in `here`",
                "the way out: the level exit, and nothing between here and it that `here.health` and `here.ammunition` could not survive"]},
        # Charter 3.3 and 4. The charter's own example of a question worth asking: "three imps and a
        # sergeant between me and the only frontier, 38 health, 12 shells, armor behind me. Fight, detour
        # or retreat?" No field settles that, and the exact rule underneath it (retreat when health is
        # critical or the ammunition is gone) is a backstop, not an answer -- it was written in a hurry
        # after the first executor baseline charged everything it met and died 142 times.
        "engage": {
            "type": "choice",
            "instructions": {
                "question": "The player has met something. What should it do about it?",
                "inspect": "`combat`, `here`, `targets`"},
            "criteria": {
                "Fight where I stand": {
                    "what": "`combat.threat` is worth the ammunition and `here.health` can take the trade, "
                            "and there is room to shoot from"},
                "Fight while moving": {
                    "what": "worth fighting but standing still is the danger: `combat.distance` is close, "
                            "or `combat.count` is more than one"},
                "Break off and go round": {
                    "what": "the fight is not the point: `targets` has somewhere to be and `combat.threat` "
                            "is avoidable at `combat.distance`"},
                "Retreat": {
                    "what": "`here.health` is critical or low against a threat that is dangerous or deadly, "
                            "or `here.ammunition` is empty or scarce with more than one of them",
                    "examples": ["health critical, two imps close, shotgun empty"]}}},
        "weapon": {
            "type": "choice",
            "instructions": {
                "question": "Which weapon suits this fight?",
                "inspect": "`combat`, `here.ammunition`"},
            "criteria": {
                "Shotgun": {"what": "`combat.distance` close or mid-range and shells are in hand: the pellets "
                                    "all land"},
                "Chaingun": {"what": "`combat.distance` far, or several of them, and bullets are in hand: the "
                                     "stagger is worth more than the damage"},
                "Pistol": {"what": "nothing better is loaded"},
                "Fist": {"what": "`combat.distance` is point blank and nothing is loaded at all"}}},
        "need": {
            "type": "score",
            "instructions": {
                "question": "How badly does the player need {need} right now?",
                "inspect": "`needs.{need}`, `here`, `combat`"},
            "criteria": [
                "`needs.{need}` is none: no reason to spend a step on it",
                "`needs.{need}` is nice to have: worth taking if it is on the way",
                "`needs.{need}` is wanted: worth a short detour",
                "`needs.{need}` is urgent: worth turning away from the exit for"]},
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

THRESHOLD_RANGES = {"crosshair_deg": (3, 20), "fire_range": (100, 1200), "threat_dist": (100, 900), "blocked_units": (24, 120),
                    "tight_units": (40, 220), "health_critical": (10, 60), "health_low": (20, 80),
                    "max_aim_deg": (10, 90), "max_turn_deg": (135, 180), "turn_settle_deg": (2, 30)}
SELECT_RANGES = {"sector_margin": (0.0, 3.0), "commit_bonus": (0.0, 2.0), "commit_ticks": (1, 30),
                 "unsure_gap": (0.0, 2.0), "unsure_conf": (0.0, 1.0), "goal_bonus": (0.0, 3.0),
                 "tried_penalty": (0.0, 3.0), "tried_cooldown": (5, 200), "confirm_ticks": (1, 6),
                 "danger_sidestep": (0.0, 9.0), "danger_retreat": (0.0, 9.0), "operate_units": (24, 120),
                 "approach_ticks": (2, 60),
                 "door_tries": (1, 12), "door_retry_ticks": (10, 400), "idle_ticks": (3, 40), "recover_ticks": (2, 60), "fight_linger_ticks": (0, 40),
                 "intent_ttl_ms": (300, 5000), "target_give_up_ticks": (10, 400)}
INT_KEYS = ("commit_ticks", "tried_cooldown", "door_tries", "recover_ticks", "fight_linger_ticks",
            "confirm_ticks", "approach_ticks", "door_retry_ticks", "idle_ticks",
            "intent_ttl_ms", "target_give_up_ticks")


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


def save_candidate(cfg, rationale, issues=None, model=None, report=None):
    """Store a revision *without* making it current.

    Promoting a review off a single three-minute episode is the mistake the audit criticised in the old
    loop, so by default the pilot keeps flying the graph it has and the candidate waits for
    `tools/promote_graph.py`, which replays both against logged states before swapping them.
    """
    GRAPH_DIR.mkdir(exist_ok=True)
    out = GRAPH_DIR / "candidates"
    out.mkdir(exist_ok=True)
    n = 1 + max([int(p.stem.split("_c")[1]) for p in out.glob("graph_c*.json")] + [0])
    path = out / ("graph_c%d.json" % n)
    path.write_text(json.dumps({"config": cfg, "rationale": rationale, "issues": issues or [],
                                "model": model, "from_version": cfg.get("version"),
                                "report": report}, indent=1), encoding="utf-8")
    return path


def load_candidate(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate(data["config"]), data


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
