"""The world model for one level attempt: frontiers, an object table, and a path planner that commits.

Charter 3.2. This lives onboard, beside the map the payload already builds, and it is thrown away at every
level start along with everything else (charter 2.2). It knows nothing that was not sensed this attempt.

It exists because of one number. Graded against the charter's ruler, the best flight run of 22 September
had a `revisit_fraction` of 0.80: four fifths of its decisions were taken on ground it had walked over
twenty seconds earlier, 75,000 units of walking to stand in 57 distinct cells. The pilot was neither stuck
nor slow. It kept arriving where it had already been, because eight local sectors cannot express "go to
that door six hundred units away" -- the best they can say is "it is a bit more open to the left".

Three parts, in the order they depend on each other:

  passable()   which 32-unit cells a player could stand in, from the automap raster and the barriers the
               payload learned by bumping into things
  frontiers()  the boundary between swept floor and the unknown, clustered into places worth going
  plan()       A* over walkable cells, with commitment

The HANDOFF removed the first planner because it "flipped between equal-cost routes every replan". That is
the same problem world-frame direction memory already solved for sectors: the answer is to hold a choice
until something better by a margin comes along, not to stop choosing. `Plan.better_than` is that margin.
"""
import heapq
import math
from collections import deque

from mapclasses import (BLOCKING, DOOR, EXIT, GRID, LOCK_KEY, LOCKED, STEP, WPX,  # noqa: F401
                        ENEMY_INDEX, NO_ENEMY)

THREAT_NEAR = 384.0        # an enemy this close to a candidate is a reason to think twice about going there
# What a ceiling change has to look like before it is allowed to be called a door. Doom doorways are a
# little over a cell wide; a ceiling change that runs for hundreds of units is a ledge or a light recess.
DOOR_MIN_WIDTH, DOOR_MAX_WIDTH = 40.0, 200.0
DOOR_CONFIRM_UNITS = 400.0   # close enough for the range camera to have an opinion
SEE_PAST_UNITS = 96.0        # seeing this much further than the suspect means it is not solid
# One, not two. Doors are `must` candidates -- always in the list of eight, never pruned -- and the
# rubric's top level is "the way on: an untried door", so every door in the list outranks the frontier
# that leads onward. At the closest approach of three separate attempts the right way on was offered
# every time, with the lowest true distance to the exit of anything in the list, and every time two doors
# behind the player sat alongside it and won. Two of eight slots is a quarter of the list spent on the
# way the player came in.
# Two, now that a door competes on what is behind it rather than sitting in a reserved slot at the top of
# the rubric. The cap exists so that a room with four doorways cannot fill a list of eight; it is not a
# statement about how important doors are, which is the model's question.
MAX_DOOR_CANDIDATES = 2
# Clearance is a preference, not a permission. The player has a 16-unit radius, so 4 raster pixels is
# +-16 and exactly no margin: a cell whose centre sits sixteen units from a wall counts as walkable and
# the player arrives already touching it, which is what the rub log shows -- clear_fwd 14, one shoulder
# at 7. Raising the requirement to 5 fixed that and broke something far worse: in a corridor narrow
# enough that every neighbouring cell failed the test, the flood could not leave the player's own cell
# and the candidate list came back empty. Seventy per cent of the decisions in two flights had nowhere
# to go at all, against 19% in the one flight that got closest to the exit, and every one of those
# reported no route to any goal with five hundred walkable cells on the map.
#
# So: 4 decides whether a cell can be used, 5 decides whether the planner likes it. A tight cell costs
# extra to cross, which puts the route down the middle of a corridor without ever refusing the corridor.
PLAYER_CLEARANCE_PX = 4      # a cell narrower than this is not walkable at all
PLAYER_ROOMY_PX = 5          # a cell narrower than this is walkable, and avoided if there is a choice
# A ledge is not a wall and it is not floor. Doom lets the player climb 24 units and no more, and the
# automap draws every floor-height change in one colour, so the payload cannot tell a stair from a drop --
# but STEP is not in BLOCKING, so the planner has been routing straight across ledges the player cannot
# cross. Five seeds all stopped within the same five hundred units of E1M1, at a ledge with exactly one
# passable gap in it, and none of them found the gap. Costly, not forbidden: stairs still get climbed
# when they are the way through, and a route with a gap in it wins over a route with a ledge in it.
# Measured at 6.0 and it did not pay: mean closest approach across five seeds went from 0.42 of the way
# to 0.37, with three deaths instead of two. The automap draws every floor-height change in one colour,
# including every stair tread, so charging for all of them charges for almost every cell and the penalty
# becomes a constant. The ledge is handled where it belongs instead -- in the sweep, by not believing the
# camera about floor it can see over.
STEP_COST = 0.0              # extra steps crossing a floor-height change costs, in cells
TIGHT_COST = 4.0             # extra steps a tight cell costs, in cells. 1.6 was worth 51 units of
                             # detour, which is not enough to prefer the middle of a room to the wall
                             # of it: scraping went back from 13% of ticks to 30% as soon as tight cells
                             # became usable again. Four cells is 128 units of detour -- a corridor is
                             # still taken when it is the only way through, and never when it is not.
ARRIVED_UNITS = 96.0        # close enough that the arm's-length probe has the final word. 96 was
                             # the probe's own reach. A suspect inside a wall is settled by having
                             # no route to it, which is a stronger test than standing near it.

FRONTIER_MIN_CELLS = 2     # a frontier smaller than this is sensor noise, not a way on
MIN_UNSEEN_CELLS = 6       # unknown ground behind an opening, below which it is a pinhole in the sweep
UNSEEN_FLOOD_LIMIT = 400   # stop counting the unknown beyond an opening at this many cells
FRONTIER_MAX = 24          # clusters to consider before pruning to the candidates the ground scores
REPLAN_MARGIN = 0.80       # a new path must be this much shorter than the one being walked to replace it
REPLAN_EVERY_S = 1.0       # never replan faster than this, whatever happens
PATH_MAX_CELLS = 4000      # A* gives up rather than stall the control loop
LOOKAHEAD_CELLS = 4        # waypoints ahead to steer at: about 128 units
ARRIVE_UNITS = 24.0        # close enough to a waypoint to take the next one, and under one cell: at 48
                           # the cursor cleared two waypoints at once and the walk cut every corner
TARGET_UNITS = 64.0        # close enough to the target to call it reached
OUTWARD_UNITS = 128.0      # further from the spawn than here by this much counts as further out

# Where the candidate list's own time goes, accumulated in seconds and reported per attempt. The tic
# budget is 28.6 ms and this runs once in seven of them, so "candidates are expensive" is not a finding --
# which part of them is, is.
COST = {}


def _cost(name, t0):
    import time as _t
    COST[name] = COST.get(name, 0.0) + (_t.perf_counter() - t0)


KIND_FRONTIER, KIND_DOOR, KIND_EXIT, KIND_KEY, KIND_ITEM, KIND_SWITCH, KIND_ENEMY = range(7)
KIND_NAME = {KIND_FRONTIER: "frontier", KIND_DOOR: "door", KIND_EXIT: "exit", KIND_KEY: "key",
             KIND_ITEM: "item", KIND_SWITCH: "switch", KIND_ENEMY: "enemy"}


