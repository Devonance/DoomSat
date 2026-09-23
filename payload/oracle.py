"""ORACLE: knowledge the pilot is not allowed to have, handed to it on purpose, to find out what breaks.

This module is a diagnostic instrument and nothing else. Everything it provides -- the whole level's
geometry before it has been seen, the position of the exit before the player has looked at it -- is
forbidden by charter 2.2 and by honesty tests 2 and 5. Any attempt that loads it is stamped
`oracle: L0|L1` in its own record, `research/grade.py` refuses to put it in a summary, and
`research/ledger.py` refuses to build a row from it. It exists to answer one question:

    when the pilot fails, is it failing to see, or failing to act on what it saw?

The ladder, from the brief of 23 September:

  L0  true geometry for the whole level, plus where the exit is. Tests the executor, the INTENT loop and
      the flight stack, and nothing else. If L0 cannot walk to a known exit on a known map, no amount of
      perception work will help.
  L1  true geometry for seen lines only; the exit revealed once it is in view. Tests exploration: the
      player has to find the way out, but never mistakes a ledge for a doorway on the way.
  L2  the stack as flown. Everything.

L0 and L1 both come from `payload/seen_geometry.py`, which already has the gate; the oracle only opens
it. The exit position is the one thing that is not in `sectors_info` at all -- an exit is a linedef
special, and ViZDoom does not report line specials -- so it is read out of the WAD here, by the smallest
reader that can do it. That is the single deliberate violation of "no pilot-side code opens the level
file", and it is confined to this file so it is obvious in a diff.
"""
from mapclasses import EXIT

LEVELS = ("off", "L0", "L1", "L2")
# Brief 5: L1 is told about the exit once it is in view within this far. Near enough that a player facing
# it would read the sign, and far enough that it is not "stand on top of it".
L1_EXIT_IN_VIEW_UNITS = 256.0


def reveal_for(level):
    """What `SeenGeometry.reveal` should be for a rung of the ladder."""
    return "all" if level == "L0" else "seen"


def reveals_exit(level):
    """L0 is told where the exit is. L1 is told once it has looked at it. L2 has to recognise it."""
    return level == "L0"


# ---------------------------------------------------------------- the level file, through the grader's reader
# The brief says to build the oracle from `research/grader/wad.py`, and that is right: a second WAD reader
# is a second thing to be wrong. It cannot be imported as `research.grader.wad`, because that package
# refuses to load in a pilot process (honesty test 6) and the bench runner is one -- so it is loaded
# straight off its path, which is deliberate, visible, and confined to this file.
def _wad_module():
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "research", "grader", "wad.py")
    spec = importlib.util.spec_from_file_location("doomsat_oracle_wad", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def exit_positions(wad_path, map_name):
    """Where every normal exit line on this map is, as (x, y) midpoints.

    ORACLE ONLY. The honest path to this fact is recognising the switch or the EXIT sign on screen, which
    is step 4 of the brief; this is the shortcut that says how much that step is worth.
    """
    wad = _wad_module()
    try:
        level = wad.Level(wad_path, map_name)
    except KeyError:
        return []
    out = []
    for line in level.exit_lines():
        a, b = level.verts[line[0]], level.verts[line[1]]
        out.append(((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0))
    return out


def reveal_exit(explorer, exits, always, px=None, py=None):
    """Put the exit where a seen exit line would have been. ORACLE only.

    It goes into `exit_px` and the raster rather than anywhere new, so every consumer -- `nearest_exit`,
    the slow sense, the exit candidate -- is the same code an honest run uses, and the rung of the ladder
    is the only difference between them.

    `always` is L0: told from the first tic. Otherwise it is L1: told once the automap has drawn the wall
    the switch is on, so the player has looked straight at it and is only being spared recognising the
    switch, which is the brief's second perception change and not what this rung is testing.

    This is deliberately not in the payload. Honesty test 5 forbids any map class being written into the
    raster outside the automap stamp, and that test should keep failing for anything that tries -- so the
    one thing allowed to do it lives in the file named ORACLE, and the payload reaches it only through
    the --oracle flag.
    """
    import math
    if always:
        # L0 is told where the exit is, which has to mean it can act on it. The honest window is six
        # hundred units -- an exit line counts while it is in view -- and leaving that in place made the
        # rung a test of walking to within six hundred units of something it had been told the position
        # of. ORACLE only, and the reason this line lives in this file.
        explorer.exit_search_px = explorer.n
    revealed = 0
    for wx, wy in exits:
        ix, iy = explorer.wpx(wx, wy)
        if not (2 <= ix < explorer.n - 2 and 2 <= iy < explorer.n - 2):
            continue
        if not always:
            # Brief 5: in view, and within L1_EXIT_IN_VIEW_UNITS. Both halves matter -- the automap has
            # drawn the wall it is on, so the player has looked at it, and it is close enough that a
            # player standing there would read the sign rather than having glimpsed it across a hall.
            if px is not None and math.hypot(wx - px, wy - py) > L1_EXIT_IN_VIEW_UNITS:
                continue
            if not explorer.drawn[iy - 3:iy + 4, ix - 3:ix + 4].any():
                continue
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                explorer.exit_px.add((iy + dy, ix + dx))
                explorer.raster[iy + dy, ix + dx] = EXIT
        revealed += 1
    return revealed
