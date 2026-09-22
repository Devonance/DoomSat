"""The System One decision graph for the DoomSat pilot: the state, the questions, and the code that acts.

jev classifies. It never reasons, plans or remembers, so this module keeps to four rules:

  1. every fact a criterion mentions exists as a field of the state (`lint` proves it before a graph ships);
  2. anything that depends on the past is computed here and written as a present-tense field (`NavMemory`);
  3. any rule code can compute exactly stays in code (walking, doors, firing, weapons, aiming, sidestepping);
  4. every threshold on an answer has an unsure band and a named fallback.

jev is asked the two judgments that have no exact rule behind them, both Scores: how promising each open
sector is for reaching the exit, and how dangerous the scene is. Code owns the mode machine, the reflex
layer, the hysteresis and the buttons. Direction memory is kept as a world bearing and converted to the
current egocentric label every tick, so "keep going left" cannot mean a new direction after every turn.
"""
import copy
import math
import re

GOALS = ["EXPLORE", "KILL_ENEMY", "STOCK_AMMO", "RESTORE_HEALTH", "ADD_ARMOR", "UPGRADE_WEAPON", "SCOUT", "HOLD"]
GOAL_FROM_CHOICE = {"Kill enemies": "KILL_ENEMY", "Restore health": "RESTORE_HEALTH", "Stock ammo": "STOCK_AMMO",
                    "Add armor": "ADD_ARMOR", "Explore": "EXPLORE", "Scout": "SCOUT", "Upgrade weapon": "UPGRADE_WEAPON"}
# The one direction vocabulary: every bearing in the state is binned into these eight labels (issue 8).
SECTORS = {"ahead": 0.0, "ahead-left": 45.0, "left": 90.0, "behind-left": 135.0,
           "behind": 180.0, "behind-right": -135.0, "right": -90.0, "ahead-right": -45.0}
DIR_KEYS = {"ahead": ("CLEAR_FWD", "NEW_FWD", "DOOR_FWD"), "ahead-left": ("CLEAR_AL", "NEW_AL", "DOOR_AL"),
            "left": ("CLEAR_LEFT", "NEW_LEFT", "DOOR_LEFT"), "behind-left": ("CLEAR_BL", "NEW_BL", "DOOR_BL"),
            "behind": ("CLEAR_BACK", "NEW_BACK", "DOOR_BACK"), "behind-right": ("CLEAR_BR", "NEW_BR", "DOOR_BR"),
            "right": ("CLEAR_RIGHT", "NEW_RIGHT", "DOOR_RIGHT"), "ahead-right": ("CLEAR_AR", "NEW_AR", "DOOR_AR")}
AHEAD_WORDS = {"NOTHING": "nothing near", "WALL": "a wall", "DOOR": "a door", "EXIT": "the exit switch",
               "LOCKED": "a locked door", "BARRIER": "bars or a blocked doorway the map does not show",
               "THING": "a monster or a barrel"}
OPERABLE = ("DOOR", "EXIT", "LOCKED")
MODES = ("EXPLORE", "APPROACH", "OPERATE", "FIGHT", "RECOVER", "DONE")
JUDGED_MODES = ("EXPLORE", "APPROACH")          # the modes in which jev picks the direction
UNKNOWN = "unknown"
SECTOR_FIELDS = ("space", "ground", "door", "exit_here", "key_here", "item_here", "hint_here",
                 "tried_recently", "data")
ROOMY = ("open", "long")
STOP = {"move": 0, "strafe": 0, "turn": 0.0, "fire": False, "use": False, "weapon": "FIST"}

# Every path a criterion is allowed to name. `lint` checks a graph against this before it is used.
STATE_PATHS = {
    "sectors": {"*": SECTOR_FIELDS},
    "player": ("health", "armor", "ammunition", "equipped_weapon", "equipped_ammo", "shotgun_shells",
               "pistol_bullets", "owns_shotgun"),
    "combat": ("enemy_visible", "enemies_in_view", "enemy_where", "enemy_distance", "enemy_in_crosshair"),
    "here": ("at_arms_length", "at_arms_length_distance", "stuck", "level", "keys_held", "mode"),
    "seen": ("exit", "key", "health_pickup", "ammo_pickup", "armor_pickup", "ground_hint"),
}


