"""Developer-side level map (never used by the agent): draw a level's lines with doors, exit, start and things."""
import struct, sys, math
from PIL import Image, ImageDraw
sys.path.insert(0, "/mnt/c/Users/Kevin/Genai/DoomSat/tools")
import wad_stats as w
path, name, out = sys.argv[1], sys.argv[2], sys.argv[3]
data, ls = w.lumps(path)
idx = [i for i, l in enumerate(ls) if l[0] == name][0]
d = {ls[j][0]: data[ls[j][1]: ls[j][1] + ls[j][2]] for j in range(idx + 1, idx + 11)}
lines = [struct.unpack("<hhHhhhh", d["LINEDEFS"][i:i + 14]) for i in range(0, len(d["LINEDEFS"]), 14)]
verts = [struct.unpack("<hh", d["VERTEXES"][i:i + 4]) for i in range(0, len(d["VERTEXES"]), 4)]
things = [struct.unpack("<hhhhh", d["THINGS"][i:i + 10]) for i in range(0, len(d["THINGS"]), 10)]
xs = [v[0] for v in verts]; ys = [v[1] for v in verts]
S = 0.25
W, H = int((max(xs) - min(xs)) * S) + 40, int((max(ys) - min(ys)) * S) + 40
img = Image.new("RGB", (W, H), (20, 20, 24)); dr = ImageDraw.Draw(img)
P = lambda x, y: ((x - min(xs)) * S + 20, (max(ys) - y) * S + 20)
for v1, v2, flags, sp, tag, fr, bk in lines:
    a, b = P(*verts[v1]), P(*verts[v2])
    if sp in w.EXIT: col = (255, 120, 0); wd = 3
    elif sp in w.DOOR or sp in w.KEY_DOOR: col = (80, 160, 255); wd = 3
    elif sp in w.LIFT: col = (200, 80, 255); wd = 2
    elif sp: col = (255, 255, 0); wd = 2
    elif bk == -1: col = (230, 230, 230); wd = 1
    elif flags & 1: col = (255, 60, 60); wd = 2
    else: col = (90, 90, 100); wd = 1
    dr.line([a, b], fill=col, width=wd)
for t in things:
    if t[3] == 1: dr.ellipse([P(t[0] - 24, t[1] + 24), P(t[0] + 24, t[1] - 24)], outline=(0, 255, 0), width=2)
    elif t[3] in (3004, 9, 3001): dr.ellipse([P(t[0] - 12, t[1] + 12), P(t[0] + 12, t[1] - 12)], outline=(255, 0, 0))
for gx in range(min(xs) - min(xs) % 512, max(xs), 512):
    dr.text(P(gx, max(ys)), str(gx), fill=(120, 120, 120))
for gy in range(min(ys) - min(ys) % 512, max(ys), 512):
    dr.text(P(min(xs), gy), str(gy), fill=(120, 120, 120))
img.save(out); print("wrote", out, img.size)
