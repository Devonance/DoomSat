"""Level geometry from the WAD, and the distance-to-exit field the score is built on.

Only the grader imports this. It is a walkability model, not a simulator: it decides which 32-unit cells
a player could stand in, then flood-fills outward from the exit so any position can be turned into "how
much farther, along the floor, to the way out". That number is what makes a run that got two thirds of
the way score better than one that circled the first room, which is the whole reason the charter needs a
grader at all.

What it models, and what it therefore gets wrong:
  - a one-sided line, or a line flagged impassable, blocks;
  - a two-sided line blocks when the opening is shorter than the player or the step up is over 24 units,
    which is the engine's own rule;
  - a door, a locked door or a lift does not block, because the player can open it. That is optimistic
    for a locked door whose key is elsewhere: the grader will say a level is nearly finished when the
    pilot is standing at a locked door with no key. Progress is a partial credit score, not a claim that
    the remaining distance is achievable, and `completed` is the only thing that says a level was beaten.
  - teleports are not modelled, so a level that needs one reads as unreachable past that point. The
    grader reports `reachable: false` for that case instead of silently scoring on a wrong number.
"""
import math
import struct
from collections import deque

CELL = 16                  # the grid the distance field is computed on (map units)
PLAYER_HEIGHT = 56         # the engine's own numbers
PLAYER_RADIUS = 16
MAX_STEP = 24

DOOR = {1, 2, 3, 4, 16, 29, 31, 42, 46, 50, 61, 63, 75, 76, 86, 90, 103, 105, 106, 107, 108, 109, 110,
        111, 112, 113, 114, 115, 116, 117, 118, 175, 196}
KEY_DOOR = {26, 27, 28, 32, 33, 34, 99, 133, 134, 135, 136, 137}
LIFT = {10, 21, 62, 88, 120, 121, 122, 123}
NORMAL_EXIT = {11, 52, 197}      # switch, walk-over, gunshot
SECRET_EXIT = {51, 124, 198}     # charter 1: out of scope
EXIT_SECTOR = {11}               # sector special 11: the "death exit" floor E1M8 ends on
TELEPORT = {39, 97, 125, 126, 174, 195}

FLAG_IMPASSABLE = 0x0001
FLAG_TWO_SIDED = 0x0004


def lumps(path):
    with open(path, "rb") as f:
        data = f.read()
    _ident, n, off = struct.unpack("<4sii", data[:12])
    out = []
    for i in range(n):
        p, size, name = struct.unpack("<ii8s", data[off + 16 * i: off + 16 * i + 16])
        out.append((name.rstrip(b"\0").decode(), p, size))
    return data, out


def maps(path):
    """Every map name in the WAD, in the order it appears."""
    _data, ls = lumps(path)
    # A map is a zero-length marker lump followed by THINGS then LINEDEFS. Looking only for "LINEDEFS
    # somewhere soon after" also matches THINGS itself, which is how the first version of this reported a
    # map called THINGS and nothing else.
    names, seen = [], set()
    for i in range(len(ls) - 2):
        name = ls[i][0]
        if ls[i][2] == 0 and ls[i + 1][0] == "THINGS" and ls[i + 2][0] == "LINEDEFS" and name not in seen:
            names.append(name)
            seen.add(name)
    return names