# ---------------------------------------------------------------- numbers -> words
def dist_words(d):
    if not d or d <= 0:
        return "none"
    return "point blank" if d < 70 else "close" if d < 180 else "mid-range" if d < 450 else "far"


def sector_of(rel_deg):
    """Bin any relative bearing (degrees, positive left) into the eight labels the sectors use."""
    return min(SECTORS, key=lambda d: abs((rel_deg - SECTORS[d] + 180) % 360 - 180))


def world_bearing(heading, label):
    return (heading + SECTORS[label]) % 360.0


def relative(heading, bearing):
    return (bearing - heading + 180.0) % 360.0 - 180.0


def ground_words(nov, legacy_door_overload=False):
    """Novelty only. A door never overwrites it any more: doors have their own channel (issue 9).

    `legacy_door_overload` is for replaying logs recorded before DOOR_* existed, where the payload wrote
    200..254 into NEW_* to mean "a door at (v-200)*8 units" and the novelty at that bearing was simply lost.
    """
    if nov is None:
        return UNKNOWN
    if nov >= 255:
        return "never explored"
    if legacy_door_overload and nov >= 200:
        return UNKNOWN
    return "new" if nov >= 60 else "partly walked" if nov >= 25 else "walked before"


def where_words(rel_deg, dist):
    """Where something seen lies, in the sector vocabulary: '<distance> <sector>' or 'not seen'."""
    if not dist:
        return "not seen"
    return "%s %s" % (dist_words(dist), sector_of(rel_deg))


def door_units(t, nov_key, door_key):
    """Door distance in a sector. Prefers the DOOR_* channel; falls back to the old NEW_* overload."""
    v = t.get(door_key)
    if v is not None:
        return None if v <= 0 or v >= 255 else int(v) * 8
    nov = t.get(nov_key)
    if nov is not None and 200 <= nov < 255:
        return (int(nov) - 200) * 8 + 1
    return None


# ---------------------------------------------------------------- history, kept by code (rule 2)
class NavMemory:
    """What the graph remembers. jev gets none of this directly; it gets the present-tense fields it implies.

    The committed direction is a world bearing, not the word "left": after a 90 degree turn "left" names a
    different direction, and keeping the label is what made the player spin (issue 5).
    """

    def __init__(self, cfg=None):
        sel = (cfg or {}).get("select", {})
        self.cooldown = int(sel.get("tried_cooldown", 40))
        self.no_progress_units = 64.0
        self.bearing = None          # world bearing committed to, degrees (0 = east, positive left)
        self.held = 0                # ticks the bearing has been held
        self.tick = 0
        self.start_pos = None        # position when the commitment began
        self.tried = {}              # world bucket 0..7 -> tick a commitment there ended with no progress
        self.fallbacks = 0
        self.mode, self.mode_since = "EXPLORE", 0
        self.door_presses, self.door_at = 0, None
        self.recover_from = None

    @staticmethod
    def bucket(bearing):
        return int(round((bearing % 360.0) / 45.0)) % 8

    def label_now(self, heading):
        """The egocentric name of the committed bearing at this heading, or None."""
        return None if self.bearing is None else sector_of(relative(heading, self.bearing))

    def commit(self, heading, label, pos=None):
        bearing = world_bearing(heading, label)
        if self.bearing is not None and self.bucket(bearing) == self.bucket(self.bearing):
            self.held += 1
            return
        if self.bearing is not None and self.start_pos and pos and \
                math.dist(pos, self.start_pos) < self.no_progress_units:
            self.tried[self.bucket(self.bearing)] = self.tick    # held that direction and got nowhere
        self.bearing, self.held, self.start_pos = bearing, 0, pos

    def tried_recently(self, heading, label):
        seen = self.tried.get(self.bucket(world_bearing(heading, label)))
        return seen is not None and self.tick - seen <= self.cooldown

    def step(self):
        self.tick += 1

    def set_mode(self, mode):
        if mode != self.mode:
            self.mode, self.mode_since = mode, self.tick

    def mode_ticks(self):
        return self.tick - self.mode_since


