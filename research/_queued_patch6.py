"""Queued: a sightline stops at a wall whether or not the player has learned where that wall is.

The first dev-bench attempt with geometry on recorded **14,997 cells believed seen and 80 of 1,050 lines
admitted**. Seven per cent of the level's walls known, and fifteen thousand cells of floor claimed. The
fill was casting rays against the admitted lines only, so wherever a wall had not yet been drawn on the
automap the ray went straight through it and marked the room beyond as seen floor.

That is wrong twice over. The frontiers are computed from that set, so they were boundaries of a fiction;
and `walkable` was enormous, which is why `candidates` cost 8.9 ms of every tic and the p95 went to 73 ms
against a 28.6 ms budget.

The fix is not to admit more lines. It is that **a player cannot see through a wall it has not noticed
yet.** Stopping the ray at every classified blocking line -- admitted or not -- produces exactly the
visibility region a real player has, and it is strictly more honest than what it replaces: the pilot's map
still gains nothing until the automap draws the line, it merely stops claiming to have seen past it.

The opaque mask is private to the sensor and never reaches `ex.raster`, so nothing downstream can plan a
route by it. What leaves the module is unchanged: the admitted lines, and a smaller and truer set of cells.
"""
import io
import sys

EDITS = [
    ("payload/seen_geometry.py",
     '''    def _classify(self, sectors):
        owners = {}''',
     '''    def _classify(self, sectors):
        import numpy as np
        self._opaque = np.zeros((self.ex.n, self.ex.n), bool)
        owners = {}'''),

    ("payload/seen_geometry.py",
     '''            ln = group[0][1]
            self._pending[key] = {"a": (ln.x1, ln.y1), "b": (ln.x2, ln.y2), "kind": kind}''',
     '''            ln = group[0][1]
            rec = {"a": (ln.x1, ln.y1), "b": (ln.x2, ln.y2), "kind": kind}
            self._pending[key] = rec
            if kind in (WALL, DOOR):
                # What stops a sightline, whether or not the player has noticed it yet. Private to this
                # module: it never reaches the raster, so nothing can plan a route by it.
                self._mark_opaque(rec)'''),

    ("payload/seen_geometry.py",
     '''    def _draw(self, rec):''',
     '''    def _mark_opaque(self, rec):
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

    def _draw(self, rec):'''),

    ("payload/seen_geometry.py",
     '''            if rec["kind"] == DOOR and key not in flat:
                self._erase(rec)
                rec["kind"] = None
                self.opened += 1''',
     '''            if rec["kind"] == DOOR and key not in flat:
                self._erase(rec)
                self._clear_opaque(rec)
                rec["kind"] = None
                self.opened += 1'''),

    ("payload/seen_geometry.py",
     '''        cls = ex.raster[iy, ix]
        stop = ~inside
        # A closed door stops the view as surely as a wall does; that is what a door is for, and it is
        # why the room behind one stays unknown until it is opened. `_refresh_doors` takes the line out
        # of the map the moment the ceiling moves, so sight follows the door rather than the memory of it.
        for b in tuple(BLOCKING) + (DOOR,):
            stop |= (cls == b)''',
     '''        cls = ex.raster[iy, ix]
        stop = ~inside
        for b in tuple(BLOCKING) + (DOOR,):
            stop |= (cls == b)
        if self._opaque is not None:
            # And every other wall and shut door in the level, learned or not. A player cannot see
            # through a wall it has not noticed yet, and the fill claimed 14,997 cells of floor on seven
            # per cent of a level's walls before this line existed. Nothing here reaches the map: the
            # raster gains a line only when the automap draws it. This only stops the pilot believing it
            # has seen past one.
            stop |= self._opaque[iy, ix]'''),

    ("payload/seen_geometry.py",
     '''        self._dirs = self._radii = None   # the visibility fill's ray table, built once''',
     '''        self._dirs = self._radii = None   # the visibility fill's ray table, built once
        self._opaque = None               # what stops a sightline; private, never reaches the raster'''),
]


def main():
    bad = 0
    for path, old, new in EDITS:
        text = io.open(path, encoding="utf-8").read()
        if new in text:
            print("  %s: already applied" % path)
            continue
        if old not in text:
            print("  MISSING %s: %r" % (path, old.splitlines()[0][:70]))
            bad += 1
            continue
        io.open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))
        print("  %s: patched" % path)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