class Candidate:
    """Somewhere worth going, with the few features a decision about it needs.

    `path_units` is the distance along walkable floor, not the straight line: a frontier 200 units away
    through a wall is not 200 units away, and scoring it as though it were is how a pilot ends up walking
    into the same corner all afternoon.
    """

    __slots__ = ("kind", "x", "y", "path_units", "novelty", "colour", "tries", "cell", "note",
                 "threat_class", "threat_count", "opening", "depth", "away")

    def __init__(self, kind, x, y, path_units, novelty=0, colour="", tries=0, cell=None, note="",
                 threat_class=NO_ENEMY, threat_count=0, opening=0, depth=0, away=True):
        self.kind, self.x, self.y = kind, float(x), float(y)
        self.path_units, self.novelty = float(path_units), int(novelty)
        self.colour, self.tries = colour, int(tries)
        self.cell, self.note = cell, note
        # What is standing near it, as a fact: which class, and how many. Whether that is worth facing is
        # a judgement, and it is made on the ground with the knowledge file in hand.
        self.threat_class, self.threat_count = int(threat_class), int(threat_count)
        # What the opening looks like: how wide it is, how far the unknown runs past it, and whether it
        # leads away from the ground already walked. A corridor mouth and the corner of this room are
        # the same distance away and nothing else about them is alike.
        self.opening, self.depth, self.away = int(opening), int(depth), bool(away)

    def as_dict(self, px, py, heading):
        bearing = (math.degrees(math.atan2(self.y - py, self.x - px)) - heading + 180) % 360 - 180
        return {"kind": KIND_NAME[self.kind], "x": self.x, "y": self.y, "bearing": bearing,
                "path_units": self.path_units, "novelty": self.novelty, "colour": self.colour,
                "threat_class": self.threat_class, "threat_count": self.threat_count,
                "opening": self.opening, "depth": self.depth, "away": self.away,
                "tries": self.tries, "note": self.note}

    def __repr__(self):
        return "<%s at (%.0f,%.0f) %.0fu>" % (KIND_NAME[self.kind], self.x, self.y, self.path_units)


class Plan:
    """A path, and the discipline about when to throw it away."""

    def __init__(self, cells, target, made_at):
        self.cells = cells                  # list of (cx, cy), start first
        self.target = target                # the Candidate it was planned to
        self.made_at = made_at
        self.i = 0                          # how far along it the player is
        self.blocked = False
        self.reacquired = 0                 # times the cursor was moved to a waypoint reachable from here

    @property
    def remaining_units(self):
        return max(0, len(self.cells) - self.i - 1) * GRID

    def straight_line_clear(self, x0, y0, x1, y1):
        """Can the player walk the straight line from here to there without touching anything?

        Set by the world model when it builds a plan. Without it the aim point is chosen by whether the
        chord stays near the PATH, which is a different question: a chord 38 units off the path still puts
        a 16-unit-wide player 54 units off the corridor centre, and into the wall. The t3 baseline spent
        34% of its ticks pressed against geometry with a plan in hand, and the oracle rung -- which has
        the whole level -- spent 46%.
        """
        return True

    def advance(self, x, y):
        """Step the cursor past every waypoint already reached. Returns the point to steer at, or None."""
        while self.i < len(self.cells) - 1:
            here = math.hypot(*[a - b for a, b in zip(cell_centre(self.cells[self.i]), (x, y))])
            nxt = math.hypot(*[a - b for a, b in zip(cell_centre(self.cells[self.i + 1]), (x, y))])
            # reached it, or already past it: a player that overshoots must not be steered backwards
            if here <= ARRIVE_UNITS or nxt < here:
                self.i += 1
            else:
                break
        if self.i >= len(self.cells):
            return None
        self._reacquire(x, y)
        # Steer ahead, but only as far as the path is straight. A cell is 32 units and the player covers
        # 14.5 of them a tic, so aiming at the next cell changes the heading every two tics, the bearing
        # jitters on a diagonal, and the executor is almost never inside its alignment window -- which is
        # why it crossed the level at a sixth of its running speed. Aiming a fixed distance ahead fixes
        # that and introduces a worse bug: on a bend the aim point is through the wall, the player pushes
        # into it, and the watchdog calls it a freeze. Thirty-six of them in two dev episodes.
        #
        # So: take the furthest waypoint whose straight line from here does not leave the path's own
        # corridor. On a straight run that is the full lookahead; into a corner it shrinks to the next
        # cell by itself.
        return cell_centre(self.cells[self._aim_index(x, y)])

    def _reacquire(self, x, y, span=LOOKAHEAD_CELLS * 2):
        """If the cursor points somewhere the player cannot walk to, move it to the nearest one it can.

        A path the player has come off is still a good path. `advance` moves the cursor on when the player
        reaches a waypoint or passes it, and a player pushed sideways does neither -- so it goes on
        steering at a waypoint behind a wall, with the avoidance guard holding it at 15% of a run against
        the wall, for as long as the rub correction keeps pushing it sideways. That was the commonest
        single line in a dev run's rub log.

        Forward first, because going on is the point and going back is what the recovery is for.
        """
        here = cell_centre(self.cells[self.i])
        if self.straight_line_clear(x, y, here[0], here[1]):
            return
        for j in list(range(self.i + 1, min(len(self.cells), self.i + span + 1))) + \
                list(range(self.i - 1, max(-1, self.i - span - 1), -1)):
            cx, cy = cell_centre(self.cells[j])
            if self.straight_line_clear(x, y, cx, cy):
                self.reacquired += 1
                self.i = j
                return

    def _aim_index(self, x, y):
        best = min(len(self.cells) - 1, self.i + 1)
        for j in range(best, min(len(self.cells), self.i + LOOKAHEAD_CELLS + 1)):
            tx, ty = cell_centre(self.cells[j])
            if self._chord_clear(x, y, j) and self.straight_line_clear(x, y, tx, ty):
                best = j
            else:
                break
        return best

    def _chord_clear(self, x, y, j, slack=GRID * 1.2):
        """Does the straight line from here to waypoint j stay beside the path it is shortcutting?"""
        tx, ty = cell_centre(self.cells[j])
        dx, dy = tx - x, ty - y
        span = math.hypot(dx, dy)
        if span < 1e-6:
            return True
        for k in range(self.i, j + 1):
            px, py = cell_centre(self.cells[k])
            # perpendicular distance from the path point to the chord
            off = abs(dx * (py - y) - dy * (px - x)) / span
            if off > slack:
                return False
        return True

    def better_than(self, other):
        if other is None or other.blocked or not other.cells:
            return True
        return len(self.cells) < REPLAN_MARGIN * len(other.cells)


def cell_centre(c):
    return (c[0] + 0.5) * GRID, (c[1] + 0.5) * GRID