# ---------------------------------------------------------------- state
def build_state(t, goal, cfg, mem=None):
    """The structured state jev classifies: present-tense evidence in one vocabulary, no policy prose (issue 13)."""
    th = cfg["thresholds"]
    heading = float(t.get("ANGLE", 0.0) or 0.0)
    yn = lambda b: "yes" if b else "no"

    def space(c):
        if c is None:
            return UNKNOWN
        return "blocked" if c < th["blocked_units"] else "tight" if c < th["tight_units"] else "open" if c < 220 else "long"

    enemies = int(t.get("ENEMY_COUNT", 0) or 0)
    e_bearing, e_dist = float(t.get("ENEMY_BEARING", 0.0) or 0.0), t.get("ENEMY_DIST", 0) or 0
    shells, bullets = int(t.get("SHELLS", 0) or 0), int(t.get("BULLETS", 0) or 0)
    hp = t.get("HEALTH", 100)
    hp = 100 if hp is None else hp
    ahead_kind = str(t.get("AHEAD_KIND", "NOTHING"))
    keys = int(t.get("KEYS", 0) or 0)
    held = [name for bit, name in ((1, "red"), (2, "blue"), (4, "yellow")) if keys & bit]
    exit_rel = float(t.get("EXIT_BEARING", 0.0) or 0.0) if t.get("EXIT_DIST") else None
    key_rel = float(t.get("KEY_BEARING", 0.0) or 0.0) if t.get("KEY_DIST") else None
    items = {"health": ("HEALTH_BEARING", "HEALTH_ITEM_DIST"), "ammo": ("AMMO_BEARING", "AMMO_ITEM_DIST"),
             "armor": ("ARMOR_BEARING", "ARMOR_ITEM_DIST")}
    item_sector = {}
    for kind, (bk, dk) in items.items():
        if t.get(dk):
            item_sector.setdefault(sector_of(float(t.get(bk, 0.0) or 0.0)), kind)
    hint_sector = sector_of(float(t.get("HINT_REL", 0.0) or 0.0)) if t.get("HINT_ACTIVE") else None
    exit_sector = sector_of(exit_rel) if exit_rel is not None else None
    key_sector = sector_of(key_rel) if key_rel is not None else None

    sectors = {}
    for d, (ck, nk, dk) in DIR_KEYS.items():
        clear, nov = t.get(ck), t.get(nk)
        if clear is None or nov is None:
            sectors[d] = {"data": UNKNOWN}               # missing telemetry is never attractive (issue 4)
            continue
        if d == "ahead":
            clear = min(clear, t.get("CLEAR_MAP_FWD") or clear)
        door = door_units(t, nk, dk)
        legacy = t.get(dk) is None            # a log from before the DOOR_* channels existed
        sectors[d] = {"space": space(clear), "ground": ground_words(nov, legacy),
                      "door": dist_words(door) if door else "none",
                      "exit_here": yn(exit_sector == d), "key_here": yn(key_sector == d),
                      "item_here": item_sector.get(d, "none"), "hint_here": yn(hint_sector == d),
                      "tried_recently": yn(mem.tried_recently(heading, d)) if mem else "no"}

    here = {"at_arms_length": AHEAD_WORDS.get(ahead_kind, ahead_kind.lower()),
            "at_arms_length_distance": dist_words(t.get("AHEAD_DIST", 0)) if ahead_kind != "NOTHING" else "none",
            "stuck": yn(t.get("STUCK", False)), "level": str(t.get("LEVEL", 1)),
            "keys_held": " and ".join(held) if held else "none",
            "mode": (mem.mode if mem else "EXPLORE").lower()}
    return {
        "player": {"health": "critical" if hp < th["health_critical"] else "low" if hp < th["health_low"]
                   else "fine" if hp < 90 else "full",
                   "armor": "none" if (t.get("ARMOR") or 0) <= 0 else "some" if t.get("ARMOR") < 50 else "good",
                   "ammunition": "empty" if shells == 0 and bullets == 0 else
                                 "scarce" if shells == 0 and bullets < 12 else "ready",
                   "equipped_weapon": str(t.get("WEAPON", "PISTOL")).lower(),
                   "equipped_ammo": shells if str(t.get("WEAPON")) == "SHOTGUN" else bullets,
                   "shotgun_shells": shells, "pistol_bullets": bullets,
                   "owns_shotgun": yn(t.get("OWN_SHOTGUN", False))},
        "combat": {"enemy_visible": yn(enemies), "enemies_in_view": enemies,
                   "enemy_where": where_words(e_bearing, e_dist) if enemies else "no enemy in view",
                   "enemy_distance": dist_words(e_dist) if enemies else "none",
                   "enemy_in_crosshair": yn(enemies and abs(e_bearing) <= th["crosshair_deg"]
                                            and e_dist <= th["fire_range"])},
        "sectors": sectors,
        "here": here,
        "seen": {"exit": where_words(exit_rel or 0.0, t.get("EXIT_DIST", 0)),
                 "key": where_words(key_rel or 0.0, t.get("KEY_DIST", 0)),
                 **{"%s_pickup" % k: where_words(float(t.get(bk) or 0.0), t.get(dk, 0)) for k, (bk, dk) in items.items()},
                 "ground_hint": hint_sector or "none"},
    }


