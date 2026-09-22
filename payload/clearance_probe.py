import argparse, sys, time
sys.path.insert(0, ".")
import doom_payload as dp
args = argparse.Namespace(port=0, wad="doom1.wad", map="E1M1", skill=2, seed=7, fps=0, quality=45, status_every=3, map_png=None)
p = dp.Payload(args)
for tic in range(60):
    st = p.game.get_state()
    o = p.observe(st)
    if tic in (1, 20, 40, 59):
        x, y, a = o["x"], o["y"], o["angle"]
        ex = p.explorer
        print(f"tic {tic} pos ({x:.0f},{y:.0f}) heading {a:.0f}: clear f/l/r/b = {o['clear_fwd']}/{o['clear_left']}/{o['clear_right']}/{o['clear_back']}; map_clearance L/R/B = {p.map_clearance(x, y, a + 90)}/{p.map_clearance(x, y, a - 90)}/{p.map_clearance(x, y, a + 180)}; plan dil shape {ex.plan['dil'].shape if ex.plan else None}")
        import math
        for name, h in (("L", a + 90), ("R", a - 90), ("B", a + 180)):
            far = (x + 48 * math.cos(math.radians(h)), y + 48 * math.sin(math.radians(h)))
            print("   ", name, "far cell free:", ex.cell(*far) in ex.free, "segment clear (dil):", ex.segment_clear((x, y), far, allow=(dp.NONE, dp.STEP)), "raw:", ex.segment_clear((x, y), far, allow=(dp.NONE, dp.STEP), raw=True))
    p.game.make_action([0, 0, -2, 0, 0, 0, 0], 1)