class Level:
    """One level's lines, vertices, sidedefs, sectors and things."""

    def __init__(self, path, name):
        data, ls = lumps(path)
        idx = [i for i, l in enumerate(ls) if l[0] == name]
        if not idx:
            raise KeyError("%s has no map %s" % (path, name))
        i0 = idx[0]
        d = {ls[j][0]: data[ls[j][1]: ls[j][1] + ls[j][2]] for j in range(i0 + 1, min(i0 + 11, len(ls)))}
        self.name = name
        self.verts = [struct.unpack("<hh", d["VERTEXES"][i:i + 4]) for i in range(0, len(d["VERTEXES"]), 4)]
        self.lines = [struct.unpack("<hhHhhhh", d["LINEDEFS"][i:i + 14]) for i in range(0, len(d["LINEDEFS"]), 14)]
        self.sides = [struct.unpack("<hh8s8s8sh", d["SIDEDEFS"][i:i + 30]) for i in range(0, len(d["SIDEDEFS"]), 30)]
        self.sectors = [struct.unpack("<hh8s8shhh", d["SECTORS"][i:i + 26]) for i in range(0, len(d["SECTORS"]), 26)]
        self.things = [struct.unpack("<hhhhh", d["THINGS"][i:i + 10]) for i in range(0, len(d["THINGS"]), 10)]
        self.moving = self._moving_sectors()

    def _moving_sectors(self):
        """Sectors that something can raise, lower or open.

        A lift is the case that matters. The line that calls the lift is on the floor beside it; the line
        between the lift and the floor is a plain two-sided line with a drop of far more than a step, so a
        static height test walls the level off at every lift. Three shareware levels lost the route to
        their own exit that way. Tags 666 and 667 are in here because they are engine behaviour, not level
        knowledge: the floor a boss level opens when the bosses die.
        """
        tags = {l[4] for l in self.lines if l[3] and l[4]} | {666, 667}
        out = {i for i, s in enumerate(self.sectors) if s[6] in tags}
        for line in self.lines:                     # a manual door has no tag: it moves the sector behind it
            if (line[3] in DOOR or line[3] in KEY_DOOR or line[3] in LIFT) and not line[4]:
                for side in (line[5], line[6]):
                    if 0 <= side < len(self.sides):
                        out.add(self.sides[side][5])
        return out

    # ---------------------------------------------------------------- geometry
    def start(self):
        """Player 1 start: (x, y). Every map has exactly one that counts (the last, if a map has several)."""
        starts = [(t[0], t[1]) for t in self.things if t[3] == 1]
        if not starts:
            raise ValueError("%s has no player 1 start" % self.name)
        return starts[-1]

    def _sector_index(self, side_index):
        if 0 <= side_index < len(self.sides):
            return self.sides[side_index][5]
        return None

    def _sector_of(self, side_index):
        if side_index < 0 or side_index >= len(self.sides):
            return None
        return self.sectors[self.sides[side_index][5]] if 0 <= self.sides[side_index][5] < len(self.sectors) else None

    def blocks(self, line):
        """Does this line stop a player walking across it?"""
        _v1, _v2, flags, special, _tag, right, left = line
        if special in DOOR or special in KEY_DOOR or special in LIFT:
            return False           # it opens; see the module docstring on locked doors
        if flags & FLAG_IMPASSABLE:
            return True
        if left < 0 or not (flags & FLAG_TWO_SIDED):
            return True
        a, b = self._sector_of(right), self._sector_of(left)
        if a is None or b is None:
            return True
        # A closed door sector has its ceiling on its floor. Only the line the player presses carries the
        # door special; the line on the far side of the same sector is usually a plain two-sided line, and
        # measuring its opening while the door is shut says "no gap" and walls the level in half. Three of
        # the eight shareware levels reported no route to their own exit until this case was handled.
        if a[1] == a[0] or b[1] == b[0]:
            return False
        if self._sector_index(right) in self.moving or self._sector_index(left) in self.moving:
            return False           # a lift, a door, or a floor that opens: measure as if it has moved
        opening = min(a[1], b[1]) - max(a[0], b[0])
        if opening < PLAYER_HEIGHT:
            return True
        return abs(a[0] - b[0]) > MAX_STEP

    def exit_lines(self, include_secret=False):
        """Lines that end the level, plus the lines around a sector that ends it.

        E1M8 is the reason for the second half: its exit is not a line at all but sector special 11, the
        "damage until nearly dead, then exit" floor the Barons stand on. A grader that only looked for exit
        linedefs reported that map as having no exit and quietly scored every attempt at it as zero
        progress.
        """
        want = NORMAL_EXIT | (SECRET_EXIT if include_secret else set())
        out = [l for l in self.lines if l[3] in want]
        exit_sectors = {i for i, s in enumerate(self.sectors) if s[5] in EXIT_SECTOR}
        if exit_sectors:
            for line in self.lines:
                for side in (line[5], line[6]):
                    if 0 <= side < len(self.sides) and self.sides[side][5] in exit_sectors:
                        out.append(line)
                        break
        return out

    def has_teleport(self):
        return any(l[3] in TELEPORT for l in self.lines)

    def bbox(self):
        xs = [v[0] for v in self.verts]
        ys = [v[1] for v in self.verts]
        return min(xs), min(ys), max(xs), max(ys)


def _points_on(x0, y0, x1, y1, step=CELL / 2.0):
    """Points along a segment, close enough together that a diagonal wall cannot be stepped through."""
    n = max(2, int(math.hypot(x1 - x0, y1 - y0) / step) + 1)
    for i in range(n + 1):
        t = i / n
        yield x0 + (x1 - x0) * t, y0 + (y1 - y0) * t