def known_sectors(state):
    """A sector whose telemetry is missing carries `data: unknown` and nothing else."""
    return [d for d, s in state["sectors"].items() if s.get("data") != UNKNOWN]


def offered_sectors(state):
    """Which directions are on the menu: known data, not blocked. Unknown is never offered (issues 4 and 6)."""
    known = known_sectors(state)
    return [d for d in known if state["sectors"][d].get("space") != "blocked"] or known or ["behind"]


# ---------------------------------------------------------------- questions
def _fill(node, direction):
    if isinstance(node, str):
        return node.replace("{dir}", direction)
    if isinstance(node, dict):
        return {k: _fill(v, direction) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, direction) for v in node]
    return node


def sector_questions(state, cfg, offered=None):
    """One short Score per offered sector, all on the same rubric, combined in code (issue 6)."""
    spec = cfg["questions"]["sector"]
    out = {}
    for d in (offered if offered is not None else offered_sectors(state)):
        out["s_%s" % d] = {"type": "score", "instructions": _fill(copy.deepcopy(spec["instructions"]), d),
                           "criteria": _fill(list(spec["criteria"]), d)}
    return out


def danger_question(cfg):
    spec = cfg["questions"]["danger"]
    return {"danger": {"type": "score", "instructions": copy.deepcopy(spec["instructions"]),
                       "criteria": list(spec["criteria"])}}


def goal_question(cfg):
    spec = cfg["questions"]["goal"]
    instr = copy.deepcopy(spec["instructions"])
    if isinstance(instr, dict):
        instr["mission"] = cfg["standing_order"]     # policy prose belongs on a question, not in the state
    return {"goal": {"type": "choice", "instructions": instr, "criteria": copy.deepcopy(spec["criteria"])}}


def questions_for(state, cfg, mode, ask_goal=False, offered=None):
    """Which heads this tick. Code decides; a head that cannot apply is not asked."""
    q = {}
    if mode in JUDGED_MODES:
        q.update(sector_questions(state, cfg, offered))
    if state["combat"]["enemy_visible"] == "yes":
        q.update(danger_question(cfg))
    if ask_goal:
        q.update(goal_question(cfg))
    return q


