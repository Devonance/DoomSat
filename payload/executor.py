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
# 15 degrees a tic is 525 a second, which turns the player right around in a third of a second.
# At 8 it took two thirds, and a measured half of all executor ticks were spent not moving --
# 62% of them turning. A Doom player turns as fast as the mouse moves.
TURN_PER_TIC = 15.0
# How far off line the player may be and still move. 25 degrees was too strict: a path through a room
# bends more than that between waypoints, so the throttle sat at part power for half the level. A Doom
# player runs and turns at the same time.
ALIGN_WALK = 140.0      # more than this off the aim point and there is nothing to do but turn
PLAYER_RADIUS = 16.0    # the engine's own number, and the margin a throttle has to leave
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
# Rubbing: pressed against geometry, commanding movement, going nowhere. Every one of the 18 freezes in
# the 150 s time check was this -- APPROACH, a plan, a wall ahead, and four seconds of scraping before the
# watchdog noticed. Doom slides the player along a wall for free, so the answer to a wall is not to crawl
# at 15% speed into it; it is to keep the throttle on, lean off the wall, and alternate shoulders so a
# corner that swallows one side gets tried from the other. Half a second of correction instead of four
# seconds of freeze plus a recovery.
RUB_SECONDS = 0.45      # no real displacement for this long while asking to move
RUB_UNITS = 12.0        # "no real displacement"; a run covers 228 units in that time
RUB_FLIP_S = 0.7        # how long to try one shoulder before trying the other
RUB_TURN_DEG = 40.0     # lean this far off the heading, the angle a player takes to slide past a corner
# And when leaning off the wall does not work, say so. Path length alone cannot catch a wedge: a player
# scraping a corner still covers 48 units in four seconds, so the watchdog stayed quiet through a flight
# that spent 38% of its ticks pressed against geometry at full throttle -- one freeze logged, and the
# level crossed at 93 units a second instead of 507. "Asked to move and did not" is the honest test, and
# two and a half seconds of it is not a corner being rounded.
RUB_STUCK_S = 2.5

