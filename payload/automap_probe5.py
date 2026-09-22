"""Developer probe: is the automap buffer stable from tic to tic? Count classified pixels per tic."""
import sys
import numpy as np
import vizdoom as vzd
from PIL import Image
sys.path.insert(0, ".")
from doom_payload import classify, AM_CVARS, BUTTONS, WALL, DOOR, STEP

g = vzd.DoomGame()
g.set_doom_game_path("/root/doom/wads/doom1.wad"); g.set_doom_map("E1M1")
g.set_available_buttons(BUTTONS)
g.set_button_max_value(vzd.Button.TURN_LEFT_RIGHT_DELTA, 6)
g.set_window_visible(False)
g.set_screen_resolution(vzd.ScreenResolution.RES_640X480)
g.set_screen_format(vzd.ScreenFormat.RGB24)
g.set_render_hud(True); g.set_render_crosshair(True)
g.set_depth_buffer_enabled(True); g.set_labels_buffer_enabled(True)
g.set_automap_buffer_enabled(True); g.set_automap_mode(vzd.AutomapMode.NORMAL)
g.set_automap_rotate(False); g.set_automap_render_textures(False)
g.set_sound_enabled(False); g.set_episode_timeout(0); g.set_mode(vzd.Mode.PLAYER)
g.add_game_args("+am_colorset 0 +am_drawmapback 0 +viz_am_scale 2.5")
g.init()
for c in AM_CVARS:
    g.send_game_command(c)
g.new_episode()
bad = 0
for tic in range(120):
    s = g.get_state()
    cls = classify(s.automap_buffer)
    n_wall, n_door, n_step, n_any = int((cls == WALL).sum()), int((cls == DOOR).sum()), int((cls == STEP).sum()), int((cls > 0).sum())
    bright = int((s.automap_buffer.max(axis=2) >= 40).sum())
    if tic < 5 or n_wall > 3000 or tic % 20 == 0:
        print(f"tic {tic}: bright px {bright} classified {n_any} wall {n_wall} door {n_door} step {n_step}")
    if n_wall > 3000 and bad < 2:
        Image.fromarray(s.automap_buffer).save(f"/mnt/c/Users/Kevin/Genai/doom-mission/out/automap/bad_{tic}.png")
        bad += 1
    g.make_action([0, 0, 2 if tic % 2 else 0, 0, 0, 0, 0], 1)
g.close()
