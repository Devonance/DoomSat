"""Per-tic response of TURN_LEFT_RIGHT_DELTA bursts from rest (calibration only)."""
import os, vizdoom as vzd
from doom_payload import BUTTONS
g = vzd.DoomGame(); g.set_doom_game_path(os.path.join(os.path.dirname(vzd.__file__), "freedoom2.wad")); g.set_doom_map("MAP01")
g.set_available_buttons(BUTTONS); g.set_button_max_value(vzd.Button.TURN_LEFT_RIGHT_DELTA, 6); g.set_window_visible(False); g.set_sound_enabled(False); g.init(); g.new_episode()
ang = lambda: g.get_game_variable(vzd.GameVariable.ANGLE)
for label, seq in [("9x-6.0 then rest", [-6.0] * 8 + [-2.0] + [0] * 12), ("int -6 x8", [-6] * 8 + [0] * 8), ("-6 with move fwd", [-6] * 8 + [0] * 8)]:
    for _ in range(20): g.make_action([0] * 7, 1)
    a0 = ang(); out = []
    for i, v in enumerate(seq):
        mv = 14 if label.endswith("fwd") else 0
        g.make_action([mv, 0, v, 0, 0, 0, 0], 1)
        out.append(round((ang() - a0 + 180) % 360 - 180, 1))
    print(label, out)
g.close()