FIGHT_KEEP_UNITS = 260.0   # in a fight, hold this much room rather than closing at a run
FIRE_DEG = 7.0          # an enemy this close to the crosshair is worth a shot
FIRE_UNITS = 900.0
USE_UNITS = 96.0        # press Use when this close to a door or switch we were sent to
SAFE_FIRE_UNITS = 220.0 # in safe mode, only point-blank attackers
# The panorama. 360 degrees at TURN_PER_TIC is about 1.3 s, comfortably inside the watchdog's four, and
# LOOK_SPACING is roughly a large room, so a level costs a handful of them rather than one a corridor.
LOOK_SECONDS = 0.8
LOOK_SPACING = 256.0   # measured on five paired seeds of E1M1: at 512 the suite scored 0.069 and
                       # recalled half the doors it walked up to, at 256 it scored 0.214 and recalled all
                       # ten, at 160 it scored 0.160 -- looking is what fills the automap, and the automap
                       # is where the frontiers come from, but a panorama is also seven tenths of a second
                       # of not travelling

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
        # Ground covered, not net displacement. Displacement from the position four seconds ago cannot
        # tell a player wedged in a corner from one that walked three hundred units to a target, changed
        # its mind, and walked three hundred units back: both end up inside the 48-unit circle. The second
        # is indecision, and the recovery that follows -- which clears the plan -- makes it worse. Forty
        # freezes in one 190 s flight were logged with clear_fwd 400 and every shoulder open; nothing
        # there was stuck. Path length says what the leg muscles did.
        window = [p for p in self.track if now - p[0] <= self.STILL_SECONDS]
        if window and now - window[0][0] >= self.STILL_SECONDS * 0.9:
            covered = sum(math.hypot(b[1] - a[1], b[2] - a[2])
                          for a, b in zip(window, window[1:]))
            if covered < self.STILL_UNITS:
                return self._trip(now, "went nowhere for %.0f s" % self.STILL_SECONDS)
            # Moving, and not getting anywhere. Path length alone cannot see this and neither can
            # displacement alone, which is why both tests are here: the rub correction leans forty
            # degrees off the heading and alternates shoulders, so a wedged player covers hundreds of
            # units inside a box a few feet across and every motion test reads "fine". Measured on the
            # oracle rung with the exit finally in the candidate list: the player travelled from
            # (-416,256) to (-380,431) in 180 seconds -- 175 units of displacement, APPROACH on 98% of
            # its decisions, and not one watchdog trip in the whole attempt.
            moved = math.hypot(window[-1][1] - window[0][1], window[-1][2] - window[0][2])
            if moved < self.STILL_UNITS:
                return self._trip(now, "covered %.0f units and got %.0f in %.0f s"
                                  % (covered, moved, self.STILL_SECONDS))
        if all_blocked:
            self.blocked_since = self.blocked_since or now
            if now - self.blocked_since > self.BLOCKED_SECONDS:
                expire_barriers()
                self.blocked_since = None
                return self._trip(now, "every direction blocked for %.0f s" % self.BLOCKED_SECONDS)
        else:
            self.blocked_since = None
        return False

    def trip(self, now, reason):
        """Trip from outside: the executor can see reasons the track cannot."""
        return self._trip(now, reason)

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
        self._trail = []        # (game time, x, y) for about a second, to notice rubbing
        self._rub_since = None
        self._rub_said = 0.0

    # ---------------------------------------------------------------- uplink
    # A tic counter that has gone backwards by more than this did not arrive out of order; it restarted.
    RESYNC_TICS = 200            # about six seconds

    def set_intent(self, intent, now=None):
        if self.intent is not None and intent.based_on_tic < self.applied_tic:
            if self.applied_tic - intent.based_on_tic < self.RESYNC_TICS:
                self.stats["stale_dropped"] += 1
                return False
            # The payload restarts its tic counter at every episode, so after a death or the level budget
            # firing, every intent the ground sends looks older than the last one applied and is thrown
            # away -- for the rest of the run. One flight dropped 222 of 423 and stood still in _safe for
            # a third of its ticks, with the ground commanding normally the whole time and nothing in any
            # log to say the orders were being binned.
            self.stats["resyncs"] = self.stats.get("resyncs", 0) + 1
            print("[executor] tic counter restarted (%d -> %d): resyncing to the ground"
                  % (self.applied_tic, intent.based_on_tic), flush=True)
            self.applied_tic = -1
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
            self._trail = []
            return self._look(obs)
        before = sum(self.watchdog.trips.values())
        tripped = self.watchdog.step(now, x, y, obs.get("all_blocked", False), obs["expire_barriers"])
        if sum(self.watchdog.trips.values()) > before:
            # Only a genuine trip, not the ticks of recovery that follow it. step() returns True for the
            # whole recovery, so logging on `tripped` filled the record with the aftermath -- and since
            # recovery clears the plan, every entry said "no plan" and pointed at itself.
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
            # Printed as well as recorded. The flight stack does not downlink the trip count, let alone
            # the context, so on a flight this log line is the only evidence of why the player stopped --
            # and forty freezes in one 190 s flight is most of the flight.
            c = self.watchdog.trip_log[-1]
            print("[executor] freeze: %s/%s ahead=%s@%.0f fwd=%.0f back=%.0f fl=%.0f fr=%.0f "
                  "plan=%s left=%d enemies=%d" %
                  (c["mode"], c["stance"], c["ahead"], c["ahead_dist"], c["clear_fwd"], c["clear_back"],
                   c["clear_fl"], c["clear_fr"], c["has_plan"], c["plan_left"], c["enemies"]), flush=True)
        if tripped or self.watchdog.recovering(now):
            # Which way to turn while recovering. `recover_dir` was set to 1 in the constructor and never
            # assigned again, so every recovery in this project's history has turned left at the full
            # rate for a second and a half -- 787 degrees, two spins, with the heading afterwards decided
            # by arithmetic rather than by anything the player could see. Toward the shoulder the camera
            # says is open is at least a reason.
            if tripped:
                self.recover_dir = self._freer_side(obs)
            self.stats["recover_ticks"] += 1
            self._trail = []
            return self._recover(obs)
        it = self.intent
        if it is None or it.expired(now):
            self.stats["safe_ticks"] += 1
            return self._safe(obs)

        self._trail.append((now, x, y))
        while len(self._trail) > 2 and now - self._trail[0][0] > 1.0:
            self._trail.pop(0)
        rub = self._rubbing(now, x, y)
        if rub and now - self._rub_since >= RUB_STUCK_S:
            self.stats["recover_ticks"] += 1
            self._trail, self._rub_since = [], None
            self.watchdog.trip(now, "asked to move and did not for %.1f s" % RUB_STUCK_S)
            return self._recover(obs)

        want = None
        if it.mode in ("FIGHT", "RETREAT") and obs["enemies"]:
            # Face the threat in both. A Doom player withdrawing walks backwards with the shotgun still
            # pointed at what is chasing it; turning your back and running is how you arrive somewhere
            # else with no health left. Measured: one withdrawal across a courtyard cost 51 health down
            # to 13, every point of it taken from behind, and the retreat-returns-fire fix could not
            # help because nothing was ever in the crosshair.
            want = angle + obs["enemies"][0][1]
        elif (it.use_at_target and it.has_target
              and math.hypot(it.target_x - x, it.target_y - y) <= USE_UNITS):
            # Close enough to open it: face it. Use works along the way the player is looking, so being
            # beside a door is worth nothing. Both of the deepest flights on this level ended at the same
            # corner, fifty units from a real door, wedged against the wall east of it and pressing Use
            # into stone -- 143 times in one of them. The plan had delivered the player to the door and
            # the heading was still whatever the last leg of the walk had left it as.
            want = math.degrees(math.atan2(it.target_y - y, it.target_x - x))
        else:
            plan = self.world.plan
            if plan is not None and not plan.blocked:
                pt = plan.advance(x, y)
                # Throwing the plan away when the next waypoint is behind something was tried here and
                # measured worse, twice. The idea was right -- a player that has come off its path is
                # steering at a point it cannot reach -- but the payload only replans when the next
                # INTENT arrives, about every seventeen tics, so blanking the plan on a rub left the
                # executor with a target and no path for most of the attempt. Freedoom E1M1 on the oracle
                # rung: 62% then 65% of ticks with no plan, best progress 0.04 and 0.18, against 0.45
                # without it. The replan has to be cheap and immediate before this can pay, and it is
                # neither today.
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
            # Holding position still leans on a door if one is in front of us: Doom opens a door on the
            # Use edge, and leaning into it is both what a player does and the only way the payload finds
            # out the thing is not a door.
            if obs["ahead_kind"] in ("door", "exit") and obs["ahead_dist"] > 32:
                cmd["move"] = RUN_DELTA * 0.35
        elif it.stance == "retreat":
            # Backwards, facing the threat, still shooting. `move` is negative and the heading is the
            # enemy's, so this withdraws from it rather than toward it.
            cmd["move"] = -RUN_DELTA if obs["clear_back"] > 64 else 0.0
            cmd["strafe"] = STRAFE_DELTA * self._freer_side(obs)
        else:
            speed = 0.0
            if abs(rel) <= ALIGN_WALK:
                speed = self._throttle(rel, obs)
                if abs(rel) > 20.0:
                    # Lead with the shoulder. Doom strafes and turns at once, and a player closing an
                    # angle does not pivot on the spot and then set off -- they run and slide into it, so
                    # the velocity vector points at the target long before the crosshair does.
                    cmd["strafe"] = STRAFE_DELTA * (1.0 if rel > 0 else -1.0)
            # The guard scales with how fast we are actually going, so it is the same amount of warning
            # at a run as it was at a walk.
            guard = max(AVOID_MIN_UNITS, speed * UNITS_PER_S_PER_DELTA * AVOID_SECONDS)
            if obs["clear_fwd"] <= guard and obs["ahead_kind"] not in ("door", "exit"):
                # Something solid ahead: keep the heading and step around it. It used to slow down as
                # well, and that was most of being stuck -- 52 of 83 rub ticks in a dev run were the
                # guard's 15% crawl. This engine gives the player no momentum, so grinding into a wall
                # costs nothing and crawling at a seventh of a run costs the whole afternoon. How fast
                # it is safe to go while still turning is the throttle's question, and it is answered
                # above from the room the camera reports.
                cmd["strafe"] = STRAFE_DELTA * self._freer_side(obs)
            if rub and now - self._rub_said > 2.0:
                # Once every two seconds, not every tic: enough to see where the player is losing its
                # afternoon without drowning the log.
                self._rub_said = now
                print("[executor] rubbing at (%.0f,%.0f) %s/%s rel=%.0f speed=%.0f ahead=%s@%.0f "
                      "fwd=%.0f fl=%.0f fr=%.0f enemies=%d plan_left=%d"
                      % (x, y, it.mode, it.stance, rel, speed, obs["ahead_kind"], obs["ahead_dist"],
                         obs["clear_fwd"], obs["clear_fl"], obs["clear_fr"], len(obs["enemies"]),
                         (len(self.world.plan.cells) - self.world.plan.i)
                         if self.world.plan else -1), flush=True)
            if rub:
                # Override the guard rather than obey it: the guard is what put us here.
                #
                # Toward the side the camera says is open, and alternate only when it cannot tell. The
                # side used to be chosen by a clock alone, which meant that half the time the player
                # leaned into the wall it was already pressed against: the ladder log is full of
                # `fl=7 fr=428` with the lean going left. `_freer_side` is a measurement and was sitting
                # right there, used by the avoidance guard two lines up.
                # Start with the side the camera says is open, and still alternate. Leaning only to the
                # freer shoulder sounds better and is worse: when the way out is behind, the freer
                # shoulder is wrong and the player leans that way for as long as it is stuck. Alternating
                # blindly at least tries both. This does both -- the first try is the measured one.
                side = self._freer_side(obs) * (
                    1.0 if int((now - self._rub_since) / RUB_FLIP_S) % 2 == 0 else -1.0)
                cmd["strafe"] = STRAFE_DELTA * side
                cmd["turn"] = max(-TURN_PER_TIC, min(TURN_PER_TIC, rel + RUB_TURN_DEG * side))
                speed = RUN_DELTA
                self.stats["rub_ticks"] = self.stats.get("rub_ticks", 0) + 1
            cmd["move"] = speed
            if it.stance == "advance_strafing" and obs["enemies"]:
                cmd["strafe"] = STRAFE_DELTA * self._circle_side(now)
                # Do not close on something that is already shooting at us -- charging at a run was worth
                # four times the deaths on the first executor baseline -- but do not stop either. Clamping
                # the throttle to zero left the player circling one monster at a fixed radius for as long
                # as the intent held: measured, `advance_strafing` with anything inside FIGHT_KEEP_UNITS
                # commanded no forward movement on 60 tics out of 60, indefinitely. That is neither
                # fighting nor going anywhere, and the brief's words for it are "never stand still under
                # fire". Backing off is what a player does: it opens the range, it keeps the shotgun
                # pointed, and it ends.
                if obs["enemies"][0][2] < FIGHT_KEEP_UNITS:
                    cmd["move"] = -RUN_DELTA if obs["clear_back"] > 64 else 0.0

        # Where the time actually goes, at control rate.
        self.stats["move_ticks"] = self.stats.get("move_ticks", 0) + (1 if cmd["move"] else 0)
        self.stats["full_speed_ticks"] = self.stats.get("full_speed_ticks", 0) + (
            1 if abs(cmd["move"]) >= RUN_DELTA else 0)
        self.stats["turn_ticks"] = self.stats.get("turn_ticks", 0) + (1 if abs(cmd["turn"]) > 1 else 0)
        cmd["fire"] = int(self._should_fire(it, obs))
        cmd["use"] = int(self._should_use(it, obs, x, y))
        return cmd

    def _throttle(self, rel, obs):
        """How fast the player may run while it is still turning, given the room it has to turn in.

        This replaces a step function -- full speed inside 45 degrees, six tenths outside it -- that had
        no idea how wide the corridor was. Running at 45 degrees off the aim point is fine in a hall and
        puts the player into the wall in a doorway, and the step function said the same thing in both.
        ALIGN_FULL was tried at 70 and was worse, and at 45 it still left the oracle rung -- the whole
        level and the exit in hand -- at 46 units a second with 45% of its ticks pressed against geometry.
        A better constant was never going to fix it, because the missing term is not a constant.

        The relation is arithmetic, and every term in it is either measured or an engine fact. Turning at
        TURN_PER_TIC, closing a heading error of `rel` takes |rel|/TURN_PER_TIC tics. During those tics
        the heading error falls roughly linearly, so the sideways drift is about half what it would be at
        the full angle:

            drift = speed_per_tic * tics_to_align * sin(|rel|) / 2

        and the room to drift into is what the range camera reports on the side the player is swinging
        toward, less its own radius. Solve for speed, cap at a run.

        No new tunable: TURN_PER_TIC and the delta-to-speed conversion were already here, the radius is
        the engine's, and the clearance is a measurement.
        """
        rel = abs(rel)
        if rel < 1.0:
            return RUN_DELTA
        tics = rel / TURN_PER_TIC
        # The narrower SHOULDER, and not the forward band. The question this answers is how far the
        # body will drift sideways while the heading comes round, so the room that matters is sideways
        # room. Including `clear_fwd` made it a handbrake: a wall seven units ahead is a wall the player
        # slides along for free in this engine, and folding it in here took the throttle to zero for any
        # heading error over a degree -- so the player stopped dead exactly where it most needed to be
        # moving. What to do about something straight ahead is the avoidance guard's job, below.
        room = min(obs["clear_fl"], obs["clear_fr"])
        room -= PLAYER_RADIUS
        if room <= 0.0:
            # Already touching. There is no drift left to prevent, and this engine charges nothing for a
            # scrape and a whole tic for a stop. Measured: the throttle at zero was about 22% of all
            # ticks outside recovery and looking.
            return RUN_DELTA
        drift_per_delta = (UNITS_PER_S_PER_DELTA / TICRATE) * tics * math.sin(math.radians(rel)) / 2.0
        if drift_per_delta <= 1e-6:
            return RUN_DELTA
        return min(RUN_DELTA, room / drift_per_delta)

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
        """Turn on the spot, seeing -- and try the walls while turning.

        Doom's exit is a switch on a one-sided wall, and ZDoom's automap draws one-sided lines as plain
        wall before it ever checks whether the line is an exit. Probed at sixty-eight units from E1M1's
        exit switch, looking all around, with am_interlevelcolor set and am_showtriggerlines both off and
        on: 458 wall pixels, 106 door pixels, and zero exit pixels. The pilot has been searching for
        something it cannot perceive, and no amount of looking will change that.

        What a player does instead is press Use on the wall. Pressing while turning sweeps the whole
        circle at arm's length, so a switch anywhere around a place the player has stopped gets tried.
        It uses nothing the player does not have: a wall in front of it, and a button.
        """
        self.stats["look_ticks"] = self.stats.get("look_ticks", 0) + 1
        self.use_phase = (self.use_phase + 1) % 8
        return {"turn": TURN_PER_TIC, "move": 0.0, "strafe": 0.0, "fire": 0,
                "use": int(self.use_phase == 1), "weapon": WEAPON_KEEP}

    def _rubbing(self, now, x, y):
        """Asking to move, and not moving. Measured over RUB_SECONDS so a doorway pause is not a rub."""
        old = None
        for t, px, py in self._trail:
            if now - t >= RUB_SECONDS:
                old = (px, py)
        if old is None or math.hypot(x - old[0], y - old[1]) >= RUB_UNITS:
            self._rub_since = None
            return False
        if self._rub_since is None:
            self._rub_since = now
        return True

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
        # A door at arm's length gets pressed, whatever the intent says. The best flight so far ended
        # seven units from the door above the exit room, in EXPLORE with no candidates left, and never
        # pressed Use once -- the press was gated on the ground having named a door to operate, and the
        # ground had named nothing. Nobody walks up to a door, stands on it, and walks away because
        # opening it was not the plan. The evidence is the payload's own arm's-length probe; there is no
        # knowledge here the player does not have.
        if not (usable or (it.use_at_target and near_target)):
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
        """Go back the way you came in, because that way is known to work.

        The old recovery turned at the full rate and pushed, which over a second and a half is 787 degrees
        of spin and leaves the heading to arithmetic. It was 28% of an oracle attempt and it is not how
        anyone gets out of a corner.

        `stood` is every cell the player has occupied this attempt -- walkable by demonstration, which is
        the strongest evidence in the world model. Steer at the nearest one that is a watchdog window
        behind, and run at it. If there is none yet, fall back to the old back-off-and-turn, which is all
        a player has in its first seconds on a level.

        Still always commands motion: the payload's stuck detector needs the player to push against
        something to learn it is there, and a recovery that stands still deadlocks it.
        """
        self.world.clear_plan()
        x, y, angle = obs["x"], obs["y"], obs["angle"]
        # getattr, because the unit suite drives the executor with a stand-in world that has no map --
        # and the point of that stand-in is that the executor can be tested without one.
        way_back = getattr(self.world, "way_back", None)
        back_to = way_back(x, y, Watchdog.STILL_UNITS) if way_back else None
        if back_to is not None:
            want = math.degrees(math.atan2(back_to[1] - y, back_to[0] - x))
            rel = (want - angle + 180) % 360 - 180
            self.stats["recover_retreats"] = self.stats.get("recover_retreats", 0) + 1
            return {"turn": max(-TURN_PER_TIC, min(TURN_PER_TIC, rel)),
                    # Backwards while the heading comes round, forwards once it has: either way the
                    # player is moving toward ground it has already stood on.
                    "move": RUN_DELTA if abs(rel) < 90.0 else -RUN_DELTA * 0.7,
                    "strafe": STRAFE_DELTA * self._freer_side(obs),
                    "fire": 0, "use": 1 if obs["ahead_kind"] in ("door", "exit") else 0,
                    "weapon": WEAPON_KEEP}
        back = obs["clear_back"] > 64
        return {"turn": TURN_PER_TIC * self.recover_dir,
                "move": -RUN_DELTA * 0.7 if back else RUN_DELTA * 0.5,
                "strafe": STRAFE_DELTA * self._freer_side(obs),
                "fire": 0, "use": 1 if obs["ahead_kind"] in ("door", "exit") else 0,
                "weapon": WEAPON_KEEP}