# Which top-level blocks of the state each head is allowed to read. `lint` holds the criteria to this, and
# `state_for` sends only these: text no question reads costs accuracy as well as tokens.
HEAD_STATE = {"sector": ("sectors",),
              "danger": ("combat", "player", "sectors"),
              "goal": ("player", "combat", "seen", "here")}


def head_of(qid):
    return "sector" if qid.startswith("s_") else qid


def state_for(state, questions):
    """The state as it is actually sent: only the blocks the heads asked this tick inspect."""
    keep = set()
    for qid in questions:
        keep |= set(HEAD_STATE.get(head_of(qid), ()))
    return {k: v for k, v in state.items() if k in keep} or state


# ---------------------------------------------------------------- answers -> numbers
def raw_score(answer):
    """A Score answer in rubric levels (0 .. levels-1), or None when the head was not asked.

    Everything downstream works in rubric levels, the same units System Two writes the rubric in, so a
    margin of 0.6 means "six tenths of a level" whatever the rubric's length.
    """
    if not isinstance(answer, dict) or "score" not in answer:
        return None
    return float(answer["score"])


def levels_of(cfg, head="sector"):
    return len(cfg["questions"][head]["criteria"])


def answer_label(v):
    """A printable answer for any head type."""
    if not isinstance(v, dict):
        return str(v)
    if "noul" in v:
        return "yes" if float(v["noul"]) >= 0.5 else "no"
    if "score" in v:
        return "%.2f" % float(v["score"])
    return v.get("choice")


def answer_confidence(v):
    if not isinstance(v, dict):
        return 0.0
    if "noul" in v:
        p = float(v["noul"])
        return max(p, 1.0 - p)
    return float(v.get("confidence", 0.0))


# ---------------------------------------------------------------- selection (code owns tie-breaks and hysteresis)
GOAL_WANTS = {"RESTORE_HEALTH": "health", "STOCK_AMMO": "ammo", "ADD_ARMOR": "armor"}


def goal_bonus(state, d, goal, cfg):
    """The goal head's one real effect: it weights the sector scores code combines, in rubric levels (issue 12)."""
    b = float(cfg["select"]["goal_bonus"])
    s = state["sectors"][d]
    if goal in GOAL_WANTS and s.get("item_here") == GOAL_WANTS[goal]:
        return b
    if goal == "SCOUT" and s.get("ground") == "never explored":
        return b
    return 0.0


def adjust(state, d, goal, cfg):
    """Every code-side adjustment to one sector's score, in rubric levels.

    A direction just held without getting anywhere loses a level here rather than in a criterion: that is a
    rule code applies exactly, and asking jev to apply it would only add a way to be wrong (rule 3).
    """
    penalty = float(cfg["select"]["tried_penalty"]) if state["sectors"][d].get("tried_recently") == "yes" else 0.0
    return goal_bonus(state, d, goal, cfg) - penalty


def frontier_fallback(state, offered):
    """The named fallback for an unsure answer: the most promising sector by the exact rule, unexplored
    ground first, skipping anything just tried. Deterministic, so an unsure tick is never a coin flip (issue 10)."""
    rank = {"never explored": 3, "new": 2, "partly walked": 1, "walked before": 0, UNKNOWN: 0}
    room = {"long": 3, "open": 2, "tight": 1, "blocked": 0, UNKNOWN: 0}
    fresh = [d for d in offered if state["sectors"][d].get("tried_recently") != "yes"] or list(offered)
    return max(fresh, key=lambda d: (state["sectors"][d].get("exit_here") == "yes",
                                     rank.get(state["sectors"][d].get("ground"), 0),
                                     room.get(state["sectors"][d].get("space"), 0),
                                     -abs(SECTORS[d])))


