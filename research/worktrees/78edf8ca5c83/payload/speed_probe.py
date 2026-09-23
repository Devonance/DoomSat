"""How fast can this player actually move? Charter 3.5: "Confirm the forward delta is at running magnitude."

Developer-side. Faces the player down an open stretch, holds forward at a series of delta values, and
measures the units per second it actually achieves. The number matters twice: charter phase 2's exit test
is a fraction of running speed, and every speed measured before this was taken against an unknown ceiling.

    /root/doom/payload-venv/bin/python payload/speed_probe.py [wad] [map]
"""
import argparse
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vizdoom as vzd

TICRATE = 35


def run(wad, map_name, delta, tics=70, cap=100):
    g = vzd.DoomGame()
    g.set_doom_game_path(wad)
    g.set_doom_map(map_name)
    g.set_doom_skill(3)
    g.set_available_buttons([vzd.Button.MOVE_FORWARD_BACKWARD_DELTA, vzd.Button.TURN_LEFT_RIGHT_DELTA,
                             vzd.Button.SPEED])
    g.set_button_max_value(vzd.Button.MOVE_FORWARD_BACKWARD_DELTA, cap)
    g.set_window_visible(False)
    g.set_screen_resolution(vzd.ScreenResolution.RES_320X240)
    g.set_mode(vzd.Mode.PLAYER)
    g.set_episode_timeout(0)
    g.set_seed(7)
    g.init()
    g.new_episode()
    best = 0.0
    for heading_try in range(8):                   # try a few headings; take the best clear run
        g.new_episode()
        g.make_action([0, 45.0 * heading_try, 0], 1)
        for _ in range(6):
            g.make_action([0, 0, 0], 1)
        x0 = g.get_game_variable(vzd.GameVariable.POSITION_X)
        y0 = g.get_game_variable(vzd.GameVariable.POSITION_Y)
        for _ in range(tics):
            if g.is_episode_finished():
                break
            g.make_action([delta, 0, 0], 1)
        if g.is_episode_finished():
            continue
        x1 = g.get_game_variable(vzd.GameVariable.POSITION_X)
        y1 = g.get_game_variable(vzd.GameVariable.POSITION_Y)
        best = max(best, math.hypot(x1 - x0, y1 - y0) / (tics / TICRATE))
    g.close()
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wad", nargs="?", default="/root/doom/wads/freedoom1.wad")
    ap.add_argument("map", nargs="?", default="E1M1")
    a = ap.parse_args()
    print("delta   units/s   note")
    for delta in (14, 20, 25, 30, 40, 50, 75, 100):
        v = run(a.wad, a.map, delta)
        note = ""
        if delta == 14:
            note = "what the payload has been using"
        elif delta == 25:
            note = "Doom's walking forwardmove"
        elif delta == 50:
            note = "Doom's running forwardmove"
        print("%5d   %7.1f   %s" % (delta, v, note))


if __name__ == "__main__":
    main()
