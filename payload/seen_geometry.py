"""Exact level geometry, filtered to the lines the automap has already drawn.

The brief of 23 September replaces the automap colour-classification pipeline with this. The old one read
ZDoom's `am_cdwallcolor` -- the "ceiling height changes" category -- as DOOR, which made every step,
window frame and light recess in the level a door suspect: 1,336 of 2,899 candidates in one flight, and a
measured door precision of 0.04. Colour cannot tell a doorway from a ledge, because ZDoom does not draw
them differently.

The engine will hand over the real thing. `sectors_info` gives every sector's floor and ceiling height and
every line bounding it, which says exactly what a doorway, a step, a ledge and a wall are. It is also the
whole level at once, which the charter forbids (honesty test 2) for the obvious reason.

So the boundary is drawn HERE, inside the sensor, and it is the only thing this module exists to enforce:

    a line leaves this module only once the automap has drawn it.

`_admit` is the gate. Nothing else in the payload ever touches `state.sectors`. `unadmitted()` and
`admitted_unseen()` exist for the honesty test, which checks the invariant from the outside, and
`research/honesty.py` plants a line that was never drawn and requires the check to catch it.

Two engine facts worth writing down, both measured rather than assumed (payload/geom_probe.py):

  * **ViZDoom 1.3.0 reports `Sector.floor_height` negated.** Checked against the WAD's own SECTORS lump on
    doom1 E1M1 and E1M2 and freedoom1 E1M1 and E1M3: `floor_height == -wad_floor` for all 797 sectors,
    while `ceiling_height` matches exactly. Taking it as given turns every step into a ledge and half the
    ledges into steps. `floor_of()` is the one place that sign lives.
  * **A closed door is a sector whose ceiling is at its floor.** All four of E1M1's doors are exactly the
    four sectors with `ceiling == floor`, and nothing else in the level is one. That is the brief's rule,
    and it holds on the map it was written for.
"""
import math

import numpy as np

from mapclasses import BLOCKING, DOOR, GRID, STEP, WALL, WPX  # noqa: F401

MAX_STEP = 24.0          # the engine's own rule: a player climbs 24 units and no more
PLAYER_HEIGHT = 56.0     # and fits through an opening this tall
SAMPLE_UNITS = 2.0       # how finely a line is walked when it is drawn into the raster
SEEN_FRACTION = 0.5      # half the points sampled along a line must carry automap pixels (brief 6.2)
SEEN_RADIUS_PX = 2       # how far from the line an automap pixel counts as being on it
DOOR_FLAT = 8.0          # a ceiling within this of its own floor is a closed door, not a room (brief 6.4)
# The visibility fill. Brief 6.3: cast against seen blocking lines at FULL range, not the camera's 400
# units -- a room is explored once it has been seen, and the range camera could only ever see a fifth of
# a Doom hall. These two numbers are a compute bound and nothing else: 240 rays is 1.5 degrees apart,
# which at 2,000 units is a 52-unit gap, and 2,048 units is longer than any sightline in the shareware
# episode. In practice a ray is stopped by a wall the automap has drawn long before either matters.
# The corner of the automap window the payload stamps: AM_W/2 / AM_SCALE by AM_H/2 / AM_SCALE, which is
# 640 by 480 units. A line outside it cannot have been drawn since the last stamp.
AUTOMAP_REACH_UNITS = 800.0
FILL_RAYS = 240
FILL_RANGE = 2048.0
FILL_STEP = GRID / 2.0


def floor_of(sector):
    """The sector's real floor height. See the module docstring: the engine hands this over negated."""
    return -float(sector.floor_height)


def ceiling_of(sector):
    return float(sector.ceiling_height)


def line_key(ln):
    """One key per physical line, whichever of its two sectors is reporting it."""
    a = (round(ln.x1, 1), round(ln.y1, 1))
    b = (round(ln.x2, 1), round(ln.y2, 1))
    return (a, b) if a <= b else (b, a)


