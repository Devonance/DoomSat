"""Developer probe: warp next to known line types (exit switch, door, locked door) and see how the
automap colours them. Uses cheats; never part of the payload."""
import os, sys
import numpy as np
import vizdoom as vzd
from PIL import Image

COLORS = {"wall": (255, 0, 0), "cd": (0, 0, 255), "fd": (83, 175, 71), "you": (255, 255, 255)}
def setup(wad, m):
    g = vzd.DoomGame()
    g.set_doom_game_path(wad); g.set_doom_map(m)
    g.set_window_visible(False)
    g.set_screen_resolution(vzd.ScreenResolution.RES_640X480)
    g.set_screen_format(vzd.ScreenFormat.RGB24)
    g.set_render_hud(True)
    g.set_automap_buffer_enabled(True)
    g.set_automap_mode(vzd.AutomapMode.NORMAL)
    g.set_automap_rotate(False)
    g.set_automap_render_textures(False)
    g.set_available_buttons([vzd.Button.TURN_LEFT_RIGHT_DELTA, vzd.Button.MOVE_FORWARD_BACKWARD_DELTA, vzd.Button.USE])
    g.set_button_max_value(vzd.Button.TURN_LEFT_RIGHT_DELTA, 10)
    g.set_sound_enabled(False); g.set_episode_timeout(0); g.set_mode(vzd.Mode.PLAYER)
    g.add_game_args("+sv_cheats 1 +am_colorset 0 +am_showtriggerlines 1 +am_showkeys 1 +am_drawmapback 0")
    g.init()
    for c in ['am_backcolor "00 00 00"', 'am_wallcolor "ff 00 00"', 'am_fdwallcolor "00 ff 00"', 'am_cdwallcolor "00 00 ff"',
              'am_lockedcolor "ff ff 00"', 'am_specialwallcolor "ff 00 ff"', 'am_interlevelcolor "00 ff ff"',
              'am_intralevelcolor "ff 80 00"', 'am_yourcolor "ff ff ff"', 'am_tswallcolor "80 80 80"', 'am_secretwallcolor "ff 00 00"',
              'am_secretsectorcolor "ff 00 00"', 'am_notseencolor "00 00 00"', 'am_gridcolor "00 00 00"', 'am_showgrid 0']:
        g.send_game_command(c)
    g.new_episode()
    return g

def colours(am):
    cols, counts = np.unique(am.reshape(-1, 3), axis=0, return_counts=True)
    order = np.argsort(-counts)
    return [(tuple(int(v) for v in cols[i]), int(counts[i])) for i in order[:14]]

out = "/mnt/c/Users/Kevin/Genai/doom-mission/out/automap"
wad = sys.argv[1]; m = sys.argv[2]; tag = sys.argv[3]
spots = [tuple(float(v) for v in s.split(",")) for s in sys.argv[4:]]   # x,y,angle
g = setup(wad, m)
for i, (x, y, ang) in enumerate(spots):
    g.send_game_command(f"warp {int(x)} {int(y)}")
    g.make_action([0, 0, 0], 2)
    a = g.get_game_variable(vzd.GameVariable.ANGLE)
    d = (ang - a + 180) % 360 - 180
    for _ in range(int(abs(d) // 10)):
        g.make_action([10 if d > 0 else -10, 0, 0], 1)
    g.make_action([0, 0, 0], 3)
    for k in range(36):
        g.make_action([10, 0, 0], 1)     # look around
    s = g.get_state()
    Image.fromarray(s.automap_buffer).save(f"{out}/{tag}_{i}.png")
    Image.fromarray(s.screen_buffer).save(f"{out}/{tag}_{i}_screen.png")
    print(tag, i, "pos", g.get_game_variable(vzd.GameVariable.POSITION_X), g.get_game_variable(vzd.GameVariable.POSITION_Y), colours(s.automap_buffer))
g.close()
