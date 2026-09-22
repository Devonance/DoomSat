"""Developer probe: is the depth buffer radial (Euclidean) or perpendicular (z) distance? Rotate and watch the
same wall point move across the screen."""
import math, sys
import numpy as np
import vizdoom as vzd
sys.path.insert(0, ".")
import doom_payload as dp
g = vzd.DoomGame()
g.set_doom_game_path("/root/doom/wads/doom1.wad"); g.set_doom_map("E1M1")
g.set_available_buttons(dp.BUTTONS)
g.set_button_max_value(vzd.Button.TURN_LEFT_RIGHT_DELTA, 6)
g.set_window_visible(False)
g.set_screen_resolution(vzd.ScreenResolution.RES_640X480)
g.set_screen_format(vzd.ScreenFormat.RGB24)
g.set_render_hud(True); g.set_render_crosshair(False)
g.set_depth_buffer_enabled(True)
g.set_sound_enabled(False); g.set_episode_timeout(0); g.set_mode(vzd.Mode.PLAYER)
g.init(); g.new_episode()
g.make_action([0] * 7, 2)
var = lambda n: float(g.get_game_variable(getattr(vzd.GameVariable, n)))
s = g.get_state(); a0 = var("ANGLE"); D = int(s.depth_buffer[196:222].min(axis=0)[320])
print(f"heading {a0:.1f}: centre depth {D}")
for turn in (6, 12, 18, 24, 30):
    while var("ANGLE") - a0 < turn - 0.5:
        g.make_action([0, 0, -6, 0, 0, 0, 0], 1)   # turn left 6 deg/tic (negative delta = left in this setup)
    s = g.get_state(); a = var("ANGLE")
    rel = a0 - a   # the original point is now to the right by (a - a0) degrees -> negative bearing
    col = int(round(320 - math.tan(math.radians(rel)) * 320))
    near = s.depth_buffer[196:222].min(axis=0)
    print(f"turned {a - a0:5.1f} deg: point now at col {col}: depth {int(near[col])}  (radial expects {D}, perpendicular expects {D * math.cos(math.radians(rel)):.1f})")
