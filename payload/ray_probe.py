import argparse, sys, time, math
import numpy as np
sys.path.insert(0, ".")
import doom_payload as dp
args = argparse.Namespace(port=0, wad="doom1.wad", map="E1M1", skill=2, seed=7, fps=0, quality=45, status_every=3, map_png=None)
p = dp.Payload(args)
for tic in range(30):
    st = p.game.get_state()
    o = p.observe(st)
    p.game.make_action([0, 0, 0, 0, 0, 0, 0], 1)
ex = p.explorer
x, y, a = o["x"], o["y"], o["angle"]
ix, iy = ex.wpx(x, y)
now = time.time()
print("pos", round(x), round(y), "angle", round(a), "clear f/l/r/b", o["clear_fwd"], o["clear_left"], o["clear_right"], o["clear_back"], "map fwd", o["clear_map_fwd"])
print("raster classes within +-4 px of the player:")
for r in range(iy - 4, iy + 5):
    print("   ", "".join(str(int(ex.raster[r, c])) if ex.raster[r, c] else "." for c in range(ix - 4, ix + 5)), "  barrier:", "".join("B" if now - ex.barrier_t[r, c] < dp.BARRIER_S else "." for c in range(ix - 4, ix + 5)))
for name, off in (("fwd", 0), ("left", 90), ("right", -90), ("back", 180)):
    print(name, ex.ray(x, y, a + off, now))
for rr in (8, 12, 16, 20, 24):
    print("  r", rr, "klass fwd", ex.klass(*ex.wpx(x + rr * math.cos(math.radians(a)), y + rr * math.sin(math.radians(a))), now))
