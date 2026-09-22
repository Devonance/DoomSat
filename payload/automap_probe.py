"""What does the in-game automap look like to the payload? Render it at the level start (NORMAL mode:
only lines the player has seen, no rotation, no textures), list the colours, try custom colour cvars."""
import os, sys
import numpy as np
import vizdoom as vzd
from PIL import Image

wad = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(vzd.__file__), "freedoom2.wad")
m = sys.argv[2] if len(sys.argv) > 2 else "MAP01"
g = vzd.DoomGame()
g.set_doom_game_path(wad)
g.set_doom_map(m)
g.set_window_visible(False)
g.set_screen_resolution(vzd.ScreenResolution.RES_640X480)
g.set_screen_format(vzd.ScreenFormat.RGB24)
g.set_render_hud(True)
g.set_depth_buffer_enabled(True)
g.set_automap_buffer_enabled(True)
g.set_automap_mode(vzd.AutomapMode.NORMAL)
g.set_automap_rotate(False)
g.set_automap_render_textures(False)
g.set_available_buttons([vzd.Button.TURN_LEFT_RIGHT_DELTA, vzd.Button.MOVE_FORWARD_BACKWARD_DELTA, vzd.Button.USE])
g.set_button_max_value(vzd.Button.TURN_LEFT_RIGHT_DELTA, 10)
g.set_sound_enabled(False)
g.set_episode_timeout(0)
g.set_mode(vzd.Mode.PLAYER)
g.add_game_args("+am_colorset 0 +am_showtriggerlines 1 +am_showkeys 0 +am_drawmapback 0")
g.init()
for c in ['am_backcolor "00 00 00"', 'am_wallcolor "ff 00 00"', 'am_fdwallcolor "00 ff 00"', 'am_cdwallcolor "00 00 ff"',
          'am_lockedcolor "ff ff 00"', 'am_specialwallcolor "ff 00 ff"', 'am_interlevelcolor "00 ff ff"',
          'am_intralevelcolor "ff 80 00"', 'am_yourcolor "ff ff ff"', 'am_tswallcolor "80 80 80"', 'am_secretwallcolor "ff 00 00"',
          'am_secretsectorcolor "ff 00 00"', 'am_notseencolor "00 00 00"', 'am_gridcolor "00 00 00"', 'am_showgrid 0']:
    g.send_game_command(c)
g.new_episode()
out = "/mnt/c/Users/Kevin/Genai/DoomSat/out/automap"
os.makedirs(out, exist_ok=True)
def dump(tag):
    s = g.get_state()
    am = s.automap_buffer
    Image.fromarray(am).save(f"{out}/{tag}.png")
    Image.fromarray(s.screen_buffer).save(f"{out}/{tag}_screen.png")
    cols, counts = np.unique(am.reshape(-1, 3), axis=0, return_counts=True)
    order = np.argsort(-counts)
    print(tag, "pos", g.get_game_variable(vzd.GameVariable.POSITION_X), g.get_game_variable(vzd.GameVariable.POSITION_Y),
          "angle", g.get_game_variable(vzd.GameVariable.ANGLE))
    for i in order[:12]:
        print("   ", tuple(int(v) for v in cols[i]), int(counts[i]))
    return am
g.make_action([0, 0, 0], 5)
dump("start")
for k in range(36):        # a full turn, so the map shows the whole start room
    g.make_action([10, 0, 0], 1)
am1 = dump("turned")
for k in range(70):        # walk forward 70 tics
    g.make_action([0, 14, 0], 1)
am2 = dump("walked")
g.close()