def pick_sector(answers, state, cfg, mem, heading, goal="EXPLORE", offered=None, pos=None):
    """Turn the per-sector Scores into one direction. Returns (label, detail)."""
    sel = cfg["select"]
    offered = list(offered if offered is not None else offered_sectors(state))
    raw = {d: raw_score(answers.get("s_%s" % d)) for d in offered}
    scored = {d: v + adjust(state, d, goal, cfg) for d, v in raw.items() if v is not None}
    detail = {"offered": offered, "scores": {d: round(v, 2) for d, v in scored.items()},
              "fallback": None, "held": False, "gap": None, "confidence": None, "margin": None}
    if not scored:
        detail["fallback"] = "no scores"
        mem.fallbacks += 1
        pick = frontier_fallback(state, offered)
        mem.commit(heading, pick, pos)
        detail["pick"] = pick
        return pick, detail
    best = max(scored, key=scored.get)
    ordered = sorted(scored.values(), reverse=True)
    gap = (ordered[0] - ordered[1]) if len(ordered) > 1 else float(levels_of(cfg))
    conf = answer_confidence(answers.get("s_%s" % best, {}))
    detail["gap"], detail["confidence"] = round(gap, 3), round(conf, 3)
    # Two independent ways to be unsure, and either one is enough. The gap is the one that matters: each
    # sector is scored by its own question, so a Score's `confidence` says how concentrated that sector's
    # own rubric answer is, not how far it beats the others. Replaying the 22 September run showed jev
    # reporting high confidence per sector while the top two sat 0.07 levels apart -- a ranking that is a
    # coin flip. Requiring both conditions meant the band never fired at all.
    if gap < float(sel["unsure_gap"]) or conf < float(sel["unsure_conf"]):
        best = frontier_fallback(state, offered)        # "cannot tell": hand off to the named rule
        detail["fallback"] = "unsure gap" if gap < float(sel["unsure_gap"]) else "unsure answer"
        mem.fallbacks += 1
    prev = mem.label_now(heading)
    if prev in scored and prev != best:
        # Hysteresis, never an override. The margin is raised while a commitment is fresh, but capped below
        # one rubric level, so a direction a whole level better always wins: a fresh commitment must not be
        # able to hold the pilot away from the sector the exit is in.
        margin = float(sel["sector_margin"])
        if mem.held < int(sel["commit_ticks"]):
            margin += float(sel["commit_bonus"])
        margin = min(margin, 1.0 - 1e-9)
        detail["margin"] = round(margin, 3)
        if scored[best] - scored[prev] < margin:
            best, detail["held"] = prev, True           # hysteresis on a world bearing, not on a word
    mem.commit(heading, best, pos)
    detail["pick"] = best
    return best, detail


# ---------------------------------------------------------------- the rules that left jev (issue 11)
def best_weapon(t):
    """The weapon to select, or FIST, which the flight component defines as "keep what is equipped".

    The payload holds the select-weapon button down for as long as the command names a real weapon, so
    asking for the weapon already in hand would hold that button on every tic. Only ask when it differs.
    """
    if t.get("OWN_SHOTGUN") and int(t.get("SHELLS", 0) or 0) > 0:
        want = "SHOTGUN"
    elif int(t.get("BULLETS", 0) or 0) > 0:
        want = "PISTOL"
    else:
        want = "FIST"
    return "FIST" if want == str(t.get("WEAPON", "")).upper() else want


def combat_controls(state, t, cfg, danger):
    """Firing, the weapon, the sidestep and the aim: exact rules over numbers code already has."""
    sel, th = cfg["select"], cfg["thresholds"]
    ammo = int(state["player"]["equipped_ammo"] or 0)
    fire = state["combat"]["enemy_in_crosshair"] == "yes" and ammo > 0
    side = lambda d: state["sectors"].get(d, {}).get("space") in ROOMY   # a long passage is the best dodge space
    strafe, move = 0, 0
    if danger is not None and danger >= float(sel["danger_retreat"]):
        strafe = -1 if side("left") else 1 if side("right") else 0
        move = -1 if side("behind") and not strafe else 0
    elif danger is not None and danger >= float(sel["danger_sidestep"]):
        strafe = -1 if side("left") else 1 if side("right") else 0
    cap = float(th["max_aim_deg"])
    turn = max(-cap, min(cap, float(t.get("ENEMY_BEARING", 0.0) or 0.0)))   # aim with the number, not a word
    return {"move": move, "strafe": strafe, "turn": turn, "fire": fire, "use": False, "weapon": best_weapon(t)}


