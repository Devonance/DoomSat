"""Developer probe: drive the Explorer directly (no socket) and print what each replan sees."""
import math, sys, time
import numpy as np
import vizdoom as vzd
from PIL import Image
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
g.set_render_hud(True); g.set_render_crosshair(True)
g.set_depth_buffer_enabled(True); g.set_labels_buffer_enabled(True)
g.set_automap_buffer_enabled(True); g.set_automap_mode(vzd.AutomapMode.NORMAL)
g.set_automap_rotate(False); g.set_automap_render_textures(False)
g.set_sound_enabled(False); g.set_episode_timeout(0); g.set_mode(vzd.Mode.PLAYER)
g.add_game_args("+am_colorset 0 +am_drawmapback 0 +viz_am_scale 2.5")
g.init()
for c in dp.AM_CVARS:
    g.send_game_command(c)
g.new_episode()
var = lambda n: float(g.get_game_variable(getattr(vzd.GameVariable, n)))
ex = dp.Explorer(var("POSITION_X"), var("POSITION_Y"))
target = None
for tic in range(int(sys.argv[1]) if len(sys.argv) > 1 else 300):
    s = g.get_state()
    x, y, ang = var("POSITION_X"), var("POSITION_Y"), var("ANGLE")
    depth = s.depth_buffer
    band = depth[depth.shape[0] * 5 // 12: depth.shape[0] * 7 // 12]
    row = band.max(axis=0)
    ex.sweep(x, y, ang, row)
    turn, move = 0.0, 0
    if tic % 7 == 0:
        t0 = time.time()
        ex.stamp(s.automap_buffer, x, y)
        p = ex.replan(x, y, time.time())
        dt = (time.time() - t0) * 1000
        pc = ex.cell(x, y)
        j, i = pc[1] - p["cy0"], pc[0] - p["cx0"]
        ecls = [p["ecls"](j, i, d) for d in range(4)]
        print(f"tic {tic:3d} pos ({x:6.0f},{y:6.0f}) ang {ang:4.0f} free {len(ex.free):4d} reached {p['reached']:4d} frontier {len(p['frontier']):3d} "
              f"spots {len(p['spots']):3d} doors {p['doors_known']} exits {len(p['exits'])} | player cell edges E/N/W/S {ecls} | {dt:.0f} ms")
        if p["reached"] < 5 and tic > 0:
            print("   !!! tiny reach; window", p["dil"].shape, "raster px around player:",
                  int((ex.raster[max(0, ex.wpx(x, y)[1] - 10):ex.wpx(x, y)[1] + 10, max(0, ex.wpx(x, y)[0] - 10):ex.wpx(x, y)[0] + 10] > 0).sum()))
            img = ex.render(x, y, ang, None, None)
            if img is not None:
                img.save(f"/mnt/c/Users/Kevin/Genai/DoomSat/out/automap/tiny_{tic}.png")
        # steer toward the nearest frontier
        fr = sorted(p["frontier"])
        target = ex.xy(fr[0][1]) if fr else None
    if target:
        cells = ex.route(ex.cell(*target))
        wp = ex.xy(cells[1]) if len(cells) > 1 else target
        b = dp.bearing_deg(x, y, ang, *wp)
        turn = max(-6.0, min(6.0, b))
        move = 14 if abs(b) < 35 else 0
    g.make_action([move, 0, -turn, 0, 0, 0, 0], 1)
g.close()