def _cells_on(x0, y0, x1, y1, origin, step=CELL / 2.0):
    """Every grid cell a segment passes through."""
    ox, oy = origin
    for x, y in _points_on(x0, y0, x1, y1, step):
        yield int((x - ox) // CELL), int((y - oy) // CELL)


class DistanceField:
    """Walkable cells, and the floor distance from each of them to the nearest normal exit."""

    def __init__(self, level, include_secret=False):
        self.level = level
        x0, y0, x1, y1 = level.bbox()
        self.origin = (x0 - CELL * 2, y0 - CELL * 2)
        self.w = int((x1 - x0) // CELL) + 5
        self.h = int((y1 - y0) // CELL) + 5
        # The space between two rooms is nothing, not floor. Without this the flood walks straight through
        # it and reports a sealed level as nearly finished.
        self.blocked = self._void(level)
        # The player is a cylinder of radius PLAYER_RADIUS, so a cell is unusable when its centre is within
        # that of a wall, not merely when a wall crosses it. Blocking whole cells instead sealed every
        # corridor narrower than two cells, which reported three of the eight shareware levels as having no
        # route to their own exit.
        reach = int(math.ceil(PLAYER_RADIUS / CELL))
        for line in level.lines:
            if not level.blocks(line):
                continue
            (ax, ay), (bx, by) = level.verts[line[0]], level.verts[line[1]]
            for px, py in _points_on(ax, ay, bx, by):
                cx, cy = int((px - self.origin[0]) // CELL), int((py - self.origin[1]) // CELL)
                for dx in range(-reach, reach + 1):
                    for dy in range(-reach, reach + 1):
                        nx, ny = cx + dx, cy + dy
                        if not (0 <= nx < self.w and 0 <= ny < self.h):
                            continue
                        ccx = self.origin[0] + (nx + 0.5) * CELL
                        ccy = self.origin[1] + (ny + 0.5) * CELL
                        if math.hypot(ccx - px, ccy - py) <= PLAYER_RADIUS:
                            self.blocked[ny * self.w + nx] = 1
        self.exit_cells = set()
        for line in level.exit_lines(include_secret):
            (ax, ay), (bx, by) = level.verts[line[0]], level.verts[line[1]]
            for cx, cy in _cells_on(ax, ay, bx, by, self.origin):
                for dx in range(-3, 4):
                    for dy in range(-3, 4):
                        c = (cx + dx, cy + dy)
                        if 0 <= c[0] < self.w and 0 <= c[1] < self.h and not self.blocked[c[1] * self.w + c[0]]:
                            self.exit_cells.add(c)
        self.dist = self._flood(self.exit_cells)

    def _void(self, level):
        """Cells outside the level: everything an ant walking in from the edge of the map can reach without
        ever stepping over a linedef.

        The first attempt at this used crossing parity over one-sided lines, which is the textbook answer
        and is wrong on real geometry often enough to matter -- it reported three of the eight shareware
        levels as having no route to their own exit, because Doom maps do not guarantee that their
        one-sided lines form clean closed loops. Walking in from outside makes no assumption about the
        geometry at all: either there is a gap in the wall or there is not.
        """
        edge = bytearray(self.w * self.h)
        for line in level.lines:
            (ax, ay), (bx, by) = level.verts[line[0]], level.verts[line[1]]
            for cx, cy in _cells_on(ax, ay, bx, by, self.origin, step=CELL / 3.0):
                if 0 <= cx < self.w and 0 <= cy < self.h:
                    edge[cy * self.w + cx] = 1
        void = bytearray(self.w * self.h)
        q = deque()
        for cx in range(self.w):
            for cy in (0, self.h - 1):
                if not edge[cy * self.w + cx] and not void[cy * self.w + cx]:
                    void[cy * self.w + cx] = 1
                    q.append((cx, cy))
        for cy in range(self.h):
            for cx in (0, self.w - 1):
                if not edge[cy * self.w + cx] and not void[cy * self.w + cx]:
                    void[cy * self.w + cx] = 1
                    q.append((cx, cy))
        while q:
            cx, cy = q.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                i = ny * self.w + nx
                if 0 <= nx < self.w and 0 <= ny < self.h and not edge[i] and not void[i]:
                    void[i] = 1
                    q.append((nx, ny))
        return void

    def _flood(self, seeds):
        """Breadth-first over 8 neighbours, in map units (a diagonal costs sqrt 2 cells)."""
        INF = float("inf")
        dist = [INF] * (self.w * self.h)
        q = deque()
        for cx, cy in seeds:
            dist[cy * self.w + cx] = 0.0
            q.append((cx, cy))
        nbr = [(1, 0, CELL), (-1, 0, CELL), (0, 1, CELL), (0, -1, CELL),
               (1, 1, CELL * 1.41421), (1, -1, CELL * 1.41421), (-1, 1, CELL * 1.41421), (-1, -1, CELL * 1.41421)]
        # A plain BFS over two edge weights is not exact, so relax: push a neighbour again when improved.
        while q:
            cx, cy = q.popleft()
            d0 = dist[cy * self.w + cx]
            for dx, dy, cost in nbr:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < self.w and 0 <= ny < self.h) or self.blocked[ny * self.w + nx]:
                    continue
                if dx and dy and (self.blocked[cy * self.w + nx] or self.blocked[ny * self.w + cx]):
                    continue           # no squeezing through the corner between two walls
                if d0 + cost < dist[ny * self.w + nx] - 1e-9:
                    dist[ny * self.w + nx] = d0 + cost
                    q.append((nx, ny))
        return dist

    def cell_of(self, x, y):
        return int((x - self.origin[0]) // CELL), int((y - self.origin[1]) // CELL)

    def at(self, x, y, search=8):
        """Distance to the exit from (x, y). Falls back to the nearest walkable cell within `search` cells,
        because a recorded position sits on a floor the grid may have marked blocked by a nearby wall."""
        cx, cy = self.cell_of(x, y)
        best = None
        for r in range(search + 1):
            for dx in range(-r, r + 1):
                for dy in (-r, r) if r else (0,):
                    for nx, ny in ((cx + dx, cy + dy), (cx + dy, cy + dx)):
                        if 0 <= nx < self.w and 0 <= ny < self.h:
                            d = self.dist[ny * self.w + nx]
                            if d != float("inf") and (best is None or d < best):
                                best = d
            if best is not None:
                return best
        return None

    def reachable(self, x, y):
        return self.at(x, y) is not None
