"""Developer probe: which colours survive the palette, what the lock/exit lines render as, the scale
set by viz_am_scale, and where the player is on the automap image."""
import sys
import numpy as np
import vizdoom as vzd
from PIL import Image

wad, m = sys.argv[1], sys.argv[2]
g = vzd.DoomGame()
g.set_doom_game_path(wad); g.set_doom_map(m)
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
g.set_sound_enabled(False); g.set_episode_timeout(0); g.set_mode(vzd.Mode.PLAYER)
g.add_game_args("+sv_cheats 1 +am_colorset 0 +am_showkeys 1 +am_drawmapback 0 +viz_am_scale 2.5")
g.init()
base = ['am_backcolor "00 00 00"', 'am_fdwallcolor "00 00 00"', 'am_cdwallcolor "00 00 00"', 'am_lockedcolor "00 00 00"',
        'am_specialwallcolor "00 00 00"', 'am_interlevelcolor "00 00 00"', 'am_intralevelcolor "00 00 00"', 'am_yourcolor "00 00 00"',
        'am_tswallcolor "00 00 00"', 'am_secretwallcolor "00 00 00"', 'am_secretsectorcolor "00 00 00"', 'am_notseencolor "00 00 00"',
        'am_gridcolor "00 00 00"', 'am_showgrid 0', 'am_efwallcolor "00 00 00"']
for c in base:
    g.send_game_command(c)
g.new_episode()
g.make_action([0, 0, 0], 3)

def top(am, n=6):
    cols, counts = np.unique(am.reshape(-1, 3), axis=0, return_counts=True)
    order = np.argsort(-counts)
    return [(tuple(int(v) for v in cols[i]), int(counts[i])) for i in order[:n] if counts[i] > 3 and tuple(cols[i]) != (0, 0, 0)]

# 1. which colours survive the palette (set as wall colour, everything else black)
print("palette mapping:")
for cand in ["ff ff ff", "ff 00 00", "00 ff 00", "00 00 ff", "ff ff 00", "ff 00 ff", "00 ff ff", "ff 80 00", "80 80 ff", "ff 80 80",
             "80 ff 80", "80 80 80", "c0 c0 c0", "ff c0 00", "00 80 ff", "c0 00 ff", "ff 00 80", "80 40 00", "40 40 ff", "ff ff 80"]:
    g.send_game_command(f'am_wallcolor "{cand}"')
    g.make_action([0, 0, 0], 1)
    print("  ", cand, "->", top(g.get_state().automap_buffer, 3))
g.send_game_command('am_wallcolor "ff ff ff"')

# 2. player marker position: arrow colour on, everything else black, spin and average
g.send_game_command('am_wallcolor "00 00 00"'); g.send_game_command('am_yourcolor "ff ff ff"')
pts = []
for k in range(36):
    g.make_action([10, 0, 0], 1)
    am = g.get_state().automap_buffer
    ys, xs = np.nonzero(am[:, :, 0] > 200)
    pts.append((xs.mean(), ys.mean(), len(xs)))
print("arrow centroid mean", np.mean([p[0] for p in pts]), np.mean([p[1] for p in pts]), "px per frame", np.mean([p[2] for p in pts]))
cx, cy = float(np.mean([p[0] for p in pts])), float(np.mean([p[1] for p in pts]))

# 3. scale: walls white only; compare the depth straight ahead with the first white pixel along the heading
g.send_game_command('am_yourcolor "00 00 00"'); g.send_game_command('am_wallcolor "ff ff ff"')
import math
for k in range(8):
    g.make_action([10, 0, 0], 5)
    s = g.get_state()
    ang = g.get_game_variable(vzd.GameVariable.ANGLE)
    d = s.depth_buffer[s.depth_buffer.shape[0] // 2, s.depth_buffer.shape[1] // 2]
    am = s.automap_buffer
    hit = None
    for r in range(2, 300):
        u, v = int(round(cx + r * math.cos(math.radians(ang)))), int(round(cy - r * math.sin(math.radians(ang))))
        if 0 <= u < am.shape[1] and 0 <= v < am.shape[0] and am[v, u, 0] > 200:
            hit = r; break
    print(f"  heading {ang:6.1f} depth {int(d)} steps (~{int(d)*8.5:.0f} units) first wall px {hit} -> scale {hit/(int(d)*8.5) if hit and d else 0:.3f} px/unit")

# 4. lock / exit / door colours at known spots (doom1 E1M2: red key door at x=-720..-736 y 320..448; door at 848; exit at -256, 2304..2368)
for c in ['am_wallcolor "ff ff ff"', 'am_fdwallcolor "00 ff 00"', 'am_cdwallcolor "80 80 ff"', 'am_lockedcolor "ff ff 00"',
          'am_interlevelcolor "00 ff ff"', 'am_intralevelcolor "ff 80 00"', 'am_yourcolor "ff 00 ff"']:
    g.send_game_command(c)
for (x, y, ang, tag) in [(-620, 384, 180, "red key door"), (740, 0, 0, "plain door"), (-180, 2336, 180, "exit switch")]:
    g.send_game_command(f"warp {x} {y}")
    g.make_action([0, 0, 0], 2)
    a = g.get_game_variable(vzd.GameVariable.ANGLE)
    d = (ang - a + 180) % 360 - 180
    for _ in range(int(abs(d) // 10)):
        g.make_action([10 if d > 0 else -10, 0, 0], 1)
    g.make_action([0, 0, 0], 3)
    s = g.get_state()
    am = s.automap_buffer
    # colours within 40 px of the centre, in front
    win = am[int(cy) - 40:int(cy) + 40, int(cx) - 40:int(cx) + 40]
    print(tag, "pos", g.get_game_variable(vzd.GameVariable.POSITION_X), g.get_game_variable(vzd.GameVariable.POSITION_Y), "near colours", top(win, 8))
    Image.fromarray(am).save(f"/mnt/c/Users/Kevin/Genai/DoomSat/out/automap/p3_{tag.replace(' ', '_')}.png")
    Image.fromarray(s.screen_buffer).save(f"/mnt/c/Users/Kevin/Genai/DoomSat/out/automap/p3_{tag.replace(' ', '_')}_screen.png")
g.close()
