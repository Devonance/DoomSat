"""Calibrate the depth buffer against a ray cast on the live sector lines (calibration only)."""
import math, os
import numpy as np
import vizdoom as vzd
from doom_payload import BUTTONS
wad = os.path.join(os.path.dirname(vzd.__file__), "freedoom2.wad")
g = vzd.DoomGame(); g.set_doom_game_path(wad); g.set_doom_map("MAP01"); g.set_available_buttons(BUTTONS)
g.set_window_visible(False); g.set_screen_resolution(vzd.ScreenResolution.RES_320X240); g.set_screen_format(vzd.ScreenFormat.RGB24)
g.set_depth_buffer_enabled(True); g.set_labels_buffer_enabled(True); g.set_sectors_info_enabled(True); g.set_sound_enabled(False)
g.set_render_hud(False); g.init(); g.new_episode()
def ray(x, y, ang, lines):
    dx, dy = math.cos(math.radians(ang)), math.sin(math.radians(ang)); best = 4000.0
    for x1, y1, x2, y2 in lines:
        sx, sy = x2 - x1, y2 - y1; det = dx * sy - dy * sx
        if abs(det) < 1e-9: continue
        qx, qy = x1 - x, y1 - y; t, u = (qx * sy - qy * sx) / det, (qx * dy - qy * dx) / det
        if t >= 0 and 0 <= u <= 1: best = min(best, t)
    return best
for step in range(6):
    st = g.get_state()
    d = st.depth_buffer; H, W = d.shape
    lines = [(l.x1, l.y1, l.x2, l.y2) for s in st.sectors for l in s.lines if l.is_blocking]
    x, y, ang = [g.get_game_variable(getattr(vzd.GameVariable, n)) for n in ("POSITION_X", "POSITION_Y", "ANGLE")]
    row = d[H // 2]
    fov = 90.0
    print(f"pos=({x:.0f},{y:.0f}) ang={ang:.0f} depth dtype={d.dtype} shape={d.shape} min={d.min()} max={d.max()}")
    for col_frac in (0.05, 0.25, 0.5, 0.75, 0.95):
        col = int(col_frac * (W - 1)); rel = math.degrees(math.atan((0.5 - col_frac) * 2 * math.tan(math.radians(fov / 2))))
        print(f"   col {col:3d} (bearing {rel:+6.1f}) depth={int(row[col]):3d}   raycast={ray(x, y, ang + rel, lines):7.1f}")
    g.make_action([14, 0, 15.0 if step < 3 else 0.0, 0, 0, 0, 0], 8)
lab = [(l.object_name, round(l.object_position_x), round(l.object_position_y), l.x, l.y, l.width, l.height) for l in g.get_state().labels]
print("labels", lab[:6])
g.close()
