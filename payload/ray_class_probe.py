"""Why do the map ray and the range camera disagree? Charter 4, the one open sensing item.

The audit measured the two sensors 150 units or more apart on 32% of tics, with `ahead` taking the worse
of the two, and the charter's hypothesis was that two-sided lines -- steps and ledges -- are being
stamped as walls. The charter asks for the line class of every collapsed ray, so that is what this logs:
for each tic where the map ray comes back much shorter than the camera, which automap class stopped it.

Developer-side. It never flies.

    /root/doom/payload-venv/bin/python payload/ray_class_probe.py [wad] [map] [tics]
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import doom_payload as dp        # noqa: E402
import mapclasses as mc          # noqa: E402

CLASS_NAME = {mc.NONE: "nothing", mc.STEP: "floor step", mc.DOOR: "door", mc.LOCK_RED: "locked red",
              mc.LOCK_BLUE: "locked blue", mc.LOCK_YELLOW: "locked yellow", mc.LOCKED: "locked",
              mc.EXIT: "exit line", mc.WALL: "wall", mc.BARRIER: "barrier (learned by bumping)"}
DISAGREE = 150.0


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wad", nargs="?", default="/root/doom/wads/freedoom1.wad")
    ap.add_argument("map", nargs="?", default="E1M1")
    ap.add_argument("tics", nargs="?", type=int, default=2000)
    a = ap.parse_args()

    p = dp.Payload(argparse.Namespace(port=0, wad=a.wad, map=a.map, skill=3, seed=7, fps=0,
                                      quality=45, status_every=3, map_png=None))
    stopped_by = collections.Counter()
    disagreements = ticks = 0
    ray_short = cam_short = 0
    import time
    for tic in range(a.tics):
        if p.game.is_episode_finished() or p.game.is_player_dead():
            p.new_episode()
            continue
        state = p.game.get_state()
        if state is None:
            break
        o = p.observe(state)
        ticks += 1
        cam, ray = o["clear_fwd"], o["clear_map_fwd"]
        if abs(cam - ray) >= DISAGREE:
            disagreements += 1
            if ray < cam:
                ray_short += 1
                # what the map ray hit: re-run it and keep the class that stopped it
                r = p.explorer.ray(o["x"], o["y"], o["angle"], time.time())
                stopped_by[CLASS_NAME.get(r[3], str(r[3]))] += 1
            else:
                cam_short += 1
        # keep it walking so the sample is not one corridor
        p.executor = None
        p.control = dict(move=1, strafe=0, turn=0.0, fire=0, use=1, weapon=0)
        p.last_control_time = time.time()
        p.game.make_action(p.action(tic), 1)

    print("%d tics, %d disagreements of %.0f units or more (%.0f%%)"
          % (ticks, disagreements, DISAGREE, 100.0 * disagreements / max(1, ticks)))
    print("  the map ray was the shorter one %d times, the camera %d" % (ray_short, cam_short))
    print("\nwhat stopped the map ray when it came back short:")
    for name, n in stopped_by.most_common():
        print("  %-28s %5d  %5.1f%%" % (name, n, 100.0 * n / max(1, ray_short)))
    print("\nCharter 4's hypothesis was that two-sided lines (steps, ledges) are stamped as walls. Read the")
    print("'floor step' row against the 'wall' row: a large step share supports it, a large wall share")
    print("says the map is right and the camera is seeing past something the map knows about.")
    try:
        p.game.close()
    except Exception:                                          # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