def reflex(cargs, state, t, cfg, pending_turn=0.0):
    """The layer under every mode: hard invariants enforced in code, never by the model (rule 9)."""
    out = dict(cargs)
    if int(state["player"]["equipped_ammo"] or 0) <= 0:
        out["fire"] = False
    ahead = state["sectors"].get("ahead", {})
    if out["move"] > 0 and ahead.get("space") in ("blocked", UNKNOWN, None) \
            and state["here"]["at_arms_length"] not in ("a door", "the exit switch"):
        out["move"] = 0                                 # never walk into a known wall
    if abs(pending_turn) > float(cfg["thresholds"]["turn_settle_deg"]):
        out["turn"] = 0.0                               # never re-command a turn that is still in flight
    cap = float(cfg["thresholds"]["max_turn_deg"])
    out["turn"] = max(-cap, min(cap, float(out["turn"])))
    return out


# ---------------------------------------------------------------- the mode machine (code owns every transition)
def next_mode(state, t, mem, cfg):
    """Explicit modes beat one hidden in criteria; every transition here is an exact rule (rule 8)."""
    sel = cfg["select"]
    mode = mem.mode
    operable = str(t.get("AHEAD_KIND", "NOTHING")) in OPERABLE and 0 < (t.get("AHEAD_DIST") or 0) <= sel["operate_units"]
    enemy = state["combat"]["enemy_visible"] == "yes"
    if t.get("LEVEL_DONE"):
        mem.set_mode("DONE")
        return "DONE"
    if mode == "DONE":
        mem.set_mode("EXPLORE")
        return "EXPLORE"
    if state["here"]["stuck"] == "yes" and mode != "OPERATE":
        if mem.recover_from is None and t.get("POS_X") is not None:
            mem.recover_from = (t["POS_X"], t["POS_Y"])
        mem.set_mode("RECOVER")
        return "RECOVER"
    if mode == "RECOVER":
        moved = mem.recover_from is not None and t.get("POS_X") is not None and \
            math.dist((t["POS_X"], t["POS_Y"]), mem.recover_from) >= 64.0
        if moved or mem.mode_ticks() >= sel["recover_ticks"]:
            mem.recover_from = None
            mem.set_mode("EXPLORE")
            return "EXPLORE"
        return "RECOVER"
    if enemy:
        mem.set_mode("FIGHT")
        return "FIGHT"
    if mode == "FIGHT" and mem.mode_ticks() < sel["fight_linger_ticks"]:
        return "FIGHT"
    if operable:
        mem.set_mode("OPERATE")
        return "OPERATE"
    if mode == "OPERATE":
        mem.door_presses, mem.door_at = 0, None
        mem.set_mode("EXPLORE")
        return "EXPLORE"
    near = [state["sectors"][d] for d in known_sectors(state)]
    approach = any(s.get("door") in ("point blank", "close") or s.get("exit_here") == "yes" for s in near)
    mem.set_mode("APPROACH" if approach else "EXPLORE")
    return mem.mode


def operate_controls(state, t, cfg, mem):
    """OPERATE: press Use, count the presses, give up after a few so the player never stands on a dead door."""
    at = (round((t.get("POS_X") or 0) / 32), round((t.get("POS_Y") or 0) / 32),
          round(float(t.get("ANGLE") or 0) / 45))
    if at != mem.door_at:
        mem.door_at, mem.door_presses = at, 0
    mem.door_presses += 1
    give_up = mem.door_presses > int(cfg["select"]["door_tries"])
    return {"move": 0 if give_up else 1, "strafe": 0, "turn": 0.0, "fire": False,
            "use": not give_up, "weapon": best_weapon(t)}


