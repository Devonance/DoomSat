"""Developer probe: depth buffer calibration. Walk toward a wall and regress depth against distance travelled;
compare the centre column with columns near the edge of the view (perpendicular vs radial distance)."""
import math, sys
import numpy as np
import vizdoom as vzd
sys.path.insert(0, ".")
import doom_payload as dp
g = vzd.DoomGame()
g.set_doom_game_path("/root/doom/wads/doom1.wad"); g.set_doom_map("E1M1")
g.set_available_buttons(dp.BUTTONS)
g.set_button_max_value(vzd.Button.TURN_LEFT_RIGHT_DELTA, 6)
g.set_button_max_value(vzd.Button.MOVE_FORWARD_BACKWARD_DELTA, 14)
g.set_window_visible(False)
g.set_screen_resolution(vzd.ScreenResolution.RES_640X480)
g.set_screen_format(vzd.ScreenFormat.RGB24)
g.set_render_hud(True); g.set_render_crosshair(False)
g.set_depth_buffer_enabled(True)
g.set_sound_enabled(False); g.set_episode_timeout(0); g.set_mode(vzd.Mode.PLAYER)
g.init(); g.new_episode()
var = lambda n: float(g.get_game_variable(getattr(vzd.GameVariable, n)))
# face north (90 deg): the start faces north already. Walk forward and sample.
rows = []
for k in range(40):
    s = g.get_state()
    d = s.depth_buffer
    near = d[196:222].min(axis=0)
    rows.append((var("POSITION_X"), var("POSITION_Y"), int(near[320]), int(near[160]), int(near[80]), int(near[560])))
    g.make_action([14, 0, 0, 0, 0, 0, 0], 3)
ys = np.array([r[1] for r in rows]); c = np.array([r[2] for r in rows], float)
ok = c > 3
slope = np.polyfit(ys[ok], c[ok], 1)[0]
print("centre column: depth change per unit travelled =", round(slope, 4), "-> units per depth step =", round(-1 / slope, 2) if slope else None)
print("samples (y, centre, col160, col80, col560):", rows[::8])
# angular check: columns 160 and 80 are at bearings
for col in (160, 80, 560):
    rel = math.degrees(math.atan((0.5 - col / 639) * 2 * math.tan(math.radians(45))))
    print(f"col {col}: bearing {rel:.1f} deg, 1/cos = {1 / math.cos(math.radians(rel)):.3f}")
