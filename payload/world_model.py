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

from mapclasses import BLOCKING, DOOR, EXIT, GRID, LOCK_KEY, LOCKED, WPX, ENEMY_INDEX, NO_ENEMY  # noqa: F401

THREAT_NEAR = 384.0        # an enemy this close to a candidate is a reason to think twice about going there

FRONTIER_MIN_CELLS = 2     # a frontier smaller than this is sensor noise, not a way on
FRONTIER_MAX = 24          # clusters to consider before pruning to the candidates the ground scores
REPLAN_MARGIN = 0.80       # a new path must be this much shorter than the one being walked to replace it
REPLAN_EVERY_S = 1.0       # never replan faster than this, whatever happens
PATH_MAX_CELLS = 4000      # A* gives up rather than stall the control loop
ARRIVE_UNITS = 24.0        # close enough to a waypoint to take the next one, and under one cell: at 48
                           # the cursor cleared two waypoints at once and the walk cut every corner
TARGET_UNITS = 64.0        # close enough to the target to call it reached

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
                 "threat_class", "threat_count")

    def __init__(self, kind, x, y, path_units, novelty=0, colour="", tries=0, cell=None, note="",
                 threat_class=NO_ENEMY, threat_count=0):
        self.kind, self.x, self.y = kind, float(x), float(y)
        self.path_units, self.novelty = float(path_units), int(novelty)
        self.colour, self.tries = colour, int(tries)
        self.cell, self.note = cell, note
        # What is standing near it, as a fact: which class, and how many. Whether that is worth facing is
        # a judgement, and it is made on the ground with the knowledge file in hand.
        self.threat_class, self.threat_count = int(threat_class), int(threat_count)

    def as_dict(self, px, py, heading):
        bearing = (math.degrees(math.atan2(self.y - py, self.x - px)) - heading + 180) % 360 - 180
        return {"kind": KIND_NAME[self.kind], "x": self.x, "y": self.y, "bearing": bearing,
                "path_units": self.path_units, "novelty": self.novelty, "colour": self.colour,
                "threat_class": self.threat_class, "threat_count": self.threat_count,
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

    @property
    def remaining_units(self):
        return max(0, len(self.cells) - self.i - 1) * GRID

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
        # Steer at a waypoint a little way ahead rather than the very next one, so the walk does not
        # zig-zag from cell centre to cell centre.
        j = min(len(self.cells) - 1, self.i + 1)
        return cell_centre(self.cells[j])

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
        self.plan = None
        self.last_plan_t = 0.0
        self.last_frontier_t = -1e9      # not 0.0: that makes the very first call hit the cache and
                                         # return nothing, so the first candidate list of every level
                                         # would be empty
        self._frontiers = []
        self.planner_calls = 0
        self.planner_failures = 0

    # ------------------------------------------------------------------ the floor
    def passable(self, cx, cy, now):
        """Could a player stand in this 32-unit cell?

        Known-free floor that the automap does not show a wall or a remembered barrier in. A door counts
        as passable -- it opens -- unless it is locked and the key is not held, which `Explorer.klass`
        already distinguishes by colour.
        """
        if (cx, cy) not in self.ex.free:
            return False
        ix, iy = self.ex.wpx((cx + 0.5) * GRID, (cy + 0.5) * GRID)
        c = self.ex.klass(ix, iy, now, r=3)
        if c in BLOCKING:
            return False
        if c in LOCK_KEY and LOCK_KEY[c] not in self.ex.keys:
            return False
        return True

    def walkable(self, now):
        return {c for c in self.ex.free if self.passable(c[0], c[1], now)}

    # ------------------------------------------------------------------ frontiers
    def frontiers(self, x, y, now, force=False):
        """Clusters of swept floor that border on ground nothing has seen.

        Yamauchi 1997. A frontier cell is walkable and has at least one neighbour that has never been
        swept; the clusters are the places that, walked to, would show something new.
        """
        if not force and now - self.last_frontier_t < 0.5:
            return self._frontiers
        self.last_frontier_t = now
        walk = self.walkable(now)
        edge = []
        for (cx, cy) in walk:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if (cx + dx, cy + dy) not in self.ex.free:
                    edge.append((cx, cy))
                    break
        self._frontiers = self._cluster(set(edge))
        return self._frontiers

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
        return out[:FRONTIER_MAX]

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
        """Doors and locked doors on the automap, as places rather than pixels."""
        import numpy as np
        ex = self.ex
        cx_, cy_ = ex.wpx(*self._last_pos) if getattr(self, "_last_pos", None) else (ex.n // 2, ex.n // 2)
        a, b = max(0, cx_ - radius_px), min(ex.n, cx_ + radius_px)
        c, d = max(0, cy_ - radius_px), min(ex.n, cy_ + radius_px)
        win = ex.raster[c:d, a:b]
        for cls in (DOOR, LOCKED) + tuple(LOCK_KEY):
            ys, xs = np.nonzero(win == cls)
            for k in range(0, len(xs), 7):      # a door is many pixels; one sample every few is plenty
                wx = ex.ox + (a + int(xs[k])) * WPX
                wy = ex.oy - (c + int(ys[k])) * WPX
                cell = (int(math.floor(wx / GRID)), int(math.floor(wy / GRID)))
                rec = self.doors.setdefault(cell, {"x": wx, "y": wy, "colour": "", "tries": 0,
                                                   "opened": False, "last_try": 0.0})
                rec["colour"] = LOCK_KEY.get(cls, "locked" if cls == LOCKED else "")

    def note_door_try(self, x, y, now, opened=False):
        cell = (int(math.floor(x / GRID)), int(math.floor(y / GRID)))
        best, bd = None, 1e9
        for c, rec in self.doors.items():
            d = math.hypot(rec["x"] - x, rec["y"] - y)
            if d < bd:
                best, bd = rec, d
        if best is not None and bd < 96:
            best["tries"] += 0 if opened else 1
            best["opened"] = best["opened"] or opened
            best["last_try"] = now

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
                    ng = g + step
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
        want = {g for g in goals}
        dist = {start: 0.0}
        openq = [(0.0, start)]
        out = {}
        while openq and len(out) < len(want):
            g, cur = heapq.heappop(openq)
            if g > dist.get(cur, 1e18):
                continue
            if cur in want:
                out[cur] = g * GRID
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if not dx and not dy:
                        continue
                    n = (cur[0] + dx, cur[1] + dy)
                    if n not in walk:
                        continue
                    if dx and dy and ((cur[0] + dx, cur[1]) not in walk or (cur[0], cur[1] + dy) not in walk):
                        continue
                    ng = g + (1.41421 if dx and dy else 1.0)
                    if ng < dist.get(n, 1e18):
                        dist[n] = ng
                        heapq.heappush(openq, (ng, n))
        return out

    # ------------------------------------------------------------------ the candidate list
    def candidates(self, x, y, angle, now, keys_held=(), need=None, limit=8):
        """Everywhere worth going, nearest-by-path first, pruned to what the ground can score.

        Charter 3.3: code builds the list, the model scores it, code picks. Building it here rather than on
        the ground is not an optimisation -- the path distances need the map, and the map is onboard.
        """
        self._last_pos = (x, y)
        self.see_doors(now)
        goals, meta = [], {}

        for cell, size in self.frontiers(x, y, now):
            goals.append(cell)
            meta[cell] = (KIND_FRONTIER, size, "", 0)

        for cell, rec in self.doors.items():
            if rec["opened"] or (rec["tries"] >= 4 and now - rec["last_try"] < 120):
                continue
            if rec["colour"] and rec["colour"] != "locked" and rec["colour"] not in keys_held:
                continue                       # a locked door without its key is not a place to go
            goals.append(cell)
            meta[cell] = (KIND_DOOR, 0, rec["colour"], rec["tries"])

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

        if not goals:
            return []
        costs = self.path_costs(x, y, set(goals), now)
        out = []
        for cell in set(goals):
            if cell not in costs:
                continue                       # no way there from here: not a candidate
            kind, size, colour, tries = meta[cell]
            wx, wy = cell_centre(cell)
            tc, tn = self.threat_near(wx, wy)
            out.append(Candidate(kind, wx, wy, costs[cell], novelty=min(255, size * 4),
                                 colour=colour, tries=tries, cell=cell,
                                 threat_class=tc, threat_count=tn))
        # The exit and keys always make the cut; the rest compete on how far away they are, because a
        # candidate the ground never sees is a candidate the ground cannot choose.
        must = [c for c in out if c.kind in (KIND_EXIT, KIND_KEY)]
        rest = sorted((c for c in out if c.kind not in (KIND_EXIT, KIND_KEY)), key=lambda c: c.path_units)
        return (must + rest)[:limit]

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
        if cur is None or cur.blocked or cur.target is None or cur.target.cell != cand.cell or fresh.better_than(cur):
            self.plan = fresh
        return self.plan

    def clear_plan(self):
        self.plan = None