class SeenGeometry:
    """The level's lines, classified, and released one at a time as the automap draws them.

    `reveal` is the knowledge boundary as a single word, and it is the only thing separating an honest run
    from a diagnostic one:

      "seen"  a line is released once the automap has drawn it. The honest setting, and the only one a
              scored run may use.
      "all"   every line is released immediately. ORACLE only (charter 2.2 forbids it); the runner marks
              any attempt that used it and the grader refuses to score it.
    """

    def __init__(self, explorer, reveal="seen"):
        self.ex = explorer
        self.reveal = reveal
        self.lines = {}          # key -> {"a", "b", "kind"}: admitted, and drawn into the raster
        self.sectors_seen = 0
        self.admitted = 0
        self.opened = 0
        self._pending = {}       # key -> the same record, classified but not yet drawn on the automap
        self._dirs = self._radii = None   # the visibility fill's ray table, built once
        self._opaque = None               # what stops a sightline; private, never reaches the raster

    # ------------------------------------------------------------------ classification
    def observe(self, sectors, px=None, py=None):
        """Classify what the engine reports, then admit only what the automap has drawn.

        Classification is pure and idempotent, so it happens once; admission is re-tested every call,
        because the automap grows as the player looks around -- but only for lines it could possibly have
        grown over. The automap window the payload stamps is +-640 by +-480 units around the player, so a
        line further away than its corner cannot have gained a pixel since the last look. That is an
        exact statement about the instrument, not a guess: without it every call re-measured all 865
        undrawn lines of a Freedoom level and the sensor cost 15 ms a decision.
        """
        if not self._pending and not self.lines:
            self._classify(sectors)
        self._admit(px, py)
        self._refresh_doors(sectors)

    def _classify(self, sectors):
        import numpy as np
        self._opaque = np.zeros((self.ex.n, self.ex.n), bool)
        owners = {}
        for s in sectors:
            for ln in s.lines:
                owners.setdefault(line_key(ln), []).append((s, ln))
        self.sectors_seen = len(sectors)
        for key, group in owners.items():
            kind = self._kind(group)
            if kind is None:
                continue                       # an open threshold: nothing to draw
            ln = group[0][1]
            rec = {"a": (ln.x1, ln.y1), "b": (ln.x2, ln.y2), "kind": kind}
            self._pending[key] = rec
            if kind in (WALL, DOOR):
                # What stops a sightline, whether or not the player has noticed it yet. Private to this
                # module: it never reaches the raster, so nothing can plan a route by it.
                self._mark_opaque(rec)

    def _refresh_doors(self, sectors):
        """A door that has opened stops being a door.

        The classification above is taken once, because a wall does not become a doorway. A door does:
        its sector's ceiling rises to the room's and the line under it becomes a threshold the player
        walks through. That matters for sight as much as for walking -- a closed door blocks the view and
        an open one does not -- so the pixels come out of the raster the moment the ceiling moves.

        Only the flat sectors are looked at, which on a Freedoom level is a dozen of a hundred and eighty.
        """
        flat = set()
        for sec in sectors:
            if ceiling_of(sec) - floor_of(sec) <= DOOR_FLAT:
                for ln in sec.lines:
                    flat.add(line_key(ln))
        for key, rec in self.lines.items():
            if rec["kind"] == DOOR and key not in flat:
                self._erase(rec)
                self._clear_opaque(rec)
                rec["kind"] = None
                self.opened += 1
            elif rec["kind"] is None and key in flat:
                rec["kind"] = DOOR          # closed again behind the player
                self._draw(rec)

    @staticmethod
    def _kind(group):
        """WALL, DOOR, STEP, or None for a threshold the player walks straight through.

        One-sided lines and anything the engine flags impassable are wall. A two-sided line is judged the
        way the engine judges it: too short an opening to fit through is a wall, more than a 24-unit rise
        is a ledge and therefore a wall, and a smaller rise is a step.
        """
        if any(ln.is_blocking for _s, ln in group):
            return WALL
        if len(group) < 2:
            return WALL
        floors = [floor_of(s) for s, _ln in group]
        ceils = [ceiling_of(s) for s, _ln in group]
        # A sector with no headroom is one of two completely different things, and the brief's rule --
        # ceiling within eight units of the floor -- cannot tell them apart.
        #
        #   a closed DOOR    the ceiling has come DOWN to the floor. Open it and you walk through.
        #   a solid PILLAR   the floor has gone UP to the ceiling. That is how Doom builds a column in
        #                    the middle of a room, and its bounding lines are two-sided and unflagged
        #                    exactly like a door's.
        #
        # Measured, and it matters: with both called doors the oracle rung routed straight through the
        # pillars, and 71 of the 250 rubbing reports in one L0 run were the player pressed against one at
        # seven units with Use pulsing into it. The heights say which is which -- a door's flat is at the
        # neighbouring FLOOR, a pillar's is at the neighbouring CEILING -- and the heights are already here.
        flat = [i for i, (f, c) in enumerate(zip(floors, ceils)) if c - f <= DOOR_FLAT]
        if flat:
            others = [i for i in range(len(group)) if i not in flat]
            if not others:
                return WALL                    # flat on both sides: nothing to walk into
            reachable = min(floors[i] for i in others) + MAX_STEP
            return DOOR if min(floors[i] for i in flat) <= reachable else WALL
        if min(ceils) - max(floors) < PLAYER_HEIGHT:
            return WALL
        rise = max(floors) - min(floors)
        if rise > MAX_STEP:
            return WALL                        # a ledge: the engine will not let the player climb it
        if rise > 0:
            return STEP
        return None

    # ------------------------------------------------------------------ the knowledge boundary
    def _admit(self, px=None, py=None):
        """Release the lines the automap has drawn, and only those."""
        for key in list(self._pending):
            rec = self._pending[key]
            if px is not None and self.reveal != "all":
                (x1, y1), (x2, y2) = rec["a"], rec["b"]
                reach = AUTOMAP_REACH_UNITS + math.hypot(x2 - x1, y2 - y1) / 2.0
                if math.hypot((x1 + x2) / 2.0 - px, (y1 + y2) / 2.0 - py) > reach:
                    continue
            if self.reveal == "all" or self.drawn_fraction(rec) >= SEEN_FRACTION:
                del self._pending[key]
                self.lines[key] = rec
                self.admitted += 1
                self._draw(rec)

    def drawn_fraction(self, rec):
        """How much of this line the automap has drawn.

        Not "is its midpoint drawn": a long wall comes into view a piece at a time, and a line admitted
        from one pixel at one end is a line the player has mostly not seen.
        """
        ex = self.ex
        drawn = getattr(ex, "drawn", None)
        if drawn is None:
            return 0.0
        hit = total = 0
        r = SEEN_RADIUS_PX
        for px, py in self._samples(rec, step=8.0):
            ix, iy = ex.wpx(px, py)
            if not (r <= ix < ex.n - r and r <= iy < ex.n - r):
                continue
            total += 1
            if drawn[iy - r:iy + r + 1, ix - r:ix + r + 1].any():
                hit += 1
        return (hit / total) if total else 0.0

    def unadmitted(self):
        """Lines classified but not released yet. Diagnostics, and the other half of the honesty test."""
        return dict(self._pending)

    def admitted_unseen(self):
        """Admitted lines the automap cannot account for. The honesty test wants this empty.

        Charter 2.4 test 5 says everything remembered was sensed this attempt. For geometry that reads as:
        every line in the world model has automap pixels along it. Under `reveal="all"` it is expected to
        be non-empty, which is exactly why such a run is marked ORACLE and never scored.
        """
        return [k for k, rec in self.lines.items() if self.drawn_fraction(rec) < SEEN_FRACTION]

    # ------------------------------------------------------------------ into the map the pilot steers by
    @staticmethod
    def _samples(rec, step=SAMPLE_UNITS):
        (x1, y1), (x2, y2) = rec["a"], rec["b"]
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) / step))
        for i in range(n + 1):
            t = i / n
            yield x1 + t * (x2 - x1), y1 + t * (y2 - y1)

    def _mark_opaque(self, rec):
        ex = self.ex
        for px, py in self._samples(rec):
            ix, iy = ex.wpx(px, py)
            if 0 <= ix < ex.n and 0 <= iy < ex.n:
                self._opaque[iy, ix] = True

    def _clear_opaque(self, rec):
        ex = self.ex
        for px, py in self._samples(rec):
            ix, iy = ex.wpx(px, py)
            if 0 <= ix < ex.n and 0 <= iy < ex.n:
                self._opaque[iy, ix] = False

    def _draw(self, rec):
        ex, cls = self.ex, rec["kind"]
        if cls is None:
            return
        for px, py in self._samples(rec):
            ix, iy = ex.wpx(px, py)
            if 0 <= ix < ex.n and 0 <= iy < ex.n and ex.raster[iy, ix] < cls:
                ex.raster[iy, ix] = cls

    def _erase(self, rec):
        """Take a line out of the map, but only where it is the class this line put there."""
        ex, cls = self.ex, rec["kind"]
        for px, py in self._samples(rec):
            ix, iy = ex.wpx(px, py)
            if 0 <= ix < ex.n and 0 <= iy < ex.n and ex.raster[iy, ix] == cls:
                ex.raster[iy, ix] = 0

    def redraw(self):
        """Re-stamp every admitted line. Called after anything has cleared part of the raster."""
        for rec in self.lines.values():
            self._draw(rec)

    # ------------------------------------------------------------------ what downstream asks for
    def doors(self):
        """Every admitted door line that is still shut, as (x, y, length).

        The world model's door list with no suspects in it: a door here is a sector whose ceiling is at
        its own floor, not a colour that might be one. One that has opened is not on the list, because
        there is nothing left to open.
        """
        out = []
        for rec in self.lines.values():
            if rec["kind"] != DOOR:
                continue
            (x1, y1), (x2, y2) = rec["a"], rec["b"]
            out.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0, math.hypot(x2 - x1, y2 - y1)))
        return out

    def cells_with_geometry(self):
        """Every 32-unit cell an admitted line passes through. For the honesty test and the overlay."""
        out = set()
        for rec in self.lines.values():
            for px, py in self._samples(rec, step=GRID / 2.0):
                out.add((int(math.floor(px / GRID)), int(math.floor(py / GRID))))
        return out

    # ------------------------------------------------------------------ what has been SEEN, not walked
    def visible_cells(self, px, py, now):
        """Every cell the player can see from here, given the lines it has already seen.

        This is what replaces the range camera as the source of "where is the floor". The camera is
        trusted to 400 units and samples forty columns a tic, so the floor it swept was sparse and full of
        holes, and a cell beside one of those holes looked exactly like a cell beside the edge of the map:
        that is why every frontier came out "right here" and they all looked alike. Sightlines against
        seen walls have neither problem -- a room the player has looked into is filled in one go, and a
        room it has not is not touched.

        It cannot reveal anything: a ray is stopped by the admitted lines and by nothing else, so the
        furthest it can reach is the furthest the player has already seen a wall.
        """
        ex = self.ex
        if self._dirs is None:
            a = np.linspace(0.0, 2.0 * math.pi, FILL_RAYS, endpoint=False)
            self._dirs = (np.cos(a), np.sin(a))
            self._radii = np.arange(FILL_STEP, FILL_RANGE, FILL_STEP)
        ca, sa = self._dirs
        r = self._radii
        xs = px + r[None, :] * ca[:, None]
        ys = py + r[None, :] * sa[:, None]
        ix = ((xs - ex.ox) / WPX).astype(np.intp)
        iy = ((ex.oy - ys) / WPX).astype(np.intp)
        inside = (ix >= 0) & (ix < ex.n) & (iy >= 0) & (iy < ex.n)
        np.clip(ix, 0, ex.n - 1, out=ix)
        np.clip(iy, 0, ex.n - 1, out=iy)
        cls = ex.raster[iy, ix]
        stop = ~inside
        for b in tuple(BLOCKING) + (DOOR,):
            stop |= (cls == b)
        if self._opaque is not None:
            # And every other wall and shut door in the level, learned or not. A player cannot see
            # through a wall it has not noticed yet, and the fill claimed 14,997 cells of floor on seven
            # per cent of a level's walls before this line existed. Nothing here reaches the map: the
            # raster gains a line only when the automap draws it. This only stops the pilot believing it
            # has seen past one.
            stop |= self._opaque[iy, ix]
        # the first stop along each ray, and everything before it is floor the player can see
        any_stop = stop.any(axis=1)
        first = np.where(any_stop, stop.argmax(axis=1), stop.shape[1])
        keep = np.arange(stop.shape[1])[None, :] < first[:, None]
        cx = np.floor(xs[keep] / GRID).astype(np.intp)
        cy = np.floor(ys[keep] / GRID).astype(np.intp)
        return set(zip(cx.tolist(), cy.tolist()))

    def flood_open(self, start_cell, now, limit=40000):
        """Every cell reachable from `start_cell` without crossing something blocking.

        Only meaningful once the lines that would stop it have been admitted, so the payload calls it on
        L0 and nowhere else: with the whole level released, this is the exact walkable map, which is what
        rung L0 of the ladder is for. With a part of the level released it would flood straight through
        the wall it has not seen yet, which is why the honest path keeps using the camera sweep to say
        where the floor is.
        """
        from collections import deque
        from mapclasses import BLOCKING
        ex = self.ex
        seen, q = {start_cell}, deque([start_cell])
        out = set()
        while q and len(seen) < limit:
            cx, cy = q.popleft()
            ix, iy = ex.wpx((cx + 0.5) * GRID, (cy + 0.5) * GRID)
            if ex.klass(ix, iy, now, r=4) in BLOCKING:
                continue
            out.add((cx, cy))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (cx + dx, cy + dy)
                if n not in seen:
                    seen.add(n)
                    q.append(n)
        return out

    def stats(self):
        """Everything a run needs to say about what it was allowed to see.

        `admitted_unseen` is the brief's honesty test, run live at the end of every attempt rather than
        only in the source: a line in the world model with no automap pixels along it is a leak, whatever
        the source says the gate does. On an ORACLE run it is expected to be large, which is the point.
        """
        unseen = self.admitted_unseen()
        return {"classified": self.admitted + len(self._pending), "admitted": self.admitted,
                "pending": len(self._pending), "sectors": self.sectors_seen, "reveal": self.reveal,
                "doors": len(self.doors()), "doors_opened": self.opened, "admitted_unseen": len(unseen),
                "seen_fraction_of_level": (round(self.admitted / (self.admitted + len(self._pending)), 4)
                                           if (self.admitted + len(self._pending)) else None)}