def recover_controls(state, t, cfg, mem):
    """RECOVER: back out and turn away from whatever the player is pushing into. No judgment needed."""
    back = state["sectors"].get("behind", {}).get("space") in ROOMY
    left = state["sectors"].get("left", {}).get("space") in ROOMY
    return {"move": -1 if back else 0, "strafe": 0, "turn": 0.0 if back else (90.0 if left else -90.0),
            "fire": False, "use": True, "weapon": best_weapon(t)}


def travel_controls(state, pick):
    """EXPLORE / APPROACH: walking is a rule once the direction is chosen (the `advance` Noul is gone)."""
    ahead = state["sectors"].get("ahead", {})
    if pick == "ahead":
        return {"move": 1 if ahead.get("space") not in ("blocked", UNKNOWN, None) else 0, "strafe": 0, "turn": 0.0}
    if pick == "behind" and state["sectors"].get("behind", {}).get("space") in ROOMY \
            and ahead.get("space") in ("blocked", "tight"):
        return {"move": -1, "strafe": 0, "turn": 0.0}   # back out rather than turn around in a corridor
    return {"move": 0, "strafe": 0, "turn": SECTORS[pick]}


def danger_level(answers, cfg):
    """The danger Score in rubric levels, or None when the head was not asked."""
    return raw_score(answers.get("danger"))


def control_args(state, t, cfg, mem, mode, answers, pick=None, pending_turn=0.0):
    """The one place answers become buttons."""
    if mode == "FIGHT":
        cargs = combat_controls(state, t, cfg, danger_level(answers, cfg))
    elif mode == "OPERATE":
        cargs = operate_controls(state, t, cfg, mem)
    elif mode == "RECOVER":
        cargs = recover_controls(state, t, cfg, mem)
    elif mode == "DONE":
        cargs = dict(STOP)
    else:
        cargs = {**travel_controls(state, pick or "ahead"), "fire": False,
                 "use": state["here"]["at_arms_length"] in ("a door", "the exit switch", "a locked door"),
                 "weapon": best_weapon(t)}
    return reflex(cargs, state, t, cfg, pending_turn)


# ---------------------------------------------------------------- the linter (rule 5)
def _paths_in(node, out):
    if isinstance(node, str):
        out.update(re.findall(r"`([A-Za-z0-9_.{}\-\[\]*]+)`", node))
    elif isinstance(node, dict):
        for v in node.values():
            _paths_in(v, out)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _paths_in(v, out)
    return out


def known_path(path):
    """A fully qualified path only. Every sector has a field called `space`, so a bare `space` would be
    ambiguous in a state jev reads literally: questions name `sectors.left.space` in full."""
    parts = path.split(".")
    node = STATE_PATHS.get(parts[0])
    if node is None:
        return False
    if len(parts) == 1:
        return True
    if isinstance(node, dict):                        # sectors.<direction>.<field>
        if parts[1] not in SECTORS:
            return False
        return len(parts) == 2 or (len(parts) == 3 and parts[2] in node["*"])
    return len(parts) == 2 and parts[1] in node


def rendered_questions(cfg):
    """(head, question) for every question as jev will actually receive it, {dir} substituted.

    Linting the rendered text rather than the template catches a placeholder that never got substituted
    and a field name that only exists on some sectors.
    """
    out = [("danger", copy.deepcopy(cfg["questions"]["danger"])), ("goal", copy.deepcopy(cfg["questions"]["goal"]))]
    for d in SECTORS:
        out.append(("sector", _fill(copy.deepcopy(cfg["questions"]["sector"]), d)))
    return out


def lint(cfg):
    """Every backticked state path a question names, as sent, must exist *and* be in a block that head is
    given. Returns the offending paths, sorted."""
    bad = set()
    for head, q in rendered_questions(cfg):
        allowed = HEAD_STATE.get(head, ())
        for p in _paths_in(q, set()):
            if not known_path(p) or p.split(".")[0] not in allowed:
                bad.add(p)
    return sorted(bad)
