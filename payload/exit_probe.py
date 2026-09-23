"""Can the payload ever see the exit? Put the player at the exit line and count EXIT pixels.

`exit_ever_seen` has been 0 on every graded run this project has ever produced, on the bench and on the
flight stack alike, including a flight that finished fifty units from the door above the exit room. That
is either a very long run of bad luck or an instrument that cannot fire, and the difference matters more
than anything else here: the goal is to reach the exit, and a pilot that cannot perceive one is looking
for something invisible.

    python payload/exit_probe.py            # the shipped automap cvars
    python payload/exit_probe.py --triggers # the same, with am_showtriggerlines 1
"""
import argparse
import os
import sys

import numpy as np
import vizdoom as vzd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import doom_payload as dp                                     # noqa: E402
from mapclasses import EXIT, DOOR, WALL, LOCKED, STEP         # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--wad", default="/root/doom/wads/doom1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--triggers", action="store_true", help="am_showtriggerlines 1")
    ap.add_argument("--tswall", default=None, help="am_tswallcolor, e.g. \"ff 80 00\"")
    ap.add_argument("--at", nargs=2, type=float, default=None, help="warp here first")
    a = ap.parse_args(argv)

    g = vzd.DoomGame()
    g.set_doom_game_path(a.wad)
    g.set_doom_scenario_path(a.wad)
    g.set_doom_map(a.map)
    g.set_screen_resolution(vzd.ScreenResolution.RES_640X480)
    g.set_screen_format(vzd.ScreenFormat.RGB24)   # the payload reads HxWx3; the default is planar
    g.set_automap_buffer_enabled(True)
    g.set_automap_mode(vzd.AutomapMode.NORMAL)
    g.set_automap_rotate(False)
    g.set_automap_render_textures(False)
    g.set_window_visible(False)
    g.set_mode(vzd.Mode.PLAYER)
    g.add_available_button(vzd.Button.TURN_LEFT_RIGHT_DELTA)
    for v in (vzd.GameVariable.POSITION_X, vzd.GameVariable.POSITION_Y):
        g.add_available_game_variable(v)
    g.add_game_args("+am_colorset 0 +am_drawmapback 0 +viz_am_scale 2.5")
    g.init()
    # After init, exactly as the payload does it. Passing these as "+am_backcolor \"00 00 00\"" game args
    # instead mangles every quoted value and the automap comes back uniformly black, which looks a lot
    # like "the exit is invisible" and is really "the probe is broken".
    cvars = list(dp.AM_CVARS)
    if a.triggers:
        cvars = [c for c in cvars if not c.startswith("am_showtriggerlines")] + ["am_showtriggerlines 1"]
    if a.tswall:
        cvars = [c for c in cvars if not c.startswith("am_tswallcolor")] + ['am_tswallcolor "%s"' % a.tswall]
    for c in cvars:
        g.send_game_command(c)
    g.new_episode()
    if a.at:
        g.send_game_command("warp %d %d" % (int(a.at[0]), int(a.at[1])))
    # Turn on the spot first. NORMAL automap mode draws only lines the renderer has actually put on
    # screen, so a player that has been put somewhere and not looked at anything has an empty map --
    # which is the right behaviour and makes "nothing is drawn" a useless answer.
    n = g.get_available_buttons_size()
    turn = g.get_available_buttons().index(vzd.Button.TURN_LEFT_RIGHT_DELTA)
    for _ in range(160):
        act = [0.0] * n
        act[turn] = 6.0
        g.make_action(act, 1)
    s = g.get_state()
    am = s.automap_buffer
    print("automap buffer:", None if am is None else (am.shape, am.dtype, int(am.max())))
    if am is not None and am.max() > 0:
        flat = am.reshape(-1, am.shape[-1]) if am.ndim == 3 else am.reshape(3, -1).T
        bright = flat[flat.max(axis=1) >= 40]
        import collections
        print("  top colours:", collections.Counter(map(tuple, bright.tolist())).most_common(8))
    cls = dp.classify(am)
    g.close()
    names = {EXIT: "EXIT", DOOR: "DOOR", WALL: "WALL", LOCKED: "LOCKED", STEP: "STEP"}
    gv = list(s.game_variables) if s.game_variables is not None else []
    print("am_showtriggerlines %d, player at (%.0f, %.0f)"
          % (1 if a.triggers else 0, gv[0] if gv else 0.0, gv[1] if len(gv) > 1 else 0.0))
    for k, n in sorted(names.items()):
        print("  %-7s %6d pixels" % (n, int((cls == k).sum())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