class WorldModel:
    """Everything this attempt has learned about where it can go and what is there.

    It borrows the payload's Explorer rather than keeping a second copy: the raster, the swept floor and
    the barrier marks are already the record of what has been sensed, and a second copy would be a second
    thing to wipe at level start.
    """

    def __init__(self, explorer, enemies=(), item_kind=None):
        self.ex = explorer
        # Passed in rather than imported so this module loads without ViZDoom and so the unit suite can
        # reach it; the payload hands it its own tables, and a test pins the two together.
        self.enemy_names = set(enemies)
        self.item_kind = dict(item_kind or {})
        self.objects = {}            # (kind, rx, ry) -> {kind, name, x, y, first_seen_tic, last_seen_tic, state}
        self.doors = {}              # (cx, cy) -> {"x","y","colour","tries","opened","last_try"}
        self.switches = {}           # (cx, cy) -> {"x","y","pressed"}
        self._features = {}          # cell -> what makes this opening worth judging
        self.plan = None
        self.last_plan_t = 0.0
        self.last_frontier_t = -1e9      # not 0.0: that makes the very first call hit the cache and
                                         # return nothing, so the first candidate list of every level
                                         # would be empty
        self._frontiers = []
        self.dead_frontiers = set()   # openings the player stood on that stayed openings
        self.start = None             # where this attempt began; the fixed point "outward" is measured from
        # How many separate times the player has set off for a place. `tried_before` is one of the nine
        # things a target decision rests on and it has been the word "no" on every candidate of every
        # flight, because frontier tries were hardcoded to zero -- so the one signal that says "you have
        # already been there" was missing from the only head that could have used it.
        self.targeted = {}
        self.empty_reason = None
        self.stood = set()           # every cell the player has occupied: passable by demonstration
        self.planner_calls = 0
        self.planner_failures = 0
        self._walk_key, self._walk = None, set()
        self._known_key, self._known = None, set()

    # ------------------------------------------------------------------ the floor
    def passable(self, cx, cy, now):
        """Could a player stand in this 32-unit cell?

        Known-free floor that the automap does not show a wall or a remembered barrier in. A door counts
        as passable -- it opens -- unless it is locked and the key is not held, which `Explorer.klass`
        already distinguishes by colour.
        """
        if (cx, cy) in self.stood:
            # Standing somewhere is proof it can be stood in, and it outranks every inference. Without
            # this the player seals itself in: it marks a step barrier in front of its feet, the barrier
            # covers the ground it is on, the flood cannot leave its own cell, and the candidate list
            # comes back empty with eight hundred walkable cells on the map -- which is what the log said
            # at (1328,-3190), over and over, at the exact place the step detector fires.
            return True
        if (cx, cy) not in self.ex.free:
            return False
        ix, iy = self.ex.wpx((cx + 0.5) * GRID, (cy + 0.5) * GRID)
        # r=5 is +-20 raster units, and the player is a cylinder of radius 16. At r=3 the test only
        # cleared +-12, so a cell whose centre sat fourteen units from a wall counted as walkable, the
        # planner ran paths that hugged the geometry, and the player ground along them until the freeze
        # watchdog pulled it out -- eight of thirteen trips in a dev attempt had a perfectly good plan
        # and a wall at arm's length. The grader learned the same lesson about its own grid; this is it
        # applied to the map the pilot actually steers by.
        c = self.ex.klass(ix, iy, now, r=PLAYER_CLEARANCE_PX)
        if c in BLOCKING:
            return False
        if c in LOCK_KEY and LOCK_KEY[c] not in self.ex.keys:
            return False
        return True

    def note_here(self, x, y):
        """The player is here, so here can be stood in. Called every tic: at two hundred units a second
        the decision rate would leave two-cell gaps in the trail, and a gap is where it gets walled in.

        Settling a door by standing in it was tried here and measured worse -- mean closest approach
        across five seeds fell from 0.42 of the way to the exit to 0.29, and door recall from all ten to
        six of eight. Too many of the suspects the payload raises are ceiling-height lines the player
        walks over constantly, so "I have been inside it" retires real doors along with the phantoms.
        """
        self.stood.add(self.ex.cell(x, y))

    def tight(self, cx, cy, now):
        """Walkable, but with the walls close enough that the player will scrape them."""
        ix, iy = self.ex.wpx((cx + 0.5) * GRID, (cy + 0.5) * GRID)
        return self.ex.klass(ix, iy, now, r=PLAYER_ROOMY_PX) in BLOCKING

    def crossing_costs(self, walk, now):
        """What each cell costs beyond its distance: a squeeze, a ledge, or both."""
        out = {}
        if getattr(self.ex, "geom", None) is not None:
            # Restored, and I was wrong to take it out in the step 2 commit. The argument was that
            # TIGHT_COST compensated for the automap drawing a wall as a fuzzy stroke, so exact lines made
            # it redundant. It does not: the clearance test asks whether a player can STAND in a cell, and
            # a 16-unit cylinder moving 14.5 units a tic while turning needs room to MOVE through it. With
            # the bribe gone the planner ran routes flush against exact walls, and the oracle rung -- the
            # whole level and the exit handed over -- spent 46% of its ticks pressed against geometry with
            # a perfect map in hand.
            free_of = getattr(self.ex, "cell_is_free", None)
            if free_of is None:
                return out
            for c in walk:
                if free_of(c[0], c[1], now, PLAYER_ROOMY_PX) is False:
                    out[c] = TIGHT_COST
            return out
        near = getattr(self.ex, "near_class", None)
        for c in walk:
            extra = TIGHT_COST if self.tight(c[0], c[1], now) else 0.0
            if near is not None:
                ix, iy = self.ex.wpx((c[0] + 0.5) * GRID, (c[1] + 0.5) * GRID)
                if near(ix, iy, STEP, 1):
                    extra += STEP_COST
            if extra:
                out[c] = extra
        return out

    def walkable(self, now):
        """Every cell a player could stand in, computed once per decision rather than per caller.

        `frontiers`, `path_costs` and `plan_to` each used to build this from scratch, and each build was
        one `klass` call per cell. That cost nothing while the floor came from a 400-unit camera sweep;
        with the visibility fill a look around one hall adds two thousand cells and the three rebuilds
        became 160 ms a decision. The mask does the geometry once for everybody and this caches the
        answer for the tic it was asked on.
        """
        key = round(now, 3)
        if self._walk_key == key:
            return set(self._walk)
        # getattr, not a hard call: the unit suite drives this with a stand-in Explorer that has no
        # raster to filter, and the point of that stand-in is that the world model can be tested without
        # ViZDoom. Falling back to the per-cell test keeps both honest -- same answer, slower.
        free_of = getattr(self.ex, "cell_is_free", None)
        if free_of is None:
            out = {c for c in self.ex.free if self.passable(c[0], c[1], now)} | self.stood
        else:
            out = set(self.stood)
            for c in self.ex.free:
                if c in self.stood or free_of(c[0], c[1], now, PLAYER_CLEARANCE_PX):
                    out.add(c)
        self._walk_key, self._walk = key, out
        return set(out)

    def tight_cells(self, walk, now):
        return {c for c in walk if self.tight(c[0], c[1], now)}

    # ------------------------------------------------------------------ frontiers
    def known(self, now):
        """Every cell this attempt has any evidence about: floor the camera swept, or a line the automap
        drew.

        The distinction matters more than it sounds. The range camera is trusted to about 400 units and
        samples forty columns a tic, so the floor it sweeps is sparse and full of holes -- and a cell
        beside one of those holes looks exactly like a cell beside the edge of the map. That is why every
        frontier came out "right here" and they all looked alike: most of them were pinholes two metres
        away, not ways on. The automap has seen every wall that has been in view, including far ones the
        camera never swept, so using it as well tells the difference between "not looked at" and "not
        there".
        """
        key = round(now, 3)
        if self._known_key == key:
            return set(self._known)
        out = set(self.ex.free)
        ex = self.ex
        import numpy as np
        # Over the window the player has seen, not the whole 3072-square raster: np.nonzero on nine
        # million pixels to find a few thousand is most of a tic, every time a frontier is asked for.
        mask_of = getattr(ex, "blocked_mask", None)
        box = mask_of(now, 1) if mask_of else None
        if box is not None:
            _blk, ix0, iy0 = box
            sub = ex.raster[iy0:iy0 + _blk.shape[0], ix0:ix0 + _blk.shape[1]]
            ys, xs = np.nonzero(sub)
            xs = xs + ix0
            ys = ys + iy0
        else:
            ys, xs = np.nonzero(ex.raster)
        if len(xs):
            step = max(1, len(xs) // 6000)
            for k in range(0, len(xs), step):
                wx = ex.ox + int(xs[k]) * WPX
                wy = ex.oy - int(ys[k]) * WPX
                out.add((int(math.floor(wx / GRID)), int(math.floor(wy / GRID))))
        self._known_key, self._known = key, out
        return set(out)

    def frontiers(self, x, y, now, force=False):
        """Ways on: walkable floor that borders on ground this attempt knows nothing about.

        Yamauchi 1997, with the two corrections the flights asked for. A frontier has to border the
        genuinely unknown rather than an unswept pinhole, and it is weighed by how much is likely to be
        behind it rather than by how near it is -- weighting by expected unseen area is the standard
        improvement on nearest-frontier exploration, and here it is the difference between a corridor
        mouth and the corner of the room you are standing in.
        """
        if not force and now - self.last_frontier_t < 0.5:
            return self._frontiers
        import time as _t
        self.last_frontier_t = now
        t0 = _t.perf_counter(); walk = self.walkable(now); _cost("walkable", t0)
        t0 = _t.perf_counter(); known = self.known(now); _cost("known", t0)
        edge = []
        for (cx, cy) in walk:
            if (cx, cy) in self.dead_frontiers:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if (cx + dx, cy + dy) not in known:
                    edge.append((cx, cy))
                    break
        self._frontiers = []
        t0 = _t.perf_counter()
        clusters = self._cluster(set(edge))
        _cost("cluster", t0)
        t0 = _t.perf_counter()
        for cell, size in clusters:
            unseen, depth = self._beyond(cell, known)
            if unseen < MIN_UNSEEN_CELLS:
                continue          # a pinhole in the sweep, not a way on
            self._frontiers.append((cell, size, unseen, depth))
        _cost("beyond", t0)
        # biggest promise first; the ground still gets to disagree
        self._frontiers.sort(key=lambda f: -(f[2] + f[3]))
        return self._frontiers[:FRONTIER_MAX]

    @staticmethod
    def _cluster(cells):
        """Connected groups of frontier cells, as (centroid cell, size), biggest first."""
        out, seen = [], set()
        for c in cells:
            if c in seen:
                continue
            group, q = [], deque([c])
            seen.add(c)
            while q:
                a = q.popleft()
                group.append(a)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        n = (a[0] + dx, a[1] + dy)
                        if n in cells and n not in seen:
                            seen.add(n)
                            q.append(n)
            if len(group) >= FRONTIER_MIN_CELLS:
                mx = sum(g[0] for g in group) / len(group)
                my = sum(g[1] for g in group) / len(group)
                # the centroid may fall in a gap; snap to the group member nearest it
                best = min(group, key=lambda g: (g[0] - mx) ** 2 + (g[1] - my) ** 2)
                out.append((best, len(group)))
        out.sort(key=lambda g: -g[1])
        return out

    def _beyond(self, cell, known, limit=UNSEEN_FLOOD_LIMIT):
        """How much unknown lies past this opening, and how far it runs.

        Returns (cells of unknown reachable through it, how far the furthest of them is, in cells). A
        corner of a room has a handful; a corridor mouth has hundreds and they run away from you.
        """
        seen, q = {cell}, deque([(cell, 0)])
        unseen, far = 0, 0
        while q and unseen < limit:
            (cx, cy), d = q.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (cx + dx, cy + dy)
                if n in seen:
                    continue
                seen.add(n)
                if n in known:
                    continue
                unseen += 1
                far = max(far, d + 1)
                q.append((n, d + 1))
        return unseen, far

    def frontier_features(self, cell, size, unseen, depth, px, py):
        """What a decision about this opening rests on, as numbers; the ground turns them into words."""
        wx, wy = cell_centre(cell)
        centre = self.explored_centre()
        away = True
        if centre is not None:
            here = math.hypot(px - centre[0], py - centre[1])
            there = math.hypot(wx - centre[0], wy - centre[1])
            away = there >= here - GRID
        return {"opening_units": size * GRID, "unseen_cells": unseen,
                "open_depth_units": depth * GRID, "leads_away": away, "gate": ""}

    def explored_centre(self):
        """Where the level started, which is the one reference point that does not move.

        This used to be the centroid of everywhere the player had walked -- and a centroid follows the
        player, so "does this lead away from explored ground" barely separated anything: jev scored the
        two cases 5.22 and 4.92, a third of a rubric level apart. Measured from the start it means
        something an exploring player can act on, because wherever the way out is, it is not where you
        came in. It uses nothing but the player's own spawn position.
        """
        return self.start

    def note_frontier_reached(self, x, y, now):
        """A frontier the player has stood at and which is still a frontier revealed nothing.

        Standing on an opening and having it stay an opening means the camera could not see through it --
        a fake gap, a grating, a drop. Dropping it for the attempt is the same discipline as settling a
        door suspect by standing at it, and for the same reason: arriving is evidence.
        """
        here = self.ex.cell(x, y)
        dropped = 0
        for (cell, _size, _unseen, _depth) in list(self._frontiers):
            if abs(cell[0] - here[0]) <= 1 and abs(cell[1] - here[1]) <= 1:
                self.dead_frontiers.add(cell)
                dropped += 1
        return dropped

    # ------------------------------------------------------------------ objects, doors, switches
    def see_objects(self, x, y, labels, tic):
        """The object table: everything the labels buffer has named, with when it was first seen."""
        for lab in labels:
            name = lab.object_name
            kind = "enemy" if name in self.enemy_names else self.item_kind.get(name)
            if not kind:
                continue
            key = (kind, round(lab.object_position_x / 32), round(lab.object_position_y / 32))
            rec = self.objects.get(key)
            if rec is None:
                rec = {"kind": kind, "name": name, "first_seen_tic": tic, "state": "alive"}
                self.objects[key] = rec
            rec.update({"x": lab.object_position_x, "y": lab.object_position_y, "last_seen_tic": tic})
        # anything we have walked over is gone
        for key, rec in list(self.objects.items()):
            if rec["kind"] != "enemy" and math.hypot(rec["x"] - x, rec["y"] - y) < 40:
                rec["state"] = "taken"

    def see_doors(self, now, radius_px=220):
        """Places on the automap that MIGHT be a door. Nothing here is a door yet.

        ZDoom's `am_cdwallcolor` is the "ceiling height changes" category, and the payload reads that
        colour as DOOR. It is not: every step up, window frame, light recess and ledge in the level is a
        ceiling change. Across one flight that made 1,336 of 2,899 candidates "a door", and since the
        rubric reasonably prefers a close untried door to a far frontier, the player spent its time
        pressing Use on walls near where it started.

        So a line found here is a *suspect*. It becomes a candidate only once it has passed the tests in
        `confirm_doors` and `note_door_try`: roughly door-width, solid to the range camera, and not yet
        proved inert by pressing it. This is the same lesson as the first audit -- the model answered bad
        inputs correctly, and the fix belongs in the senses.
        """
        import numpy as np
        ex = self.ex
        if getattr(ex, "geom", None) is not None:
            # Exact geometry: a door is a sector whose ceiling is at its own floor, so there are no
            # suspects to sift and none of the machinery below applies. Width, see-through and
            # settle-by-arrival all exist to tell a doorway from a ceiling change, which is a question
            # the colours could not answer and this one never has to ask.
            for (dx, dy, width) in ex.geom.doors():
                cell = (int(math.floor(dx / GRID)), int(math.floor(dy / GRID)))
                rec = self.doors.setdefault(cell, {"x": dx, "y": dy, "colour": "", "tries": 0,
                                                   "opened": False, "last_try": 0.0, "not_a_door": False,
                                                   "see_through": False, "width": width, "why": ""})
                rec["x"], rec["y"], rec["width"] = dx, dy, width
            return
        cx_, cy_ = ex.wpx(*self._last_pos) if getattr(self, "_last_pos", None) else (ex.n // 2, ex.n // 2)
        a, b = max(0, cx_ - radius_px), min(ex.n, cx_ + radius_px)
        c, d = max(0, cy_ - radius_px), min(ex.n, cy_ + radius_px)
        win = ex.raster[c:d, a:b]
        for cls in (DOOR, LOCKED) + tuple(LOCK_KEY):
            ys, xs = np.nonzero(win == cls)
            if not len(xs):
                continue
            # Group the pixels by cell first, so a cluster's extent can be measured. A door is roughly
            # one doorway wide; a ceiling change that runs the length of a wall is a ledge.
            by_cell = {}
            for k in range(0, len(xs), 3):
                wx = ex.ox + (a + int(xs[k])) * WPX
                wy = ex.oy - (c + int(ys[k])) * WPX
                by_cell.setdefault((int(math.floor(wx / GRID)), int(math.floor(wy / GRID))),
                                   []).append((wx, wy))
            for cell, pts in by_cell.items():
                rec = self.doors.get(cell)
                if rec and rec.get("not_a_door"):
                    continue                      # settled, and it stays settled for the attempt
                width = self._extent(pts, by_cell, cell)
                rec = self.doors.setdefault(cell, {"x": pts[0][0], "y": pts[0][1], "colour": "",
                                                   "tries": 0, "opened": False, "last_try": 0.0,
                                                   "not_a_door": False, "see_through": False,
                                                   "width": width, "why": ""})
                rec["width"], rec["colour"] = width, LOCK_KEY.get(cls, "locked" if cls == LOCKED else "")
                if not (DOOR_MIN_WIDTH <= width <= DOOR_MAX_WIDTH):
                    rec["not_a_door"], rec["why"] = True, "%.0f units wide" % width

    @staticmethod
    def _extent(pts, by_cell, cell):
        """How far the ceiling change runs through this cell and its neighbours, in map units."""
        near = list(pts)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                near += by_cell.get((cell[0] + dx, cell[1] + dy), [])
        xs = [p[0] for p in near]
        ys = [p[1] for p in near]
        return max(max(xs) - min(xs), max(ys) - min(ys))

    def confirm_doors(self, x, y, angle, depth_units, now):
        """Ask the range camera whether the suspect is solid.

        A closed door blocks the view. A window, a ledge or a step in the ceiling does not: the camera
        sees past it, to the far wall of whatever is behind. So if the depth at the suspect's bearing
        reads meaningfully further than the suspect itself, it is not a closed door and never was.

        `depth_units` is a function from a relative bearing to how far the camera can see that way.
        """
        for cell, rec in self.doors.items():
            if rec.get("not_a_door") or rec.get("opened") or rec.get("see_through"):
                continue
            dist = math.hypot(rec["x"] - x, rec["y"] - y)
            if dist > DOOR_CONFIRM_UNITS or dist < 24:
                continue
            rel = (math.degrees(math.atan2(rec["y"] - y, rec["x"] - x)) - angle + 180) % 360 - 180
            if abs(rel) > 40:
                continue                          # outside the camera's useful field
            seen = depth_units(rel)
            if seen is not None and seen > dist + SEE_PAST_UNITS:
                rec["see_through"] = True
                rec["why"] = "the camera sees %.0f units past it" % (seen - dist)

    def settle_by_arrival(self, x, y, angle, ahead_kind, ahead_dist):
        """Standing in front of a suspect and seeing no door is evidence, and it is free.

        A suspect was only ever disproved by pressing Use on it -- but the executor only presses when the
        arm's-length probe already says "door", which for a ceiling change it never does. So a false
        suspect could not be disproved: the pilot walked to it, found nothing to press, gave up, and the
        suspect went straight back on the list. Zero Use presses in a whole flight, and six phantom doors
        approached over and over.

        This closes the loop with the evidence the payload already computes. If the player is at arm's
        length, facing it, and what is at arm's length is not a door, then it is not a door.
        """
        if ahead_kind in ("door", "exit", "locked"):
            return 0
        if ahead_kind == "nothing" or not ahead_dist:
            # The arm's-length probe only classifies what is within about 120 units; beyond that it
            # reports nothing, which is an absence of evidence and not evidence of absence. Treating it
            # as proof settled every real door as a not-a-door on approach: door_recall said five of six
            # were offered, and the pilot pressed Use exactly zero times in a whole flight.
            return 0
        settled = 0
        for _cell, rec in self.doors.items():
            if rec.get("not_a_door") or rec.get("opened"):
                continue
            d = math.hypot(rec["x"] - x, rec["y"] - y)
            if d > ARRIVED_UNITS:
                continue
            rel = (math.degrees(math.atan2(rec["y"] - y, rec["x"] - x)) - angle + 180) % 360 - 180
            if abs(rel) > 90:
                continue
            rec["not_a_door"] = True
            rec["why"] = "stood at it facing it; nothing there to open"
            settled += 1
        return settled

    def note_door_try(self, x, y, now, opened=False):
        """A press, and what it proved. One press that opens nothing settles it for the attempt.

        Pressing Use on a wall is the cheapest possible experiment and its result is unambiguous, so it
        is worth more than any amount of inference from the automap.
        """
        best, bd = None, 1e9
        for _c, rec in self.doors.items():
            d = math.hypot(rec["x"] - x, rec["y"] - y)
            if d < bd:
                best, bd = rec, d
        if best is None or bd >= 96:
            return None
        best["last_try"] = now
        if opened:
            best["opened"] = True
            return True
        best["tries"] += 1
        # Three, not one. One press was right while the verdict could never be read: the pending watch was
        # overwritten every eight tics, note_door_try was reached almost never, and a single failure
        # costing a door did not matter because it never happened. With the watch fixed it happens on the
        # first press -- and a press landed a moment early, or at the wrong panel of a wide frame, or
        # while the player was still sliding into place, then retires a real door for the whole attempt.
        # The flight after that fix offered none of the two doors it walked up to and pressed Use zero
        # times, and spent 48% of its ticks grinding on geometry that would have opened.
        if best["tries"] >= 3:
            best["not_a_door"] = True
            best["why"] = "pressed three times, nothing opened"
        return False

    def door_suspects(self):
        """Every ceiling-change line seen, and what became of it. Diagnostics only."""
        return dict(self.doors)

    def threat_near(self, x, y, radius=THREAT_NEAR):
        """Which monster class is standing near this place, and how many things are.

        The class rather than a danger score: the payload has no business ranking monsters, and the same
        observation has to serve a decision made with the knowledge file open.
        """
        best, count = NO_ENEMY, 0
        for rec in self.objects.values():
            if rec["kind"] != "enemy" or rec["state"] != "alive":
                continue
            if math.hypot(rec["x"] - x, rec["y"] - y) > radius:
                continue
            count += 1
            idx = ENEMY_INDEX.get(rec["name"])
            if idx is not None and (best == NO_ENEMY or idx > best):
                best = idx
        return best, min(255, count)

    # ------------------------------------------------------------------ planning
    def plan_to(self, x, y, goal_cell, now):
        """A* from the player's cell to `goal_cell` over walkable floor. None when there is no way."""
        self.planner_calls += 1
        start = self.ex.cell(x, y)
        walk = self.walkable(now)
        walk.add(start)                      # the player is standing somewhere, by definition
        if goal_cell not in walk:
            # aim at the walkable cell nearest the goal instead of failing outright
            near = [c for c in walk if abs(c[0] - goal_cell[0]) <= 2 and abs(c[1] - goal_cell[1]) <= 2]
            if not near:
                self.planner_failures += 1
                return None
            goal_cell = min(near, key=lambda c: (c[0] - goal_cell[0]) ** 2 + (c[1] - goal_cell[1]) ** 2)
        narrow = self.crossing_costs(walk, now)
        h = lambda c: math.hypot(c[0] - goal_cell[0], c[1] - goal_cell[1])
        openq = [(h(start), 0.0, start)]
        came, best = {}, {start: 0.0}
        seen = 0
        while openq:
            _f, g, cur = heapq.heappop(openq)
            if cur == goal_cell:
                path = [cur]
                while cur in came:
                    cur = came[cur]
                    path.append(cur)
                return list(reversed(path))
            seen += 1
            if seen > PATH_MAX_CELLS:
                break
            if g > best.get(cur, 1e18):
                continue
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if not dx and not dy:
                        continue
                    n = (cur[0] + dx, cur[1] + dy)
                    if n not in walk:
                        continue
                    if dx and dy and ((cur[0] + dx, cur[1]) not in walk or (cur[0], cur[1] + dy) not in walk):
                        continue          # no cutting a corner between two walls
                    step = 1.41421 if dx and dy else 1.0
                    ng = g + step + narrow.get(n, 0.0)
                    if ng < best.get(n, 1e18):
                        best[n], came[n] = ng, cur
                        heapq.heappush(openq, (ng + h(n), ng, n))
        self.planner_failures += 1
        return None

    def path_costs(self, x, y, goals, now):
        """Path distance from the player to each of `goals`, in one flood rather than one A* apiece."""
        start = self.ex.cell(x, y)
        walk = self.walkable(now)
        walk.add(start)
        narrow = self.crossing_costs(walk, now)
        want = {g for g in goals}
        dist = {start: 0.0}
        openq = [(0.0, start)]
        out = {}
        # Written out rather than looped over. This is the single most expensive thing the payload does
        # -- measured at 3.9 ms of every tic, which is 27 ms of the one tic in seven it runs on, against
        # a 28.6 ms budget for the whole loop -- and the cost is entirely the inner loop's dictionary and
        # attribute lookups, not the algorithm. Binding them once and unrolling the eight neighbours is
        # the same Dijkstra with the interpreter taken out of it.
        push, pop = heapq.heappush, heapq.heappop
        straight, diag = ((1, 0), (-1, 0), (0, 1), (0, -1)), ((1, 1), (1, -1), (-1, 1), (-1, -1))
        get = dist.get
        while openq and len(out) < len(want):
            g, cur = pop(openq)
            if g > get(cur, 1e18):
                continue
            if cur in want:
                out[cur] = g * GRID
            cx, cy = cur
            for dx, dy in straight:
                n = (cx + dx, cy + dy)
                if n not in walk:
                    continue
                ng = g + 1.0 + narrow.get(n, 0.0) if narrow else g + 1.0
                if ng < get(n, 1e18):
                    dist[n] = ng
                    push(openq, (ng, n))
            for dx, dy in diag:
                n = (cx + dx, cy + dy)
                if n not in walk or (cx + dx, cy) not in walk or (cx, cy + dy) not in walk:
                    continue          # no cutting a corner between two walls
                ng = g + 1.41421 + narrow.get(n, 0.0) if narrow else g + 1.41421
                if ng < get(n, 1e18):
                    dist[n] = ng
                    push(openq, (ng, n))
        return out

    # ------------------------------------------------------------------ the candidate list
    def boss_candidates(self, x, y, boss_names, now):
        """Bosses, once there is nothing else left to try.

        Engine behaviour, not level knowledge: on some maps the way out only opens when the boss-class
        monsters die, so with the frontiers exhausted and no exit seen, killing them becomes a place to
        go. knowledge/doom_rules.yaml names the classes; nothing here knows which map it is on.
        """
        out = []
        for rec in self.objects.values():
            if rec["kind"] == "enemy" and rec["state"] == "alive" and rec["name"] in boss_names:
                cell = (int(math.floor(rec["x"] / GRID)), int(math.floor(rec["y"] / GRID)))
                out.append((cell, rec))
        return out

    def candidates(self, x, y, angle, now, keys_held=(), need=None, limit=8, boss_names=()):
        """Everywhere worth going, nearest-by-path first, pruned to what the ground can score.

        Charter 3.3: code builds the list, the model scores it, code picks. Building it here rather than on
        the ground is not an optimisation -- the path distances need the map, and the map is onboard.
        """
        import time as _t
        self._last_pos = (x, y)
        self.stood.add(self.ex.cell(x, y))
        if self.start is None:
            self.start = (x, y)
        t0 = _t.perf_counter(); self.see_doors(now); _cost("see_doors", t0)
        t0 = _t.perf_counter()
        goals, meta, door_cells = [], {}, set()

        for cell, size, unseen, depth in self.frontiers(x, y, now):
            goals.append(cell)
            meta[cell] = (KIND_FRONTIER, size, "", self.times_tried(cell))
            self._features[cell] = self.frontier_features(cell, size, unseen, depth, x, y)

        _cost("frontiers", t0)
        # Doors, and only the ones that have earned the name. Capped, so that a level full of ceiling
        # changes cannot crowd the frontiers out of a list of eight.
        usable = []
        for cell, rec in self.doors.items():
            if rec.get("not_a_door") or rec.get("see_through") or rec["opened"]:
                continue
            if rec["colour"] and rec["colour"] != "locked" and rec["colour"] not in keys_held:
                continue                       # a locked door without its key is not a place to go
            usable.append((math.hypot(rec["x"] - x, rec["y"] - y), cell, rec))
        known_cells = self.known(now) if usable else set()
        for _d, cell, rec in sorted(usable)[:MAX_DOOR_CANDIDATES]:
            goals.append(cell)
            meta[cell] = (KIND_DOOR, 0, rec["colour"], rec["tries"])
            door_cells.add(cell)
            # Brief 7.3: a door is an opening with a gate, scored on what is behind it like any other way
            # on. It was a `must` candidate with its own top rubric level, which meant every door in the
            # list outranked the frontier that actually led onward -- and since a closed door is exactly
            # where the seen map ends, the thing behind it is measurable in the same way a frontier's is.
            unseen, depth = self._beyond(cell, known_cells)
            self._features[cell] = {"opening_units": int(rec.get("width") or 0), "unseen_cells": unseen,
                                    "open_depth_units": depth * GRID,
                                    "leads_away": self.frontier_features(cell, 0, unseen, depth, x, y)["leads_away"],
                                    "gate": rec["colour"] or "a door"}

        ex_seen = self.ex.nearest_exit(x, y, now)
        if ex_seen:
            cell = (int(math.floor(ex_seen[0] / GRID)), int(math.floor(ex_seen[1] / GRID)))
            goals.append(cell)
            meta[cell] = (KIND_EXIT, 0, "", 0)

        for key, rec in self.objects.items():
            if rec["state"] != "alive" or rec["kind"] == "enemy":
                continue
            if rec["kind"] not in ("key", "weapon") and need and rec["kind"] != need:
                continue                       # only detour for what is actually needed
            cell = (int(math.floor(rec["x"] / GRID)), int(math.floor(rec["y"] / GRID)))
            goals.append(cell)
            meta[cell] = (KIND_KEY if rec["kind"] == "key" else KIND_ITEM, 0, rec["kind"], 0)

        # Charter 3.5's boss rule: only when there is nothing else worth walking to.
        if not goals and boss_names:
            for cell, rec in self.boss_candidates(x, y, boss_names, now):
                goals.append(cell)
                meta[cell] = (KIND_ENEMY, 0, rec["name"], 0)
        if not goals:
            return []
        import time as _t
        t0 = _t.perf_counter()
        # An exit line is a one-sided wall, a door line is the door itself, and an item can sit against a
        # pillar -- so the cell a goal names is regularly a cell no player can stand in, and the flood
        # below would report "no route" to a place the player could walk right up to. `plan_to` already
        # snapped its goal to the nearest cell that works; this is the same courtesy, done once for the
        # whole list. Without it the exit was silently dropped from the candidate list of every attempt
        # that had one.
        goals = self._reachable_goals(goals, meta, door_cells, now)
        costs = self.path_costs(x, y, set(goals), now)
        _cost("path_costs", t0)
        out, no_route = [], 0
        for cell in set(goals):
            if cell not in costs:
                no_route += 1
                # No route to it at all. For a frontier that is temporary -- the map may open up. For a
                # door suspect it is close to proof: a door you cannot walk to is not a door you can use,
                # and one sitting inside a wall would otherwise be approached, abandoned and offered again
                # for the rest of the attempt.
                # `cell in self.doors` as well, because a goal may have been moved to the nearest cell
                # a player can stand in and that cell is not where the door is. Without the second test
                # this raised KeyError and killed a twelve-attempt run on its first level.
                if cell in door_cells and cell in self.doors:
                    self.doors[cell]["not_a_door"] = True
                    self.doors[cell]["why"] = "no walkable route to it"
                continue
            kind, size, colour, tries = meta[cell]
            wx, wy = cell_centre(cell)
            tc, tn = self.threat_near(wx, wy)
            f = self._features.get(cell, {})
            out.append(Candidate(kind, wx, wy, costs[cell],
                                 novelty=min(255, int(f.get("unseen_cells", size * 4))),
                                 colour=colour, tries=tries, cell=cell,
                                 threat_class=tc, threat_count=tn,
                                 opening=int(f.get("opening_units", 0)),
                                 depth=int(f.get("open_depth_units", 0)),
                                 away=bool(f.get("leads_away", True))))
        # A candidate the ground never sees is a candidate the ground cannot choose, so what gets pruned
        # matters as much as what gets offered. Pruning purely by distance was a structural bias toward
        # going back: after walking out of a room the nearest unexplored corners are all behind you, so
        # the eight nearest were mostly the way you came, and the model could only pick among those. Half
        # the list is now the nearest and half the most promising -- how much unknown lies past it -- so
        # "the corner two steps away" and "the corridor across the room" both reach the judgement.
        # Doors are gates, not options: they are already capped at two, and letting them compete with
        # frontiers on promise dropped door_recall to a third -- the outward lean scores a door at the
        # start of a corridor below a frontier at the far end of one, and then the corridor stays shut.
        if not out:
            # Empty means the player has nowhere to go, and it is not rare: 70% of the decisions in two
            # flights came back with no candidates at all, against 19% in the one flight that got closest
            # to the exit. Say which of the three ways it happened -- nothing found, everything already
            # written off, or nothing with a route -- because they have nothing to do with each other.
            self.empty_reason = {"frontiers": len(self._frontiers), "dead": len(self.dead_frontiers),
                                 "goals": len(goals), "no_route": no_route,
                                 "walkable": len(self.walkable(now))}
        # The exit and a key are still `must`: one ends the level and the other opens a door that is
        # otherwise closed for good. A door is not, any more -- see the features above.
        must = [c for c in out if c.kind in (KIND_EXIT, KIND_KEY)]
        rest = [c for c in out if c.kind not in (KIND_EXIT, KIND_KEY)]
        room = max(0, limit - len(must))
        # Half, measured. Giving the nearest a third of the room instead and the rest to promise sounds
        # like the same trade only bolder, and it is not: mean closest approach across five seeds fell
        # from 0.448 of the way to the exit to 0.304 and coverage from 58 cells to 38. The corner two
        # steps away is often the way on, and a list that is mostly far promises walks past it.
        near = sorted(rest, key=lambda c: c.path_units)[:max(1, room // 2)]
        promise = [c for c in sorted(rest, key=lambda c: -self._promise(c)) if c not in near]
        return (must + near + promise)[:limit]

    def _reachable_goals(self, goals, meta, door_cells, now):
        """Move each goal to the nearest cell a player could stand in, keeping what it stands for.

        Measured on the oracle rung, which is handed the exit's exact position: the payload reported the
        exit in telemetry on all 334 decisions of an attempt, and the exit appeared in the candidate list
        on none of them. An exit line is a one-sided wall, so its cell is not walkable, so the flood never
        reached it and it was dropped without a word. The same is true of a door line and of an item
        against a pillar -- and it is true on an honest run too, which means the pilot could never target
        an exit it saw.
        """
        walk = self.walkable(now)
        out = []
        for cell in goals:
            if cell in walk:
                out.append(cell)
                continue
            near = [c for c in walk if abs(c[0] - cell[0]) <= 2 and abs(c[1] - cell[1]) <= 2]
            if not near:
                out.append(cell)                 # genuinely unreachable; the flood will say so
                continue
            moved = min(near, key=lambda c: (c[0] - cell[0]) ** 2 + (c[1] - cell[1]) ** 2)
            kind = meta[cell][0]
            # A cell can be two things at once -- the floor beside an exit line is also a frontier. The
            # exit and a key win, because one ends the level and the other opens what nothing else will.
            if moved not in meta or kind in (KIND_EXIT, KIND_KEY):
                meta[moved] = meta[cell]
                self._features.setdefault(moved, self._features.get(cell, {}))
            if cell in door_cells and moved in self.doors:
                # Only if the moved cell is itself a known door. Otherwise the door stays where it is and
                # the goal is simply the floor in front of it, which is where a player stands to open it.
                door_cells.add(moved)
            out.append(moved)
        return out

    def outwardness(self, c, x, y):
        """0 back toward where the level began, 1 about as far out, 2 further out than here.

        The player's own spawn and its own position, nothing else. A level's way on leads away from where
        it put you down -- that is true of the whole form, not of any particular level -- and it is the
        one thing the pilot can say about a direction without having seen what is down it. `_promise`
        already uses it to decide what to OFFER; this is the same fact said in words, so the head that
        actually chooses can weigh it against the opening, the depth and what is standing there.
        """
        if self.start is None:
            return 1
        here = math.hypot(x - self.start[0], y - self.start[1])
        there = math.hypot(c.x - self.start[0], c.y - self.start[1])
        if there > here + OUTWARD_UNITS:
            return 2
        if there < here - OUTWARD_UNITS:
            return 0
        return 1

    def _promise(self, c):
        """How much a candidate is worth offering: unknown behind it, how far that runs, and how far out
        it is from where the level began.

        Outwardness belongs here rather than in the rubric. Code builds the candidate list (charter 3.3),
        and "an exploring player goes outward" is a policy about what to consider, not a judgement about
        which of two things is better -- the judgement is still the model's, over whatever is offered.
        Putting it in the rubric did not work: jev scored frontiers further out at 4.92 and ones back
        toward the start at 5.52, the wrong way round, because it is one clause among nine.

        It uses nothing but the player's own spawn position. Wherever the way out is, it is not there.
        """
        out = 0.0
        if self.start is not None:
            out = math.hypot(c.x - self.start[0], c.y - self.start[1]) / GRID
        return c.novelty + c.depth / GRID + out

    # ------------------------------------------------------------------ commitment
    def route_to(self, x, y, cand, now, force=False):
        """Walk toward `cand`, keeping the path already being walked unless the new one is clearly better."""
        cur = self.plan
        if (not force and cur is not None and not cur.blocked and cur.target is not None
                and cand is not None and cur.target.cell == cand.cell
                and now - self.last_plan_t < REPLAN_EVERY_S):
            return cur
        if cand is None:
            return cur
        cells = self.plan_to(x, y, cand.cell, now)
        self.last_plan_t = now
        if not cells:
            if cur is not None and cur.target is not None and cur.target.cell == cand.cell:
                cur.blocked = True
            return None
        fresh = Plan(cells, cand, now)
        fresh.straight_line_clear = lambda x0, y0, x1, y1: self.body_can_walk(x0, y0, x1, y1, now)
        if cur is None or cur.blocked or cur.target is None or cur.target.cell != cand.cell or fresh.better_than(cur):
            if cur is None or cur.target is None or cur.target.cell != cand.cell:
                # Setting off somewhere new, not replanning to the same place: the count is of journeys
                # begun, so holding a target through twenty replans still reads as having tried it once.
                self.targeted[cand.cell] = self.targeted.get(cand.cell, 0) + 1
            self.plan = fresh
        return self.plan

    def body_can_walk(self, x0, y0, x1, y1, now, step=GRID / 2.0):
        """Is every point along this segment far enough from something solid for the player to fit?

        The same mask the walkable set is built from, sampled along the line rather than at cell centres.
        The clearance is the player's own radius, which is an engine fact and not a tuning choice.
        """
        mask_of = getattr(self.ex, "blocked_mask", None)
        box = mask_of(now, PLAYER_CLEARANCE_PX) if mask_of else None
        if box is None:
            return True
        blk, ix0, iy0 = box
        span = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(span / step))
        # Start a player's width along the line, not at the player. Standing somewhere is proof it can be
        # stood in, and a player pressed against a wall has a blocked mask under its own feet -- so asking
        # the mask about the starting point answers "you cannot be where you are". With the question asked
        # from the player's own position, every plan was thrown away the moment it was needed: 62% of
        # ticks with a target and no plan, and six cells covered in three minutes.
        skip = PLAYER_CLEARANCE_PX * WPX
        for k in range(n + 1):
            t = k / n
            if t * span < skip:
                continue
            ix, iy = self.ex.wpx(x0 + t * (x1 - x0), y0 + t * (y1 - y0))
            jx, jy = ix - ix0, iy - iy0
            if not (0 <= jy < blk.shape[0] and 0 <= jx < blk.shape[1]):
                return False
            if blk[jy, jx]:
                return False
        return True

    def way_back(self, x, y, at_least):
        """The nearest cell the player has stood in that is at least `at_least` units behind it.

        Ground it has stood on is ground it can stand on -- that is the one claim in this whole world
        model that rests on demonstration rather than inference, and it is exactly what a player wedged
        in a corner needs. Nearest, so the retreat is short; at least `at_least` away, so it is not the
        corner itself.
        """
        best, bd = None, None
        for c in self.stood:
            cx, cy = cell_centre(c)
            d = math.hypot(cx - x, cy - y)
            if d < at_least:
                continue
            if bd is None or d < bd:
                best, bd = (cx, cy), d
        return best

    def times_tried(self, cell):
        """Journeys begun to this place or the cells touching it.

        Neighbours count because a frontier recedes: walk at the edge of the known and the edge moves, so
        the cell offered next time is next door to the one offered last time. Keyed exactly, the player
        would set off for the same opening all afternoon and every offer would still say "no".
        """
        return sum(n for c, n in self.targeted.items()
                   if abs(c[0] - cell[0]) <= 1 and abs(c[1] - cell[1]) <= 1)

    def clear_plan(self):
        self.plan = None
