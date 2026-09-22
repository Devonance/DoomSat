"""Developer probe: sample the automap pixels exactly where known line types are (E1M2 shareware)."""
import sys, math
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
g.set_automap_buffer_enabled(True)
g.set_automap_mode(vzd.AutomapMode.NORMAL)
g.set_automap_rotate(False)
g.set_automap_render_textures(False)
g.set_available_buttons([vzd.Button.TURN_LEFT_RIGHT_DELTA, vzd.Button.MOVE_FORWARD_BACKWARD_DELTA, vzd.Button.USE])
g.set_button_max_value(vzd.Button.TURN_LEFT_RIGHT_DELTA, 10)
g.set_sound_enabled(False); g.set_episode_timeout(0); g.set_mode(vzd.Mode.PLAYER)
g.add_game_args("+sv_cheats 1 +am_colorset 0 +am_showkeys 1 +am_showtriggerlines 1 +am_drawmapback 0 +viz_am_scale 2.5")
g.init()
for c in ['am_backcolor "00 00 00"', 'am_wallcolor "ff ff ff"', 'am_fdwallcolor "00 ff 00"', 'am_cdwallcolor "80 80 ff"',
          'am_lockedcolor "ff ff 00"', 'am_specialwallcolor "ff ff 00"', 'am_interlevelcolor "ff 80 00"', 'am_intralevelcolor "ff 80 80"',
          'am_yourcolor "ff 00 ff"', 'am_tswallcolor "00 00 00"', 'am_secretwallcolor "ff ff ff"', 'am_secretsectorcolor "ff ff ff"',
          'am_notseencolor "00 00 00"', 'am_gridcolor "00 00 00"', 'am_showgrid 0', 'am_efwallcolor "00 00 00"']:
    g.send_game_command(c)
g.new_episode()
S, CX, CY = 0.5, 320, 240
def top(win, n=6):
    cols, counts = np.unique(win.reshape(-1, 3), axis=0, return_counts=True)
    order = np.argsort(-counts)
    return [(tuple(int(v) for v in cols[i]), int(counts[i])) for i in order[:n] if tuple(cols[i]) != (0, 0, 0)]
spots = {"E1M2": [(-620, 384, 180, "red key door", ((-720, 320), (-720, 448))),
                  (740, 0, 0, "plain door", ((848, -64), (848, 64))),
                  (-180, 2336, 180, "exit switch", ((-256, 2304), (-256, 2368)))],
         "E1M1": [(2970, -4768, 180, "exit switch", ((2912, -4800), (2912, -4736))),
                  (1056, -3616, 90, "start", ((1056, -3616), (1056, -3616)))]}
for (x, y, ang, tag, seg) in spots[m]:
    g.send_game_command(f"warp {x} {y}")
    g.make_action([0, 0, 0], 2)
    a = g.get_game_variable(vzd.GameVariable.ANGLE)
    d = (ang - a + 180) % 360 - 180
    for _ in range(36):
        g.make_action([10, 0, 0], 1)
    g.make_action([0, 0, 0], 5)
    s = g.get_state()
    am = s.automap_buffer
    px, py = g.get_game_variable(vzd.GameVariable.POSITION_X), g.get_game_variable(vzd.GameVariable.POSITION_Y)
    (x1, y1), (x2, y2) = seg
    u1, v1 = int(round(CX + S * (x1 - px))), int(round(CY - S * (y1 - py)))
    u2, v2 = int(round(CX + S * (x2 - px))), int(round(CY - S * (y2 - py)))
    win = am[min(v1, v2) - 4:max(v1, v2) + 5, min(u1, u2) - 4:max(u1, u2) + 5]
    row = am[240]
    print(tag, "at", px, py, "segment px", (u1, v1), (u2, v2), "colours on it:", top(win), "whole map:", top(am, 10))
    print("   row 240 non-black:", [(u, tuple(int(v) for v in row[u])) for u in range(640) if row[u].max() > 30][:30])
    Image.fromarray(am).save(f"/mnt/c/Users/Kevin/Genai/doom-mission/out/automap/p4_{tag.replace(' ', '_')}.png")
g.close()
