"""The onboard executor: what the player does between decisions. Charter 3.1 and the executor row of 3.

The ground stops sending buttons and starts sending an INTENT with a time to live: a mode, somewhere to go,
a stance, what to shoot at, which weapon, whether to press Use when it arrives. The executor carries that
out at 35 Hz -- following the path the world model planned, sidestepping what the range camera sees, aiming,
firing, pulsing Use -- and drops into safe behaviour when the intent goes stale.

The point is not autonomy for its own sake. Under the old CONTROL-per-tick scheme the player stood still
while a decision was in flight, which is half a second in every two; measured, that was `idle_fraction`
0.41 and an EXPLORE speed of 66 units per second against a running speed of 507 (payload/speed_probe.py).
A rover does not stop between commands from the ground, and neither should this.

Three things here are deliberately not decisions:

  local avoidance   sidestepping a doorframe is not a question worth half a second of latency
  aiming            an enemy within a few degrees of the crosshair gets shot; no model improves on that
  the watchdog      charter phase 2 wants invariants that pull the player out of a freeze. All three
                    freezes found in September were properties of a sequence of ticks, invisible to every
                    unit test and to the replay, so they are checked continuously and at control rate
"""
import math
import time

TICRATE = 35
RUN_DELTA = 50.0        # Doom's running forwardmove; measured at 507 units/s, and the engine caps there
STRAFE_DELTA = 40.0     # Doom's running sidemove
TURN_PER_TIC = 8.0      # degrees; fast enough to face a threat, slow enough not to overshoot
ALIGN_WALK = 60.0       # walk while the heading is within this of where we want to go
ALIGN_FULL = 25.0       # full speed within this
# How far ahead to look, as a time rather than a distance. At the old delta of 14 the player covered 4
# units a tic and a fixed 72-unit guard was five tics of warning; at a run it covers 14.5 and the same 72
# units is two. A guard that does not scale with speed is a guard that stops working the moment the speed
# is fixed, which is how the first executor baseline came back with four times the deaths.
# 0.12 s, not 0.35. At a run 0.35 s is a 177-unit guard, which is wider than most Doom corridors and
# taller than most rooms are deep -- so `clear_fwd` sat under it almost permanently and the player crawled
# everywhere at a third of its speed. Measured across two flights: under 100 units/s on 75 to 80% of
# samples, at running speed on 1 to 2%. The player has almost no momentum in this engine, so the guard
# only has to stop it grinding into a wall, and turning away is the path planner's job rather than the
# throttle's.
AVOID_SECONDS = 0.12
AVOID_MIN_UNITS = 48.0
# The delta is not map units per tic. payload/speed_probe.py measured delta 50 at 507 units/s, and the
# relation is linear below the engine's cap, so this is the conversion from a button value to a speed.
UNITS_PER_S_PER_DELTA = 507.0 / 50.0
FIGHT_KEEP_UNITS = 260.0   # in a fight, hold this much room rather than closing at a run
FIRE_DEG = 7.0          # an enemy this close to the crosshair is worth a shot
FIRE_UNITS = 900.0
USE_UNITS = 96.0        # press Use when this close to a door or switch we were sent to
SAFE_FIRE_UNITS = 220.0 # in safe mode, only point-blank attackers
# The panorama. 360 degrees at TURN_PER_TIC is about 1.3 s, comfortably inside the watchdog's four, and
# LOOK_SPACING is roughly a large room, so a level costs a handful of them rather than one a corridor.
LOOK_SECONDS = 1.4
LOOK_SPACING = 320.0

MODES = ("EXPLORE", "APPROACH", "OPERATE", "FIGHT", "RETREAT", "RECOVER")
STANCES = ("advance", "advance_strafing", "hold", "retreat")
FIRE_NONE, FIRE_ANY_ATTACKER, FIRE_NEAREST, FIRE_TARGET = range(4)
WEAPON_KEEP = 255


