"""Choosing where to go, from the candidate list the payload builds. Charter 3.3.

This replaces the eight-sector Score as the navigator. The sectors were never wrong; they were myopic. The
best a sector can say is "it is a bit more open to the left", and the thing worth going to is usually a
door six hundred units away, through two rooms, that the player has already walked past twice. Graded
against the charter's ruler, that cost `revisit_fraction` 0.80 and a score of zero.

The shape is the composite-scoring pattern the audit settled on, applied to targets instead of directions:

  the payload  builds the candidate list, with a path distance that respects walls
  the model    scores each candidate on one shared rubric, in one call
  code         picks, with commitment and an unsure band, and turns the pick into an INTENT

`rule_score` is the null hypothesis, and it is deliberately NOT a restatement of the rubric. The sector
head was written that way -- every rubric level a function of the same enum fields the rule read -- and
the result was that sharpening the rubric drove agreement with ten lines of code from 79% to 89%. The
model could only reproduce the rule, so the comparison measured nothing. The rubric here asks for the
trade-offs no single field settles (what is standing near the target against the health and ammunition
there is to spend, how far it is relative to the alternatives, whether a detour answers a real need);
the rule knows about none of that.
"""
import json
import math

# Path-distance buckets. These are the words the model sees; the numbers never reach it.
DIST_WORDS = ((96.0, "right here"), (320.0, "close"), (800.0, "mid-range"), (1600.0, "far"))
NOVELTY_WORDS = ((16, "none"), (64, "a little"), (160, "some"))
# What an opening looks like. A corridor mouth and the corner of the room you are standing in are the
# same distance away and nothing else about them is alike; these are the words that tell them apart.
OPENING_WORDS = ((48.0, "a crack"), (112.0, "a doorway"), (256.0, "a wide opening"))
DEPTH_WORDS = ((96.0, "no depth"), (320.0, "a little way"), (800.0, "a fair way"))
ENEMY_CLASSES = ("Zombieman", "ShotgunGuy", "ChaingunGuy", "DoomImp", "Demon", "Spectre", "LostSoul",
                 "Cacodemon", "BaronOfHell", "HellKnight", "Revenant", "Arachnotron", "Fatso",
                 "PainElemental", "Archvile", "WolfensteinSS")   # pinned to payload/mapclasses.py by a test
KIND_WORDS = {"frontier": "unexplored edge", "door": "a door", "exit": "the level exit",
              "key": "a key", "item": "a pickup", "switch": "a switch", "enemy": "an enemy"}
NEEDS = ("health", "ammo", "armor")
# Where a level puts you down is not where it lets you out. That is true of the form, not of any level,
# and it is the one thing that can be said about a direction without having been down it.
OUTWARD_WORDS = {0: "no, back toward where the level began", 1: "about as far out",
                 2: "yes, further out than where the player is"}

# The rubric as a function, level by level, worst first. Kept beside the criteria in graph_config so the
# two can be read together; a test asserts they have the same number of levels.
RULE_LEVELS = 9


def bucket(value, table, last):
    for limit, word in table:
        if value < limit:
            return word
    return last


def dist_word(units):
    return bucket(units, DIST_WORDS, "a long way")


def novelty_word(n):
    return bucket(n, NOVELTY_WORDS, "a lot")


def opening_word(units):
    return bucket(units, OPENING_WORDS, "a whole side of the room")


def depth_word(units):
    return bucket(units, DEPTH_WORDS, "a long way")


def tried_word(tries):
    return "no" if tries <= 0 else ("once" if tries == 1 else "several times")


def sector_word(bearing):
    """The eight-point direction, the same vocabulary the sector heads used."""
    import decision_graph as dg
    return dg.sector_of(bearing)


def threat_word(cand, rules):
    """What is standing near the target, judged with the knowledge file open.

    The payload reports a class and a count, which are facts. "Deadly" is a judgement, and it belongs
    here, where doom_rules.yaml is in hand -- and the danger ranks in that file are tunable, so this is
    one of the few words an experiment can move without touching the rubric.
    """
    cls = cand.get("threat_class")
    count = int(cand.get("threat_count", 0) or 0)
    if cls is None or cls == 255 or not count:
        return "none"
    name = ENEMY_CLASSES[cls] if isinstance(cls, int) and cls < len(ENEMY_CLASSES) else str(cls)
    danger = (rules.get("monsters", {}).get(name, {}) or {}).get("danger", 3)
    if count > 1:
        danger += 2
    return "a straggler" if danger <= 3 else "dangerous" if danger <= 6 else "deadly"


