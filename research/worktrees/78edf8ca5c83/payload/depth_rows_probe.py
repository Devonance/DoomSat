"""Developer probe: where is the horizon in the 640x480 depth buffer (with the status bar on)?"""
import sys
import numpy as np
import vizdoom as vzd
sys.path.insert(0, ".")
import doom_payload as dp
g = vzd.DoomGame()
g.set_doom_game_path("/root/doom/wads/doom1.wad"); g.set_doom_map("E1M1")
g.set_available_buttons(dp.BUTTONS)
g.set_window_visible(False)
g.set_screen_resolution(vzd.ScreenResolution.RES_640X480)
g.set_screen_format(vzd.ScreenFormat.RGB24)
g.set_render_hud(True); g.set_render_crosshair(True)
g.set_depth_buffer_enabled(True)
g.set_sound_enabled(False); g.set_episode_timeout(0); g.set_mode(vzd.Mode.PLAYER)
g.init(); g.new_episode()
for tic in range(4):
    g.make_action([0] * len(dp.BUTTONS), 1)
    s = g.get_state()
    d = s.depth_buffer
    col = d[:, 320]
    print(f"tic {s.tic}: shape {d.shape} centre column depth by row:", {r: int(col[r]) for r in range(120, 440, 16)})
print("row with max depth (horizon):", int(np.argmax(col)), "max", int(col.max()))
