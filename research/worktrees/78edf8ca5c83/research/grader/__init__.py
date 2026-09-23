"""The grader: the only thing in DoomSat allowed to read a level file.

It runs in its own process, after an attempt is over, and answers one question the pilot must never be
able to ask: how far was it from the exit when it stopped. Charter 6.4 turns that into the score for an
unfinished level, and charter honesty test 6 requires that the pilot cannot reach any of this.

The guard below is the enforcement, not a comment. Every pilot process sets DOOMSAT_ROLE=pilot (the
preflight does it, and `scripts/start_pilot.sh` does it), so an accidental `import grader` anywhere on
the flight path raises at import time rather than quietly working.
"""
import os

if os.environ.get("DOOMSAT_ROLE") == "pilot":
    raise ImportError(
        "research.grader may not be imported by a pilot process: it reads the level file, which is level "
        "knowledge the charter forbids on the flight path (charter 2.1, honesty test 6)")

from . import wad, score      # noqa: E402,F401