class Intent:
    """What the ground wants, and for how long it is still worth wanting.

    `based_on_tic` is the observation this was decided from. The executor ignores an intent older than one
    it has already applied, so a slow answer overtaking a fast one cannot walk the player backwards.
    """

    __slots__ = ("intent_id", "based_on_tic", "mode", "target_x", "target_y", "has_target", "stance",
                 "fire_policy", "fire_target_id", "weapon", "use_at_target", "ttl_ms", "received")

    def __init__(self, intent_id=0, based_on_tic=0, mode="EXPLORE", target_x=0.0, target_y=0.0,
                 has_target=False, stance="advance", fire_policy=FIRE_ANY_ATTACKER, fire_target_id=255,
                 weapon=WEAPON_KEEP, use_at_target=False, ttl_ms=1500, received=0.0):
        self.intent_id, self.based_on_tic = int(intent_id), int(based_on_tic)
        self.mode = mode if mode in MODES else "EXPLORE"
        self.target_x, self.target_y, self.has_target = float(target_x), float(target_y), bool(has_target)
        self.stance = stance if stance in STANCES else "advance"
        self.fire_policy, self.fire_target_id = int(fire_policy), int(fire_target_id)
        self.weapon, self.use_at_target = int(weapon), bool(use_at_target)
        self.ttl_ms = int(ttl_ms)
        # Stamped by Executor.set_intent from the same clock Executor.step is given, so that a bench
        # driving the executor with its own clock is not silently comparing it against the wall.
        self.received = float(received)

    def expired(self, now):
        return (now - self.received) * 1000.0 > self.ttl_ms

    def age_ms(self, now):
        return (now - self.received) * 1000.0

    def __repr__(self):
        return "<INTENT %d %s%s ttl %dms>" % (self.intent_id, self.mode,
                                              " -> (%.0f,%.0f)" % (self.target_x, self.target_y)
                                              if self.has_target else "", self.ttl_ms)


class Watchdog:
    """Invariants that pull the player out of a freeze, checked every tic.

    Charter phase 2. Each of these is one of the three freezes found in September, turned into a rule:
    OPERATE that could not give up (1,172 decisions at one door), FIGHT on bare visibility (211 decisions
    staring at an enemy 2,139 units away), and a reflex that refused to walk into a known wall and so
    deadlocked the payload's own stuck detector, which needs the player to push (553 decisions in one spot
    with STUCK false). None of them was visible to a unit test, because each is a property of a sequence.
    """

    STILL_SECONDS = 4.0          # no displacement for this long, in any mode
    STILL_UNITS = 48.0
    BLOCKED_SECONDS = 3.0        # every direction reading blocked for this long
    RECOVER_SECONDS = 1.5        # how long a recovery lasts before normal service resumes

    def __init__(self):
        self.track = []           # (t, x, y)
        self.blocked_since = None
        self.recover_until = 0.0
        self.trips = {}
        self.reason = ""
        self.trip_log = []        # what the executor could see each time it had to pull the player out

    def step(self, now, x, y, all_blocked, expire_barriers):
        self.track.append((now, x, y))
        while self.track and now - self.track[0][0] > self.STILL_SECONDS * 2:
            self.track.pop(0)
        if now < self.recover_until:
            return True
        old = [p for p in self.track if now - p[0] >= self.STILL_SECONDS]
        if old:
            p = old[-1]
            if math.hypot(x - p[1], y - p[2]) < self.STILL_UNITS:
                return self._trip(now, "no displacement for %.0f s" % self.STILL_SECONDS)
        if all_blocked:
            self.blocked_since = self.blocked_since or now
            if now - self.blocked_since > self.BLOCKED_SECONDS:
                expire_barriers()
                self.blocked_since = None
                return self._trip(now, "every direction blocked for %.0f s" % self.BLOCKED_SECONDS)
        else:
            self.blocked_since = None
        return False

    def _trip(self, now, reason):
        self.recover_until = now + self.RECOVER_SECONDS
        self.trips[reason] = self.trips.get(reason, 0) + 1
        self.reason = reason
        self.track = [p for p in self.track if now - p[0] < 0.5]
        print("[executor] watchdog: %s -- recovering" % reason, flush=True)
        return True

    def recovering(self, now):
        return now < self.recover_until

    def pause(self, now):
        """Time the executor spent deliberately standing still. It does not count as not moving."""
        self.track = [p for p in self.track if now - p[0] < 0.5]
        self.blocked_since = None


