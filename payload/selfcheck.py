"""Does the payload still hold together? A smoke check for the side of the stack the unit suite cannot reach.

tests/ runs on a machine with no ViZDoom, so nothing there imports doom_payload. This does, inside the
distro that has the game, and checks the things that break silently when the status record or the button
set changes: that the packed status is the length the flight software expects, that every button the
executor can ask for exists, and that the world model and executor wire up against a real Explorer.

    /root/doom/payload-venv/bin/python payload/selfcheck.py
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import doom_payload as dp        # noqa: E402
import executor as ex_mod        # noqa: E402
import world_model as wm_mod     # noqa: E402

fails = []


def check(name, ok, detail=""):
    print("%-4s %-46s %s" % ("ok" if ok else "FAIL", name, detail))
    if not ok:
        fails.append(name)


check("status format packs to STATUS_LEN",
      struct.calcsize(dp.STATUS_FULL_FMT) == dp.STATUS_LEN, "%d bytes" % dp.STATUS_LEN)
check("core status is still 120 bytes",
      struct.calcsize(dp.STATUS_FMT) == 120, "the pre-charter channels are unchanged")
check("candidate block is 8 candidates + a count, then the player's threat",
      dp.STATUS_LEN - 120 == (1 + struct.calcsize("!" + dp.CAND_FMT) * dp.MAX_CANDIDATES
                              + struct.calcsize("!" + dp.THREAT_FMT)),
      "%d bytes per candidate, %d for the threat"
      % (struct.calcsize("!" + dp.CAND_FMT), struct.calcsize("!" + dp.THREAT_FMT)))

for slot, btn in dp.WEAPON_BUTTON.items():
    check("weapon slot %d has a button" % slot, btn in dp.BUTTON_INDEX)
check("the executor's running delta matches the payload's",
      ex_mod.RUN_DELTA == dp.RUN_FORWARD, "%g" % ex_mod.RUN_DELTA)

ex = dp.Explorer(0.0, 0.0)
world = wm_mod.WorldModel(ex)
executor = ex_mod.Executor(world)
check("a fresh world model is empty",
      not world.objects and not world.doors and world.plan is None)

# a small patch of swept floor with a hole in the middle of one side: one frontier, and a route to it
for cx in range(-4, 5):
    for cy in range(-4, 5):
        ex.free.add((cx, cy))
ex.visited[(0, 0)] = 1
fr = world.frontiers(0.0, 0.0, 0.0, force=True)
check("frontiers are found on the edge of swept floor", bool(fr), "%d clusters" % len(fr))
path = world.plan_to(0.0, 0.0, (3, 3), 0.0)
check("the planner finds a route across open floor", bool(path), "%d cells" % (len(path or [])))
cands = world.candidates(0.0, 0.0, 0.0, 0.0)
check("candidates come back with a path distance", bool(cands) and all(c.path_units >= 0 for c in cands),
      ", ".join(repr(c) for c in cands[:3]))

obs = {"x": 0.0, "y": 0.0, "angle": 0.0, "clear_fwd": 400, "clear_fl": 400, "clear_fr": 400,
       "clear_back": 400, "enemies": [], "ahead_kind": "nothing", "ahead_dist": 0,
       "all_blocked": False, "expire_barriers": lambda: None, "has_ammo": True}
cmd = executor.step(obs, 0.0)
check("with no intent the executor holds still", cmd["move"] == 0 and cmd["turn"] == 0)
executor.set_intent(ex_mod.Intent(mode="EXPLORE", target_x=400.0, target_y=0.0, has_target=True, ttl_ms=2000), now=0.0)
cmd = executor.step(obs, 0.0)
check("with an intent it runs at the running delta", cmd["move"] == ex_mod.RUN_DELTA, "%g" % cmd["move"])
cmd = executor.step(obs, 10.0)
check("a stale intent falls back to safe behaviour", cmd["move"] == 0.0)

# a stationary player, sampled at 35 Hz the way the real loop does
fresh = ex_mod.Executor(world)
tripped = False
for i in range(200):
    tripped = fresh.watchdog.step(i / 35.0, 0.0, 0.0, False, lambda: None) or tripped
check("the watchdog trips when nothing has moved", tripped, fresh.watchdog.reason)
cmd = executor._recover(obs)
check("recovery always commands motion", cmd["move"] != 0 or cmd["strafe"] != 0,
      "the payload's stuck detector needs the player to push")

print("\n%d checks failed" % len(fails))
sys.exit(1 if fails else 0)
