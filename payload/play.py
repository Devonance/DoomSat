"""Doom on its own: ViZDoom with nothing else attached. Checks the payload install, or just lets you play.

    python payload/play.py                     a window you play with keyboard and mouse (needs a display;
                                               on Windows 11, WSLg provides one)
    python payload/play.py --check             no window: run 100 tics, save out/doom_check.png, exit
    python payload/play.py --wad freedoom1.wad --map E1M1

WADs are looked up as given, then in $DOOMSAT_HOME/wads (default ~/doom/wads), then beside ViZDoom
(which bundles freedoom2.wad, maps MAP01..).
"""
import argparse
import os
import time

import vizdoom as vzd


def find_wad(name):
    home = os.environ.get("DOOMSAT_HOME", os.path.expanduser("~/doom"))
    for p in (name, os.path.join(home, "wads", name), os.path.join(os.path.dirname(vzd.__file__), name)):
        if os.path.isfile(p):
            return p
    raise SystemExit(f"WAD not found: {name} (scripts/flight.sh setup wads)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wad", default="doom1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--check", action="store_true", help="headless: 100 tics, one screenshot, exit")
    a = ap.parse_args()

    g = vzd.DoomGame()
    g.set_doom_game_path(find_wad(a.wad))
    g.set_doom_map(a.map)
    g.set_screen_resolution(vzd.ScreenResolution.RES_640X480)
    g.set_screen_format(vzd.ScreenFormat.RGB24)
    g.set_render_hud(True)
    g.set_episode_timeout(0)
    g.set_doom_skill(3)
    if a.check:
        g.set_window_visible(False)
        g.set_available_buttons([vzd.Button.MOVE_FORWARD, vzd.Button.TURN_LEFT])
        g.init()
        for t in range(100):
            g.make_action([1, 1 if (t // 20) % 2 else 0])
        from PIL import Image
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out")
        os.makedirs(out, exist_ok=True)
        Image.fromarray(g.get_state().screen_buffer).save(os.path.join(out, "doom_check.png"))
        print(f"vizdoom {vzd.__version__}: {a.wad} {a.map} ran 100 tics, health "
              f"{g.get_game_variable(vzd.GameVariable.HEALTH):.0f}; screenshot out/doom_check.png")
        g.close()
        return
    g.set_mode(vzd.Mode.SPECTATOR)   # you play; ViZDoom just watches
    g.set_window_visible(True)
    g.add_game_args("+freelook 1")
    g.init()
    print("playing: close the window or Ctrl+C to stop")
    try:
        while not g.is_episode_finished():
            g.advance_action()
            time.sleep(0)
    finally:
        g.close()


if __name__ == "__main__":
    main()
