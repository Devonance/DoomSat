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
JUDGED_MODES = ("EXPLORE",)    # the only mode where jev picks a direction; the rest are exact rules
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
    "here": ("at_arms_length", "at_arms_length_distance", "stuck", "level", "keys_held", "mode",
             "health", "armor", "ammunition"),
    "seen": ("exit", "key", "health_pickup", "ammo_pickup", "armor_pickup", "ground_hint"),
    # Charter 3.3: somewhere to go, built onboard where the map is, scored here.
    "targets": {"*": ("what", "how_far", "direction", "unseen_ground_behind_it", "tried_before",
                      "locked", "needed_now")},
    "needs": ("health", "ammo", "armor"),
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


# Worst to best, per field. A reading that is worse than the one held is believed at once; a reading that
# is better has to be confirmed by a second sense before it replaces it. Optimistic flicker is the kind
# that gets a player killed, so it is the kind that has to earn its place.
FIELD_ORDER = {
    "space": ("blocked", "tight", "open", "long"),
    "ground": ("walked before", "partly walked", "new", "never explored"),
    "door": ("none", "far", "mid-range", "close", "point blank"),
}


class SectorMemory:
    """Sector words kept against the ray's real world bearing, so turning is not mistaken for change.

    The payload senses eight rays at 45 degree offsets from the *heading*, so with a heading of 36 degrees
    the rays point at 36, 81, 126 ... -- nowhere near a fixed compass grid. Rounding them into eight world
    buckets therefore files consecutive readings under the wrong neighbour about as often as the right one,
    which is why bucketing alone only removed a fifth of the churn. Matching each fresh ray to the nearest
    remembered bearing within `tolerance` keeps a world direction's history together while the player turns.

    A reading that is *worse* than the one held is believed at once; a reading that is *better* has to be
    confirmed by `confirm` senses. Optimistic flicker is the kind that walks a player into a wall, so it is
    the kind that has to earn its place.
    """

    def __init__(self, confirm=2, tolerance=22.5, slots=12):
        self.confirm = max(1, int(confirm))
        self.tolerance = float(tolerance)
        self.max_slots = int(slots)
        self.slots = []          # [bearing, {field: word}, {field: [word, count]}, last_seen]
        self.tick = 0

    def step(self):
        self.tick += 1

    def slot(self, bearing):
        best, best_d = None, 1e9
        for sl in self.slots:
            d = abs((sl[0] - bearing + 180) % 360 - 180)
            if d < best_d:
                best, best_d = sl, d
        if best is not None and best_d <= self.tolerance:
            best[0], best[3] = bearing, self.tick      # re-centre on the ray that just arrived
            return best
        fresh = [bearing, {}, {}, self.tick]
        self.slots.append(fresh)
        if len(self.slots) > self.max_slots:
            self.slots.remove(min(self.slots, key=lambda sl: sl[3]))
        return fresh

    @staticmethod
    def rank(field, word):
        order = FIELD_ORDER.get(field, ())
        return order.index(word) if word in order else -1

    def settle(self, bearing, field, word):
        """The word to report for this world direction, given a fresh reading along it."""
        sl = self.slot(bearing)
        held = sl[1].get(field)
        if held is None or word == held or word == UNKNOWN or held == UNKNOWN:
            sl[1][field] = word
            sl[2].pop(field, None)
            return word
        if self.rank(field, word) <= self.rank(field, held):
            sl[1][field] = word                        # worse news is believed at once
            sl[2].pop(field, None)
            return word
        seen = sl[2].get(field)
        count = seen[1] + 1 if seen and seen[0] == word else 1
        if count >= self.confirm:
            sl[1][field] = word                        # better news, now confirmed
            sl[2].pop(field, None)
            return word
        sl[2][field] = [word, count]
        return held


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
        self.gave_up = {}            # 64-unit cell -> tick a door there was abandoned
        self.recover_from = None
        self.idle_ticks = 0          # decisions over which the player has not got anywhere
        self.recent = []             # (tick, x, y) for the last few decisions
        self.last_pos = None
        self.sectors = SectorMemory(sel.get("confirm_ticks", 2))

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
        self.sectors.step()

    def note_position(self, pos, window=10, progress_units=64.0):
        """Count decisions over which the player has not got anywhere.

        The payload only reports STUCK once a motion command has been *held* without progress, and the
        reflex layer refuses to walk into what the map calls a wall -- so a pilot that believes it is
        walled in commands nothing, never pushes, and is never told it is stuck. It sat at one position
        for 553 consecutive decisions that way, and on the next run it drifted a few units per decision
        for a thousand more, which a "did it move since last time" test does not catch. This asks the
        question that matters: over the last `window` decisions, has it got anywhere at all?
        """
        if pos is None or pos[0] is None:
            return
        self.last_pos = pos
        self.recent.append((self.tick, pos[0], pos[1]))
        self.recent = self.recent[-window:]
        if len(self.recent) < window:
            self.idle_ticks = 0
            return
        first = self.recent[0]
        if math.dist(pos, (first[1], first[2])) < progress_units:
            self.idle_ticks += 1
        else:
            self.idle_ticks = 0

    @staticmethod
    def spot(t):
        x, y = t.get("POS_X") or 0.0, t.get("POS_Y") or 0.0
        return (round(x / 64), round(y / 64))

    def give_up_here(self, t):
        """Remember that the door at this spot did not open, so OPERATE does not re-enter immediately."""
        self.gave_up[self.spot(t)] = self.tick
        self.door_presses, self.door_at = 0, None

    def gave_up_recently(self, t, within):
        seen = self.gave_up.get(self.spot(t))
        return seen is not None and self.tick - seen <= within

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
        raw_words = {"space": space(clear), "ground": ground_words(nov, legacy),
                     "door": dist_words(door) if door else "none"}
        if mem is not None:                   # smooth per world direction, not per label
            bearing = world_bearing(heading, d)
            raw_words = {f: mem.sectors.settle(bearing, f, w) for f, w in raw_words.items()}
        sectors[d] = {**raw_words,
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


def questions_for(state, cfg, mode, ask_goal=False, offered=None, threat=False):
    """Which heads this tick. Code decides; a head that cannot apply is not asked."""
    q = {}
    if mode in JUDGED_MODES:
        q.update(sector_questions(state, cfg, offered))
    if threat:
        q.update(danger_question(cfg))      # only worth asking when there is something to be in danger of
    if ask_goal:
        q.update(goal_question(cfg))
    return q


# Which top-level blocks of the state each head is allowed to read. `lint` holds the criteria to this, and
# `state_for` sends only these: text no question reads costs accuracy as well as tokens.
HEAD_STATE = {"sector": ("sectors",),
              "danger": ("combat", "player", "sectors"),
              "goal": ("player", "combat", "seen", "here"),
              "target": ("targets", "here", "needs"),
              "need": ("needs", "here", "combat")}


def head_of(qid):
    if qid.startswith("s_"):
        return "sector"
    if qid.startswith("g_"):
        return "target"
    if qid.startswith("n_"):
        return "need"
    return qid


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


# The sector rubric written as an exact rule, level for level. It is used in two places and has to match
# cfg["questions"]["sector"]["criteria"]: as the named fallback when jev cannot tell, and as the code-only
# baseline jev is measured against in tools/replay.py. One copy, so the baseline cannot drift away from
# the rubric it is meant to be the null hypothesis for.
RULE_LEVELS = 9


def rule_score(s, levels=RULE_LEVELS):
    """A sector's level under the rubric, by rule. Scaled if the rubric's length has been changed."""
    if s.get("data") == UNKNOWN:
        return 0.0
    ground, door, roomy = s.get("ground"), s.get("door"), s.get("space") in ROOMY
    if s.get("exit_here") == "yes" or s.get("key_here") == "yes":
        raw = 8.0
    elif ground == "never explored" and roomy:
        raw = 7.0
    elif door in ("point blank", "close"):
        raw = 6.0
    elif ground == "never explored":
        raw = 5.0
    elif ground == "new":
        raw = 4.0
    elif s.get("hint_here") == "yes":
        raw = 3.0
    elif ground == "partly walked" and roomy:
        raw = 2.0
    elif roomy:
        raw = 1.0
    else:
        raw = 0.0
    return raw * (levels - 1) / (RULE_LEVELS - 1)


def frontier_fallback(state, offered):
    """The named fallback for an unsure answer: the best sector by the exact rule, skipping anything just
    tried, ties broken toward straight on. Deterministic, so an unsure tick is never a coin flip."""
    fresh = [d for d in offered if state["sectors"][d].get("tried_recently") != "yes"] or list(offered)
    return max(fresh, key=lambda d: (rule_score(state["sectors"][d]), -abs(SECTORS[d])))


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


def reflex(cargs, state, t, cfg, pending_turn=0.0, mode="EXPLORE"):
    """The layer under every mode: hard invariants enforced in code, never by the model (rule 9)."""
    out = dict(cargs)
    if int(state["player"]["equipped_ammo"] or 0) <= 0:
        out["fire"] = False
    ahead = state["sectors"].get("ahead", {})
    if out["move"] > 0 and mode != "RECOVER" and ahead.get("space") in ("blocked", UNKNOWN, None) \
            and state["here"]["at_arms_length"] not in ("a door", "the exit switch"):
        out["move"] = 0                                 # never walk into a known wall, unless recovering
    if abs(pending_turn) > float(cfg["thresholds"]["turn_settle_deg"]):
        out["turn"] = 0.0                               # never re-command a turn that is still in flight
    cap = float(cfg["thresholds"]["max_turn_deg"])
    out["turn"] = max(-cap, min(cap, float(out["turn"])))
    return out


# ---------------------------------------------------------------- the mode machine (code owns every transition)
def threatened(state, t, cfg):
    """Is there a fight here? An exact rule, so it can decide the mode before any answer comes back."""
    if state["combat"]["enemy_visible"] != "yes":
        return False
    dist = t.get("ENEMY_DIST") or 0
    return dist <= cfg["thresholds"]["threat_dist"] or state["player"]["health"] in ("low", "critical")


def next_mode(state, t, mem, cfg):
    """Explicit modes beat one hidden in criteria; every transition here is an exact rule (rule 8)."""
    sel = cfg["select"]
    mode = mem.mode
    operable = (str(t.get("AHEAD_KIND", "NOTHING")) in OPERABLE
                and 0 < (t.get("AHEAD_DIST") or 0) <= sel["operate_units"]
                and not mem.gave_up_recently(t, sel["door_retry_ticks"]))
    # An enemy on the far side of the level is not a fight. Measured: the pilot spent 211 consecutive
    # decisions in FIGHT staring at one 2,139 units away, commanding move 0, turn 0, fire 0, because the
    # mode triggered on bare visibility. A threat is one that is close enough to shoot, or any enemy at
    # all once health is down.
    enemy = threatened(state, t, cfg)
    if t.get("LEVEL_DONE"):
        mem.set_mode("DONE")
        return "DONE"
    if mode == "DONE":
        mem.set_mode("EXPLORE")
        return "EXPLORE"
    idle = mem.idle_ticks >= sel["idle_ticks"]
    if (state["here"]["stuck"] == "yes" or idle) and mode != "OPERATE":
        if mem.recover_from is None and t.get("POS_X") is not None:
            mem.recover_from = (t["POS_X"], t["POS_Y"])
        mem.set_mode("RECOVER")
        return "RECOVER"
    if mode == "RECOVER":
        moved = mem.recover_from is not None and t.get("POS_X") is not None and \
            math.dist((t["POS_X"], t["POS_Y"]), mem.recover_from) >= 64.0
        if moved:
            mem.recover_from = None
            mem.idle_ticks = 0
            mem.recent = []
            mem.set_mode("EXPLORE")
            return "EXPLORE"
        if mem.mode_ticks() >= sel["recover_ticks"] and not idle:
            mem.recover_from = None
            mem.set_mode("EXPLORE")
            return "EXPLORE"
        return "RECOVER"
    if enemy:
        mem.set_mode("FIGHT")
        return "FIGHT"
    if mode == "FIGHT" and mem.mode_ticks() < sel["fight_linger_ticks"]:
        return "FIGHT"
    if mode == "OPERATE" and mem.door_presses > sel["door_tries"]:
        # The presses are spent. Without this the pilot stood at one door for 1,172 consecutive decisions
        # -- nine minutes of use=False, move=0 -- because `operable` stayed true and nothing let it leave.
        mem.give_up_here(t)
        mem.set_mode("EXPLORE")
        return "EXPLORE"
    if operable:
        mem.set_mode("OPERATE")
        return "OPERATE"
    if mode == "OPERATE":
        mem.door_presses, mem.door_at = 0, None
        mem.set_mode("EXPLORE")
        return "EXPLORE"
    if mode == "APPROACH" and mem.mode_ticks() >= sel["approach_ticks"]:
        mem.set_mode("EXPLORE")               # never let one unreachable door hold the pilot for ever
        return "EXPLORE"
    mem.set_mode("APPROACH" if approach_target(state, t, mem, sel["door_retry_ticks"]) else "EXPLORE")
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
    """RECOVER: get out, by pushing rather than by reasoning.

    Always commands motion. Standing still is what got the pilot here, and if the map is wrong about being
    walled in -- the map ray and the camera disagree on about a third of ticks -- the only way to find out
    is to push. The reflex layer lets movement through in this mode for the same reason.
    """
    back = state["sectors"].get("behind", {}).get("space") in ROOMY
    left = state["sectors"].get("left", {}).get("space") in ROOMY
    turn = 0.0 if back else (90.0 if left else -90.0)
    # alternate the sidestep so two walls cannot trap it in the same corner
    strafe = 0 if back else (1 if (mem.tick // max(1, cfg["select"]["recover_ticks"])) % 2 else -1)
    return {"move": -1 if back else 1, "strafe": strafe, "turn": turn,
            "fire": False, "use": True, "weapon": best_weapon(t)}


def travel_controls(state, pick):
    """EXPLORE: walking is a rule once the direction is chosen (the `advance` Noul is gone).

    A correction of 45 degrees or less is taken *while walking*, so the player arcs into it instead of
    pivoting on the spot. Stopping to turn is slower, and over a window it is indistinguishable from a
    spin: part of what the spin metric counted on the first live run was this design, not a fault.
    """
    ahead = state["sectors"].get("ahead", {})
    walkable = ahead.get("space") not in ("blocked", UNKNOWN, None)
    turn = SECTORS[pick]
    if pick == "ahead":
        return {"move": 1 if walkable else 0, "strafe": 0, "turn": 0.0}
    if abs(turn) <= 45.0:
        return {"move": 1 if walkable else 0, "strafe": 0, "turn": turn}
    if pick == "behind" and state["sectors"].get("behind", {}).get("space") in ROOMY:
        if ahead.get("space") in ("blocked", "tight"):
            return {"move": -1, "strafe": 0, "turn": 0.0}   # back out rather than turn in a corridor
    return {"move": 0, "strafe": 0, "turn": turn}


def approach_target(state, t, mem=None, gave_up_within=60):
    """The bearing of the thing worth walking up to, relative to the heading, or None.

    Code owns this. Once the map says a door or the exit line is close, steering at it is arithmetic, and
    asking jev to rank sectors instead is how APPROACH came to turn *away* from the door it was
    approaching on the first live run.
    """
    if t.get("EXIT_DIST"):
        return float(t.get("EXIT_BEARING") or 0.0), "the exit"
    if mem is not None and mem.gave_up_recently(t, gave_up_within):
        return None                       # do not walk back to a door that just refused to open
    best = None
    for d, (_, nk, dk) in DIR_KEYS.items():
        if state["sectors"].get(d, {}).get("door") in ("point blank", "close"):
            units = door_units(t, nk, dk) or 10000
            if best is None or units < best[0]:
                best = (units, SECTORS[d])
    return (best[1], "a door") if best else None


def approach_controls(state, t, cfg, mem=None):
    """APPROACH: steer at the door or the exit and walk. No sector scoring, so it is a mode and not a label."""
    target = approach_target(state, t, mem, cfg["select"]["door_retry_ticks"])
    rel = target[0] if target else 0.0
    arm = state["here"]["at_arms_length"] in ("a door", "the exit switch", "a locked door")
    ahead = state["sectors"].get("ahead", {})
    walkable = ahead.get("space") not in ("blocked", UNKNOWN, None)
    move = 1 if arm or (abs(rel) <= 45.0 and walkable) else 0
    return {"move": move, "strafe": 0, "turn": rel, "fire": False, "use": arm, "weapon": best_weapon(t)}


def danger_level(answers, cfg):
    """The danger Score in rubric levels, or None when the head was not asked."""
    return raw_score(answers.get("danger"))


def control_args(state, t, cfg, mem, mode, answers, pick=None, pending_turn=0.0):
    """The one place answers become buttons."""
    if mode == "FIGHT":
        cargs = combat_controls(state, t, cfg, danger_level(answers, cfg))
    elif mode == "OPERATE":
        cargs = operate_controls(state, t, cfg, mem)
    elif mode == "APPROACH":
        cargs = approach_controls(state, t, cfg, mem)
    elif mode == "RECOVER":
        cargs = recover_controls(state, t, cfg, mem)
    elif mode == "DONE":
        cargs = dict(STOP)
    else:
        # Not a fight, but if a shot happens to line up there is no reason to walk past it.
        cargs = {**travel_controls(state, pick or "ahead"),
                 "fire": state["combat"]["enemy_in_crosshair"] == "yes",
                 "use": state["here"]["at_arms_length"] in ("a door", "the exit switch", "a locked door"),
                 "weapon": best_weapon(t)}
    return reflex(cargs, state, t, cfg, pending_turn, mode)


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


# ---------------------------------------------------------------- one decision, shared by every runner
def decide(t, cfg, mem, goal, system_one, n=0, ask_goal=None, pending_turn=0.0):
    """State, heads, pick and controls for one tick.

    The flight pilot and the bench runner both call this, which is the only reason a bench number is worth
    anything: a harness that reimplements the decision is measuring the harness. Everything around it --
    telemetry freshness, waiting out a commanded turn, sending the command, logging -- stays with the
    caller, because those differ between a Yamcs link and an in-process game.
    """
    mem.step()
    mem.note_position((t.get("POS_X"), t.get("POS_Y")) if t.get("POS_X") is not None else None,
                      window=cfg["select"]["idle_ticks"])
    state = build_state(t, goal, cfg, mem)
    mode = next_mode(state, t, mem, cfg)
    state["here"]["mode"] = mode.lower()
    offered = offered_sectors(state)
    if ask_goal is None:
        ask_goal = bool(cfg["goal_every"]) and n % cfg["goal_every"] == 0
    questions = questions_for(state, cfg, mode, ask_goal=ask_goal, offered=offered,
                              threat=threatened(state, t, cfg))
    answers, reply = {}, {"latency_ms": 0}
    sent = state_for(state, questions)      # only the blocks this tick's heads inspect
    if questions:
        reply = system_one.ask(sent, questions)
        answers = reply["answers"]
    pick, detail = None, {}
    if mode in JUDGED_MODES:
        pos = (t["POS_X"], t["POS_Y"]) if t.get("POS_X") is not None else None
        pick, detail = pick_sector(answers, state, cfg, mem, float(t.get("ANGLE", 0.0) or 0.0),
                                   goal, offered, pos)
    cargs = control_args(state, t, cfg, mem, mode, answers, pick, pending_turn)
    return {"state": state, "sent": sent, "mode": mode, "offered": offered, "questions": questions,
            "answers": answers, "reply": reply, "pick": pick, "detail": detail, "control": cargs,
            "code_only": not questions}