class Executor:
    """Turns an intent plus the last observation into buttons, every tic."""

    def __init__(self, world):
        self.world = world
        self.looked = []           # places a panorama has already been taken from
        self.look_until = 0.0
        self.looks = 0
        self.intent = None
        self.applied_tic = -1
        self.watchdog = Watchdog()
        self.recover_dir = 1
        self.use_phase = 0
        self.last_weapon = WEAPON_KEEP
        self.stats = {"ticks": 0, "safe_ticks": 0, "recover_ticks": 0, "intents": 0, "stale_dropped": 0}

    # ---------------------------------------------------------------- uplink
    def set_intent(self, intent, now=None):
        if self.intent is not None and intent.based_on_tic < self.applied_tic:
            self.stats["stale_dropped"] += 1
            return False
        intent.received = time.time() if now is None else now
        self.intent = intent
        self.applied_tic = max(self.applied_tic, intent.based_on_tic)
        self.stats["intents"] += 1
        return True

    # ---------------------------------------------------------------- the tic
    def step(self, obs, now):
        """`obs` is the payload's fast sensing: x, y, angle, clear_fwd/fl/fr, enemies, ahead_kind/dist."""
        self.stats["ticks"] += 1
        x, y, angle = obs["x"], obs["y"], obs["angle"]
        if self._should_look(obs, now):
            # A panorama is standing still on purpose. Counting it against the freeze watchdog is how the
            # executor ended up triggering its own recoveries: eleven looks of 1.4 s each, inside a 4 s
            # window that wants 48 units of travel, and 16% of the attempt went on recovering from
            # sensing actions it had chosen. The watchdog is for freezes, not for looking.
            self.watchdog.pause(now)
            return self._look(obs)
        tripped = self.watchdog.step(now, x, y, obs.get("all_blocked", False), obs["expire_barriers"])
        if tripped:
            # No more guessing at why it froze: write down what it could see at the moment it did.
            plan = getattr(self.world, "plan", None)
            self.watchdog.trip_log.append({
                "mode": it.mode if (it := self.intent) else None,
                "stance": it.stance if (it := self.intent) else None,
                "clear_fwd": obs["clear_fwd"], "clear_back": obs["clear_back"],
                "clear_fl": obs["clear_fl"], "clear_fr": obs["clear_fr"],
                "ahead": obs["ahead_kind"], "ahead_dist": obs["ahead_dist"],
                "enemies": len(obs["enemies"]), "all_blocked": bool(obs.get("all_blocked")),
                "has_plan": bool(plan and plan.cells), "plan_left": (len(plan.cells) - plan.i) if plan else 0,
                "has_target": bool(self.intent and self.intent.has_target)})
        if tripped or self.watchdog.recovering(now):
            self.stats["recover_ticks"] += 1
            return self._recover(obs)
        it = self.intent
        if it is None or it.expired(now):
            self.stats["safe_ticks"] += 1
            return self._safe(obs)

        want = None
        if it.mode in ("FIGHT", "RETREAT") and obs["enemies"]:
            # Face the threat in both. A Doom player withdrawing walks backwards with the shotgun still
            # pointed at what is chasing it; turning your back and running is how you arrive somewhere
            # else with no health left. Measured: one withdrawal across a courtyard cost 51 health down
            # to 13, every point of it taken from behind, and the retreat-returns-fire fix could not
            # help because nothing was ever in the crosshair.
            want = angle + obs["enemies"][0][1]
        else:
            plan = self.world.plan
            if plan is not None and not plan.blocked:
                pt = plan.advance(x, y)
                if pt is not None:
                    want = math.degrees(math.atan2(pt[1] - y, pt[0] - x))
            if want is None and it.has_target:
                # A target with no plan is a target with no known route, and the payload no longer hands
                # one over: it matches the intent to an offered candidate, re-routes to the nearest
                # reachable one if that fails, and clears the target if nothing is reachable. Counted
                # here so that if it ever happens again it is visible rather than a mystery freeze.
                if plan is None or plan.blocked:
                    self.stats["no_plan_ticks"] = self.stats.get("no_plan_ticks", 0) + 1
                want = math.degrees(math.atan2(it.target_y - y, it.target_x - x))
        if want is None:
            want = angle

        rel = (want - angle + 180) % 360 - 180
        cmd = {"turn": max(-TURN_PER_TIC, min(TURN_PER_TIC, rel)), "move": 0.0, "strafe": 0.0,
               "fire": 0, "use": 0, "weapon": it.weapon}

        if it.stance == "hold":
            pass
        elif it.stance == "retreat":
            # Backwards, facing the threat, still shooting. `move` is negative and the heading is the
            # enemy's, so this withdraws from it rather than toward it.
            cmd["move"] = -RUN_DELTA if obs["clear_back"] > 64 else 0.0
            cmd["strafe"] = STRAFE_DELTA * self._freer_side(obs)
        else:
            speed = 0.0
            if abs(rel) <= ALIGN_FULL:
                speed = RUN_DELTA
            elif abs(rel) <= ALIGN_WALK:
                speed = RUN_DELTA * 0.6
            # The guard scales with how fast we are actually going, so it is the same amount of warning
            # at a run as it was at a walk.
            guard = max(AVOID_MIN_UNITS, speed * UNITS_PER_S_PER_DELTA * AVOID_SECONDS)
            if obs["clear_fwd"] <= guard and obs["ahead_kind"] not in ("door", "exit"):
                # something solid ahead: keep the heading, step around it, and slow down first
                cmd["strafe"] = STRAFE_DELTA * self._freer_side(obs)
                speed *= 0.5 if obs["clear_fwd"] > AVOID_MIN_UNITS else 0.15
            cmd["move"] = speed
            if it.stance == "advance_strafing" and obs["enemies"]:
                cmd["strafe"] = STRAFE_DELTA * self._circle_side(now)
                # Do not close on something that is already shooting at us. Charging at a run was worth
                # four times the deaths on the first executor baseline.
                if obs["enemies"][0][2] < FIGHT_KEEP_UNITS:
                    cmd["move"] = min(cmd["move"], 0.0)

        cmd["fire"] = int(self._should_fire(it, obs))
        cmd["use"] = int(self._should_use(it, obs, x, y))
        return cmd

    def _should_look(self, obs, now):
        """A panorama on arriving somewhere new, the way a rover takes one at the end of a drive.

        The camera has a 90 degree field of view, so the automap only fills in where the player happens
        to be facing, and it fills in slowly. One turn on the spot when the player reaches ground it has
        not stood near before is worth more map than a minute of walking and looking forward. It is a
        sensing routine, so code owns it outright -- it decides nothing about where to go.

        It is skipped when anything is in view: a second and a half spinning in front of a monster is a
        second and a half of free shots.
        """
        if now < self.look_until:
            return True
        if obs["enemies"]:
            return False
        x, y = obs["x"], obs["y"]
        if any(math.hypot(x - px, y - py) < LOOK_SPACING for px, py in self.looked):
            return False
        self.looked.append((x, y))
        if len(self.looked) > 400:
            self.looked.pop(0)
        self.look_until = now + LOOK_SECONDS
        self.looks += 1
        return True

    def _look(self, obs):
        """Turn on the spot, seeing. Nothing else: no walking into what has not been looked at yet."""
        self.stats["look_ticks"] = self.stats.get("look_ticks", 0) + 1
        return {"turn": TURN_PER_TIC, "move": 0.0, "strafe": 0.0, "fire": 0, "use": 0,
                "weapon": WEAPON_KEEP}

    # ---------------------------------------------------------------- pieces
    @staticmethod
    def _freer_side(obs):
        """+1 strafes left, -1 right. Sidestep toward whichever shoulder the camera says is freer."""
        return 1.0 if obs["clear_fl"] >= obs["clear_fr"] else -1.0

    @staticmethod
    def _circle_side(now):
        return 1.0 if int(now * 1.5) % 2 == 0 else -1.0

    @staticmethod
    def _should_fire(it, obs):
        if it.fire_policy == FIRE_NONE or not obs["enemies"]:
            return False
        if not obs.get("has_ammo", True):
            return False
        _absb, bearing, dist, _lab = obs["enemies"][0]
        if abs(bearing) > FIRE_DEG or dist > FIRE_UNITS:
            return False
        if it.fire_policy == FIRE_ANY_ATTACKER:
            return dist < FIRE_UNITS
        return True

    def _should_use(self, it, obs, x, y):
        """Use is a press, not a hold: Doom triggers it on the edge, so it has to be pulsed."""
        near_target = it.has_target and math.hypot(it.target_x - x, it.target_y - y) <= USE_UNITS
        usable = obs["ahead_kind"] in ("door", "exit") and obs["ahead_dist"] <= 80
        if not ((it.use_at_target and (near_target or usable)) or (it.mode == "OPERATE" and usable)):
            self.use_phase = 0
            return False
        self.use_phase = (self.use_phase + 1) % 8
        return self.use_phase == 1

    def _safe(self, obs):
        """No intent, or a stale one: stop, face the nearest attacker, shoot only what is on top of us."""
        cmd = {"turn": 0.0, "move": 0.0, "strafe": 0.0, "fire": 0, "use": 0, "weapon": WEAPON_KEEP}
        if obs["enemies"]:
            _absb, bearing, dist, _lab = obs["enemies"][0]
            cmd["turn"] = max(-TURN_PER_TIC, min(TURN_PER_TIC, bearing))
            cmd["fire"] = int(dist <= SAFE_FIRE_UNITS and abs(bearing) <= FIRE_DEG and obs.get("has_ammo", True))
        return cmd

    def _recover(self, obs):
        """Always command motion.

        The payload's stuck detector needs the player to push against something to learn it is there, so a
        recovery that stands still deadlocks it -- 553 decisions in one spot with STUCK false, in September.
        Back off, turn, and keep pushing.
        """
        self.world.clear_plan()
        back = obs["clear_back"] > 64
        return {"turn": TURN_PER_TIC * self.recover_dir,
                "move": -RUN_DELTA * 0.7 if back else RUN_DELTA * 0.5,
                "strafe": STRAFE_DELTA * self._freer_side(obs),
                "fire": 0, "use": 1 if obs["ahead_kind"] in ("door", "exit") else 0,
                "weapon": WEAPON_KEEP}