def gate_word(cand, keys_held):
    """What stands in the way of an opening: nothing, a door, or a locked door and whether its key is held.

    One word for every way on, so that "the corridor" and "the door at the end of the corridor" are the
    same kind of thing with one field different -- which is what they are.
    """
    if cand.get("kind") != "door":
        return "none"
    colour = cand.get("colour") or ""
    if colour in ("red", "blue", "yellow"):
        return "a %s locked door, %s" % (colour, "the key is held" if colour in keys_held else "no key yet")
    return "a door, shut"


def relative_distance(cand, all_cands):
    """How far it is compared with the other options, which is the comparison a choice actually rests on.

    An absolute band cannot separate "everything is far" from "this one is far and the rest are next
    door", and the second is the situation where the answer matters.
    """
    others = [c.get("path_units", 0.0) for c in all_cands]
    if len(others) < 2:
        return "the only one"
    mine = cand.get("path_units", 0.0)
    if mine <= min(others):
        return "the nearest"
    if mine >= max(others):
        return "the furthest"
    mid = sorted(others)[len(others) // 2]
    return "nearer than most" if mine < mid else "further than most"


def target_words(cand, need, keys_held, rules=None, all_cands=()):
    """One candidate as the handful of words a decision about it rests on.

    Words, never numbers, and never coordinates: a classifier is not a calculator, and a raw map position
    in the state is noise it has to see past. The world position rides in the INTENT instead, where code
    uses it to aim.
    """
    kind = cand.get("kind", "frontier")
    words = {
        "what": KIND_WORDS.get(kind, kind),
        "how_far": dist_word(cand.get("path_units", 0.0)),
        "relative_distance": relative_distance(cand, all_cands or [cand]),
        "direction": sector_word(cand.get("bearing", 0.0)),
        "unseen_ground_behind_it": novelty_word(cand.get("novelty", 0)),
        "tried_before": tried_word(cand.get("tries", 0)),
        "threat": threat_word(cand, rules or {}),
    }
    if kind in ("frontier", "door"):
        # A door is an opening with a gate (brief 7.3), so it is described the same way a frontier is.
        words["the_way_on_is"] = opening_word(cand.get("opening", 0))
        words["unknown_runs"] = depth_word(cand.get("depth", 0))
        words["further_out_than_here"] = "yes" if cand.get("away", True) else "no"
        words["further_from_the_start"] = OUTWARD_WORDS.get(cand.get("outward", 1), "about as far out")
        words["gate"] = gate_word(cand, keys_held)
    if kind == "door" and cand.get("colour") in ("red", "blue", "yellow"):
        words["locked"] = cand["colour"] + (" (held)" if cand["colour"] in keys_held else " (no key)")
    if kind == "item":
        words["needed_now"] = "yes" if cand.get("colour") == need else "no"
    return words


def build_state(t, candidates, needs, keys_held, mode="explore", rules=None):
    """The state document the target and need heads see. No numbers, no policy prose."""
    need = first_need(needs)
    targets = {}
    for i, c in enumerate(candidates):
        targets["t%d" % i] = target_words(c, need, keys_held, rules, candidates)
    hp = t.get("HEALTH")
    return {
        "here": {"mode": mode,
                 "health": _health(hp),
                 "armor": _armor(t.get("ARMOR")),
                 "ammunition": _ammo(t),
                 "keys_held": ", ".join(keys_held) or "none",
                 "stuck": "yes" if t.get("STUCK") else "no"},
        "needs": {k: needs.get(k, "none") for k in NEEDS},
        "combat": combat_words(t, rules or {}),
        "targets": targets,
    }


def combat_words(t, rules):
    """What has been met, in the words the engage and weapon heads weigh.

    The payload names the class; the danger rank comes from knowledge/doom_rules.yaml. Splitting it that
    way is what lets an experiment move a danger rank without touching a rubric.
    """
    count = int(t.get("THREAT_COUNT", t.get("ENEMY_COUNT", 0)) or 0)
    if not count:
        return {"threat": "none", "what": "nothing in view", "count": "none", "distance": "none"}
    cls = t.get("THREAT_CLASS")
    name = (ENEMY_CLASSES[int(cls)] if isinstance(cls, (int, float)) and 0 <= int(cls) < len(ENEMY_CLASSES)
            else str(cls or "something"))
    danger = (rules.get("monsters", {}).get(name, {}) or {}).get("danger", 3)
    dist = float(t.get("ENEMY_DIST", 0) or 0)
    return {
        "threat": ("a straggler" if danger <= 3 else "dangerous" if danger <= 6 else "deadly"),
        "what": name,
        "count": "one" if count == 1 else "a couple" if count <= 3 else "a crowd",
        "distance": ("point blank" if dist < 120 else "close" if dist < 320
                     else "mid-range" if dist < 700 else "far"),
    }


def _health(hp):
    hp = 100 if hp is None else hp
    return "critical" if hp < 35 else "low" if hp < 50 else "fine" if hp < 80 else "full"


def _armor(a):
    a = 0 if a is None else a
    return "none" if a <= 0 else "some" if a < 50 else "good"


def _ammo(t):
    shells, bullets = int(t.get("SHELLS", 0) or 0), int(t.get("BULLETS", 0) or 0)
    total = shells * 4 + bullets
    return "empty" if total <= 0 else "scarce" if total < 30 else "ready"


def needs_from(t, rules):
    """Which of health, ammo and armor are actually wanted, in the knowledge file's own thresholds."""
    b = rules.get("behaviour", {})
    hp = int(t.get("HEALTH", 100) or 100)
    armor = int(t.get("ARMOR", 0) or 0)
    shells, bullets = int(t.get("SHELLS", 0) or 0), int(t.get("BULLETS", 0) or 0)
    low = b.get("ammo_low", {})
    out = {}
    out["health"] = ("urgent" if hp < b.get("health_critical", 30)
                     else "wanted" if hp < b.get("health_low", 50)
                     else "nice to have" if hp < b.get("health_comfortable", 80) else "none")
    out["ammo"] = ("urgent" if shells + bullets == 0
                   else "wanted" if shells < low.get("shells", 6) and bullets < low.get("bullets", 20)
                   else "none")
    out["armor"] = "wanted" if armor < b.get("armor_low", 25) else "none"
    return out


def first_need(needs):
    for level in ("urgent", "wanted"):
        for k in NEEDS:
            if needs.get(k) == level:
                return k
    return None


# ---------------------------------------------------------------- questions
def questions(state, cfg, ask_need=False):
    """One Score per candidate, in one call. Charter 3.3 and the fan-out the Valyu guide describes."""
    out = {}
    spec = cfg["questions"]["target"]
    for tid in state["targets"]:
        q = {"type": "score", "criteria": [c.replace("{t}", tid) for c in spec["criteria"]],
             "instructions": {k: v.replace("{t}", tid) for k, v in spec["instructions"].items()}}
        out["g_" + tid] = q
    if state.get("combat", {}).get("threat", "none") != "none" and "engage" in cfg["questions"]:
        # only when something has actually been met: a head asked about an empty room is latency for nothing
        for head in ("engage", "weapon"):
            spec = cfg["questions"].get(head)
            if spec:
                out[head] = {"type": "choice", "criteria": spec["criteria"],
                             "instructions": dict(spec["instructions"])}
    if ask_need and "need" in cfg["questions"]:
        spec = cfg["questions"]["need"]
        for kind in NEEDS:
            out["n_" + kind] = {"type": "score",
                                "criteria": [c.replace("{need}", kind) for c in spec["criteria"]],
                                "instructions": {k: v.replace("{need}", kind)
                                                 for k, v in spec["instructions"].items()}}
    return out


# ---------------------------------------------------------------- the code baseline
def rule_score(w, levels=RULE_LEVELS):
    """The plain baseline: exit, key, an untried door, then whichever unexplored edge is nearest.

    Deliberately simpler than the rubric, and deliberately blind to everything the rubric asks the model
    to weigh -- what is standing near the target, how much health and ammunition there is to spend on it,
    whether a detour answers a need that is real now. This is the null hypothesis. Writing it as a
    restatement of the rubric is how the sector head ended up agreeing with ten lines of code 89% of the
    time: if the rule and the rubric read the same fields the same way, the model can only reproduce the
    rule, and the comparison measures nothing.

    It is also the fallback when the answers are too close to call, so it has to have an opinion about
    everything, and it must never come down to a coin toss.
    """
    what, tried = w["what"], w["tried_before"]
    if what == "the level exit":
        return float(levels - 1)
    if what == "a key":
        return float(levels - 2)
    if what == "a door":
        # The rule keeps preferring an untried door, and that is the point: the rubric no longer does, so
        # the two now disagree about something real and the comparison measures a judgement rather than a
        # restatement. PROGRAM.md's behavioural test guards this staying simpler than the rubric.
        return float(levels - 3) if tried == "no" else 0.0
    if what == "unexplored edge":
        # Distance only. The rule does not look at how wide the way on is or how far the unknown runs
        # past it -- that is what the rubric asks the model to weigh, and a rule that read the same
        # fields would make the comparison meaningless.
        near = {"the nearest": 0, "the only one": 0, "nearer than most": 1,
                "further than most": 2, "the furthest": 3}.get(w.get("relative_distance"), 2)
        return max(1.0, float(levels - 4 - near))
    if what == "a pickup":
        return float(levels - 6) if w.get("needed_now") == "yes" else 1.0
    return 1.0


def rule_answers(state, qids, levels=RULE_LEVELS):
    """Every asked question answered by the rule, in the shape a System One reply has."""
    out = {}
    for qid in qids:
        if qid.startswith("g_"):
            out[qid] = {"type": "score", "score": rule_score(state["targets"][qid[2:]], levels),
                        "confidence": 1.0}
        elif qid.startswith("n_"):
            want = state["needs"].get(qid[2:], "none")
            out[qid] = {"type": "score", "confidence": 1.0,
                        "score": {"urgent": 3.0, "wanted": 2.0, "nice to have": 1.0}.get(want, 0.0)}
    return out


# ---------------------------------------------------------------- picking
class TargetMemory:
    """Commitment, in the same shape the sector memory had: hold a choice until something clearly better.

    The first planner in this project was removed because it "flipped between equal-cost routes every
    replan". That is a commitment problem, not a planning problem, and this is the commitment.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.committed = None      # (x, y) of the target being walked to
        self.held = 0
        self.gave_up = {}          # (rx, ry) -> ticks left before it is worth trying again
        self.fallbacks = 0
        self.changes = 0
        self.give_ups = 0
        self._since_progress = 0   # decisions committed to this target without getting closer to it
        self._best = None          # the closest we have been to it

    @staticmethod
    def key(x, y):
        return (round(x / 64.0), round(y / 64.0))

    def step(self):
        self.held += 1
        for k in list(self.gave_up):
            self.gave_up[k] -= 1
            if self.gave_up[k] <= 0:
                del self.gave_up[k]

    def give_up(self, x, y, ticks):
        self.gave_up[self.key(x, y)] = ticks

    def gave_up_recently(self, x, y):
        return self.key(x, y) in self.gave_up

    def commit(self, x, y):
        k = self.key(x, y)
        if self.committed is not None and self.is_committed(x, y):
            # The same place as last time, a cell along. Follow it without forgetting how long it has
            # been held: resetting `held` here is what stopped the commitment bonus ever being earned.
            self.committed = k
            return
        if self.committed != k:
            self.committed = k
            self.held = 0
            self.changes += 1
            self._since_progress, self._best = 0, None

    def note_progress(self, distance, stall_after):
        """Watch the distance to the committed target, and give up when it stops falling.

        The flight status check stalled here: 187 of 342 decisions in OPERATE, 69 of them consecutive at
        the end, standing at a door pressing Use with the level untouched around it. `give_up` existed
        and nothing ever called it, so a target once chosen was chosen forever. This is the call.

        Returns True when the target has just been abandoned.
        """
        if distance is None:
            return False
        if self._best is None or distance < self._best - 8.0:
            self._best, self._since_progress = distance, 0
            return False
        self._since_progress += 1
        return self._since_progress >= int(stall_after)

    def is_committed(self, x, y):
        """The same place, not the same coordinates.

        A frontier recedes. Walk toward the edge of the known and the edge moves, so the cell offered on
        the next decision is next door to the one offered on this one -- and with an exact key, that is a
        different target, `held` resets, the commitment margin never applies, and the pilot is free to
        change its mind. Measured on the dev bench: the target changed once every 6.7 decisions, which at
        about two decisions a second is a new destination every three and a half seconds. A player cannot
        walk anywhere in three and a half seconds.

        `WorldModel.times_tried` already counts neighbours for exactly this reason. This is the same fact
        on the other side of the link.
        """
        if self.committed is None:
            return False
        kx, ky = self.key(x, y)
        return abs(kx - self.committed[0]) <= 1 and abs(ky - self.committed[1]) <= 1


def pick(answers, state, candidates, cfg, mem):
    """The best candidate, with commitment and the unsure band. Returns (index, detail)."""
    sel = cfg["select"]
    scored = {}
    for i, _c in enumerate(candidates):
        a = answers.get("g_t%d" % i)
        if a is None:
            continue
        scored[i] = _raw(a)
    if not scored:
        return None, {"fallback": "no answers"}
    # code-side adjustments: a target given up on recently is worth less, whatever the model says
    for i, c in enumerate(candidates):
        if i in scored and mem.gave_up_recently(c["x"], c["y"]):
            scored[i] -= float(sel.get("tried_penalty", 1.0))

    order = sorted(scored, key=lambda i: -scored[i])
    best = order[0]
    gap = scored[order[0]] - scored[order[1]] if len(order) > 1 else 99.0
    conf = _conf(answers.get("g_t%d" % best))
    detail = {"gap": round(gap, 3), "confidence": round(conf, 2), "n": len(scored)}

    if gap < float(sel["unsure_gap"]) or conf < float(sel["unsure_conf"]):
        # a near tie is not a reason to dither: fall back to the exact rule, which always has an opinion
        rule = {i: rule_score(state["targets"]["t%d" % i]) for i in scored}
        best = max(rule, key=lambda i: (rule[i], -candidates[i]["path_units"]))
        detail["fallback"] = "unsure gap" if gap < float(sel["unsure_gap"]) else "unsure answer"
        mem.fallbacks += 1

    # hold what we are already walking to unless the new choice beats it by a margin
    for i, c in enumerate(candidates):
        if mem.is_committed(c["x"], c["y"]) and i in scored and i != best:
            margin = float(sel.get("target_margin", sel["sector_margin"]))
            if mem.held < int(sel["commit_ticks"]):
                margin += float(sel.get("target_commit_bonus", sel["commit_bonus"]))
            # No 1.0 cap here. That cap belongs to the sector head, where the eight options all cost the
            # same to try; a target already half walked to is not in that position, and abandoning it for
            # something one level better means paying for the journey twice.
            margin = min(margin, 3.0)
            detail["margin"] = round(margin, 3)
            if scored[best] - scored[i] < margin:
                best, detail["held"] = i, True
            break
    mem.commit(candidates[best]["x"], candidates[best]["y"])
    detail["score"] = round(scored.get(best, 0.0), 3)
    return best, detail


def _raw(a):
    if not isinstance(a, dict):
        return 0.0
    if a.get("score") is not None:
        return float(a["score"])
    probs = a.get("probabilities") or {}
    return sum(float(k) * float(v) for k, v in probs.items()) if probs else 0.0


def _conf(a):
    if not isinstance(a, dict):
        return 0.0
    if a.get("confidence") is not None:
        return float(a["confidence"])
    probs = a.get("probabilities") or {}
    return max(probs.values()) if probs else 0.0


# ---------------------------------------------------------------- the intent
MODE_INDEX = {"EXPLORE": 0, "APPROACH": 1, "OPERATE": 2, "FIGHT": 3, "RETREAT": 4, "RECOVER": 5}
STANCE_INDEX = {"advance": 0, "advance_strafing": 1, "hold": 2, "retreat": 3}
FIRE_NONE, FIRE_ANY_ATTACKER, FIRE_NEAREST, FIRE_TARGET = range(4)
WEAPON_KEEP = 255


ENGAGE_MODE = {"Fight where I stand": ("FIGHT", "hold"),
               "Fight while moving": ("FIGHT", "advance_strafing"),
               "Break off and go round": ("EXPLORE", "advance"),
               "Retreat": ("RETREAT", "retreat")}
WEAPON_SLOT = {"Fist": 1, "Pistol": 2, "Shotgun": 3, "Chaingun": 4, "RocketLauncher": 5}


def engage_backstop(t, cfg):
    """What to do about a fight when the head was not asked, or its answer cannot be used.

    Deliberately neutral, and that is the whole design. Fight, avoid or retreat is a judgement the
    charter gives to the model; a backstop that picks a fight is not a backstop, it is the code making
    the decision and then being compared against the model on it.

    The first executor baseline had no rule here at all and fell through to FIGHT every time, which is
    how the dev set went from 34 deaths to 142 -- and it meant the code baseline was the most dangerous
    player in the comparison, so a jev-versus-code row on combat was measuring the code's recklessness
    rather than the model's judgement. The default is now "break off and keep moving to the target".
    The executor still shoots whatever lines up with the crosshair on the way past; this is not pacifism,
    it is declining to choose a fight.

    The one thing the rule does decide is when to run, because that is a safety floor rather than a
    judgement: critically hurt, outnumbered while hurt, or nothing loaded.
    """
    th = cfg["thresholds"]
    hp = int(t.get("HEALTH", 100) or 100)
    enemies = int(t.get("ENEMY_COUNT", 0) or 0)
    no_ammo = not int(t.get("SHELLS", 0) or 0) and not int(t.get("BULLETS", 0) or 0)
    outgunned = hp < int(th["health_critical"]) or (enemies > 2 and hp < int(th["health_low"]))
    return "Retreat" if (outgunned or no_ammo) else "Break off and go round"


def weapon_backstop(t, answer, rules):
    """The rule that overrules the head: never a splash weapon at point blank, never an empty one."""
    slot = WEAPON_SLOT.get(answer)
    dist = float(t.get("ENEMY_DIST", 0) or 0)
    if slot is None:
        return best_weapon_slot(t)
    if slot == 3 and not int(t.get("SHELLS", 0) or 0):
        slot = 2
    if slot in (2, 4) and not int(t.get("BULLETS", 0) or 0):
        slot = 1
    for name, spec in (rules.get("weapons", {}) or {}).items():
        if spec.get("slot") == slot and spec.get("splash") and dist and dist < float(
                (rules.get("behaviour", {}) or {}).get("splash_min_distance", 200)):
            return 3 if int(t.get("SHELLS", 0) or 0) else 2
    equipped = {"FIST": 1, "PISTOL": 2, "SHOTGUN": 3, "OTHER": 4}.get(str(t.get("WEAPON", "PISTOL")), 2)
    return WEAPON_KEEP if slot == equipped else slot


def mode_for(t, cand, cfg, danger_level=None):
    """Which mode an intent is in. Every one of these is an exact rule, so none of them is a question.

    RECOVER is absent on purpose: the executor's watchdog owns it, because a freeze is a property of a
    sequence of tics and the ground only sees one sample of that sequence every half second.
    """
    th, sel = cfg["thresholds"], cfg["select"]
    enemies = int(t.get("ENEMY_COUNT", 0) or 0)
    dist = float(t.get("ENEMY_DIST", 0) or 0)
    hp = int(t.get("HEALTH", 100) or 100)
    threatened = enemies and dist and dist <= float(th["threat_dist"])
    # When the danger head has not been asked, this used to fall through to FIGHT every time, so the
    # player charged everything it met at running speed and never backed off. On the first executor
    # baseline that showed up as 142 deaths across the dev set against 34 for the old gait. With no
    # answer to lean on, the exact rule decides: a fight you cannot win is not a fight.
    outgunned = hp < int(th["health_critical"]) or (enemies > 2 and hp < int(th["health_low"]))
    no_ammo = not int(t.get("SHELLS", 0) or 0) and not int(t.get("BULLETS", 0) or 0)
    if threatened:
        if danger_level is not None:
            return "RETREAT" if danger_level >= float(sel["danger_retreat"]) else "FIGHT"
        return "RETREAT" if (outgunned or no_ammo) else "FIGHT"
    if cand is not None and cand["kind"] in ("door", "exit", "switch"):
        if cand["path_units"] <= float(sel["operate_units"]):
            return "OPERATE"
        return "APPROACH"
    return "EXPLORE"


def best_weapon_slot(t, rules=None):
    """The slot to hold. A rule, not a question, until the weapon head lands in phase 4."""
    shells = int(t.get("SHELLS", 0) or 0)
    bullets = int(t.get("BULLETS", 0) or 0)
    owns_shotgun = bool(t.get("OWN_SHOTGUN"))
    want = 3 if (owns_shotgun and shells > 0) else (2 if bullets > 0 else 1)
    equipped = {"FIST": 1, "PISTOL": 2, "SHOTGUN": 3, "OTHER": 4}.get(str(t.get("WEAPON", "PISTOL")), 2)
    return WEAPON_KEEP if want == equipped else want


def intent_for(t, state, candidates, pick, cfg, mode=None, danger_level=None, intent_id=0, tic=0,
               engage=None, weapon_answer=None, rules=None):
    """Everything the INTENT command carries, from the pick, the engage answer and a few exact rules."""
    sel = cfg["select"]
    cand = candidates[pick] if pick is not None and pick < len(candidates) else None
    stance = "advance"
    if engage in ENGAGE_MODE:
        mode, stance = ENGAGE_MODE[engage]
        if mode == "EXPLORE" and cand is not None and cand["kind"] in ("door", "exit", "switch"):
            mode = "OPERATE" if cand["path_units"] <= float(sel["operate_units"]) else "APPROACH"
    else:
        mode = mode or mode_for(t, cand, cfg, danger_level)
        if mode == "FIGHT":
            stance = "advance_strafing"
        elif mode == "RETREAT":
            stance = "retreat"
        elif mode == "OPERATE":
            # Holding still at a door is fine in an empty room and fatal in a fight: 37 of 203 deaths.
            # With something in view, keep moving and keep shooting; the Use press is pulsed either way.
            threatened = int(t.get("ENEMY_COUNT", 0) or 0) and float(t.get("ENEMY_DIST", 0) or 0) <= float(
                cfg["thresholds"]["threat_dist"])
            if threatened:
                stance = "advance_strafing"
            else:
                # Not "hold". A player opening a door walks into it and taps Use; they do not stop
                # forty-eight units short and stand there. Holding was six of seventeen freezes in the
                # 150 s check -- the watchdog counting a deliberate stand-still as a stuck player -- and
                # every one of those cost four seconds plus a recovery.
                stance = "advance"
    return {
        "intent_id": int(intent_id) & 0xFFFF,
        "based_on_tic": int(t.get("TIC", tic) or 0),
        "mode": mode,
        "target_x": float(cand["x"]) if cand else 0.0,
        "target_y": float(cand["y"]) if cand else 0.0,
        "has_target": cand is not None,
        "stance": stance,
        # Always. A retreat that does not return fire is a slower death -- it was half the deaths on the
        # dev set (RETREAT x99 of 203), because the player turned its back and stopped shooting at the
        # one moment something was shooting at it.
        "fire_policy": FIRE_ANY_ATTACKER,
        "fire_target_id": 255,
        "weapon": weapon_backstop(t, weapon_answer, rules or {}) if weapon_answer else best_weapon_slot(t),
        "use_at_target": bool(cand and cand["kind"] in ("door", "exit", "switch")),
        "ttl_ms": int(sel.get("intent_ttl_ms", 1500)),
    }


def decide(t, candidates, cfg, mem, system_one, rules, n=0, ask_need=False, cache=None):
    """One targeting decision, start to finish. The flight pilot and the bench runner both call this."""
    import decision_graph as dg
    mem.step()
    keys = _keys_held(t)
    needs = needs_from(t, rules)
    state = build_state(t, candidates, needs, keys, rules=rules)
    qs = questions(state, cfg, ask_need=ask_need) if candidates else {}
    answers, reply = {}, {"latency_ms": 0}
    sent = dg.state_for(state, qs) if qs else state
    unavailable = None
    if qs:
        hit = cache.get(sent, qs) if cache is not None else None
        if hit is not None:
            reply = dict(hit, cached=True, latency_ms=0)
        else:
            try:
                reply = system_one.ask(sent, qs)
                if cache is not None:
                    cache.put(sent, qs, reply)
            except Exception as e:                             # noqa: BLE001
                # The model is unreachable or slow. That is an operational fact, not a reason to throw
                # away the attempt: the code rule exists precisely for the ticks the model cannot answer,
                # and a pilot that stops flying because a request timed out is a worse pilot than one
                # that falls back. Six attempts out of fifteen were being voided by a 10 s read timeout.
                unavailable = "%s: %s" % (type(e).__name__, str(e)[:120])
                reply = {"answers": rule_answers(state, qs), "latency_ms": 0, "model": "code (fallback)",
                         "usage": {"input_tokens": 0}, "unavailable": unavailable}
        answers = reply["answers"]
    pick_i, detail = (None, {}) if not qs else pick(answers, state, candidates, cfg, mem)
    # A target we are committed to but getting no closer to is abandoned, and stays unattractive for a
    # while. Without this the pilot can pick a door it cannot open and stand there for the rest of the
    # attempt -- which is exactly what the first full-pipeline flight did.
    if pick_i is not None and candidates:
        c = candidates[pick_i]
        if mem.is_committed(c["x"], c["y"]) and mem.note_progress(c.get("path_units"),
                                                                  cfg["select"]["approach_ticks"]):
            mem.give_up(c["x"], c["y"], int(cfg["select"]["target_give_up_ticks"]))
            mem.give_ups += 1
            detail["gave_up"] = True
            remaining = [i for i in range(len(candidates))
                         if not mem.gave_up_recently(candidates[i]["x"], candidates[i]["y"])]
            if remaining:
                rule = {i: rule_score(state["targets"]["t%d" % i]) for i in remaining}
                pick_i = max(rule, key=lambda i: (rule[i], -candidates[i]["path_units"]))
                mem.commit(candidates[pick_i]["x"], candidates[pick_i]["y"])
    engage = (answers.get("engage") or {}).get("choice")
    if state.get("combat", {}).get("threat", "none") != "none" and engage not in ENGAGE_MODE:
        engage = engage_backstop(t, cfg)
        detail["engage_fallback"] = True
    detail["engage"] = engage
    if pick_i is None and candidates:
        # no answers at all: still go somewhere, on the rule alone
        rule = {i: rule_score(state["targets"]["t%d" % i]) for i in range(len(candidates))}
        pick_i = max(rule, key=lambda i: (rule[i], -candidates[i]["path_units"]))
        detail = {"fallback": "no answers"}
        mem.commit(candidates[pick_i]["x"], candidates[pick_i]["y"])
    intent = intent_for(t, state, candidates, pick_i, cfg, intent_id=n, tic=n, engage=engage,
                        weapon_answer=(answers.get("weapon") or {}).get("choice"), rules=rules)
    return {"state": state, "sent": sent, "questions": qs, "answers": answers, "reply": reply,
            "pick": pick_i, "detail": detail, "intent": intent, "needs": needs,
            "mode": intent["mode"], "code_only": not qs, "cached": bool(reply.get("cached")),
            "unavailable": unavailable}


def _keys_held(t):
    bits = int(t.get("KEYS", 0) or 0)
    return [name for bit, name in ((1, "red"), (2, "blue"), (4, "yellow")) if bits & bit]


def candidates_from(t, max_n=8):
    """The candidate list as it arrives in telemetry: CAND0..CAND7 plus a count."""
    out = []
    for i in range(int(t.get("CAND_COUNT", 0) or 0)):
        c = t.get("CAND%d" % i)
        if not c:
            continue
        out.append(normalise(c, t))
        if len(out) >= max_n:
            break
    return out


KINDS = ("frontier", "door", "exit", "key", "item", "switch", "enemy")
COLOURS = ("", "red", "blue", "yellow")


def bearing_to(px, py, heading, tx, ty):
    """Signed bearing to a point relative to the heading; positive means left, as everywhere else here."""
    return (math.degrees(math.atan2(ty - py, tx - px)) - heading + 180) % 360 - 180


def normalise(c, t):
    """One telemetry candidate as the dict the rest of this module speaks."""
    get = c.get if isinstance(c, dict) else (lambda k, d=None: getattr(c, k, d))
    kind = get("kind", 0)
    kind = KINDS[kind] if isinstance(kind, int) and kind < len(KINDS) else str(kind).lower()
    flags = int(get("flags", 0) or 0)
    x, y = float(get("x", 0.0) or 0.0), float(get("y", 0.0) or 0.0)
    px, py = float(t.get("POS_X", 0.0) or 0.0), float(t.get("POS_Y", 0.0) or 0.0)
    heading = float(t.get("ANGLE", 0.0) or 0.0)
    return {"kind": kind, "x": x, "y": y,
            "bearing": bearing_to(px, py, heading, x, y),
            # "pathUnits" is the name in the F Prime Candidate struct, and the only name Yamcs delivers.
            # Reading "dist" silently returned the default, so every candidate on the flight path arrived
            # at zero distance: jev saw six options all described as "right here" and all "the nearest",
            # scored them 5.00 across the board, and the pick became a coin toss. Two of the ten words it
            # sees are distance words; both were constants. "dist" is kept as a fallback because the bench
            # builds candidates straight from the payload and has always used it.
            "path_units": float(get("pathUnits", None) or get("dist", 0) or 0),
            "novelty": int(get("novelty", 0) or 0),
            "opening": int(get("opening", 0) or 0), "depth": int(get("depth", 0) or 0),
            "away": bool(get("away", 1)),
            # Same mismatch as pathUnits: threat_word reads these two and normalise never set them, so
            # every candidate's threat word was "none" whatever was standing on it. The payload has been
            # measuring and downlinking both all along.
            "threat_class": (None if get("threatClass", get("threat_class", 255)) in (None, 255)
                             else int(get("threatClass", get("threat_class", 255)))),
            "threat_count": int(get("threatCount", get("threat_count", 0)) or 0),
            "colour": COLOURS[flags & 3] if kind == "door" else str(get("need", "") or ""),
            "tries": (flags >> 2) & 15,
            # Bits 6-7: 0 back toward where the level began, 1 about as far out, 2 further out than here.
            # The payload works it out from the player's own spawn and its own position.
            "outward": (flags >> 6) & 3}


# ---------------------------------------------------------------- determinism within a run
class DecisionCache:
    """The same state gets the same answer, every time, for the length of a run. Charter 3.4.

    A System One model is not deterministic across calls, and the replay measured two commands differing
    between identical passes at a gap of 0.20. That is small, and it is still enough that a run cannot be
    reproduced from its log, which makes every comparison slightly unfalsifiable. Quantising the state to
    the words the heads actually see and caching on a hash of those words removes the wobble without
    removing the model: a state that has genuinely changed still gets a fresh call.

    Within a run only. Nothing survives an attempt, here as everywhere else (charter 2.2).
    """

    def __init__(self, enabled=True, limit=20000):
        self.enabled = enabled
        self.limit = limit
        self.hits = 0
        self.misses = 0
        self._by_hash = {}

    @staticmethod
    def key(state, questions):
        import hashlib
        blob = json.dumps({"s": state, "q": sorted(questions)}, sort_keys=True, default=str)
        return hashlib.sha1(blob.encode()).hexdigest()

    def get(self, state, questions):
        if not self.enabled:
            return None
        k = self.key(state, questions)
        hit = self._by_hash.get(k)
        if hit is None:
            self.misses += 1
            return None
        self.hits += 1
        return hit

    def put(self, state, questions, reply):
        if not self.enabled or len(self._by_hash) >= self.limit:
            return
        self._by_hash[self.key(state, questions)] = reply

    @property
    def hit_rate(self):
        total = self.hits + self.misses
        return self.hits / total if total else 0.0
