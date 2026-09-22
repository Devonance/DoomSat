#!/bin/bash
PY=/root/doom/payload-venv/bin/python
cd /mnt/c/Users/Kevin/Genai/doom-mission/tools
$PY - <<'PY'
import wad_stats as w, math, struct
data, ls = w.lumps("/root/doom/wads/doom1.wad")
idx = [i for i, l in enumerate(ls) if l[0] == "E1M1"][0]
d = {ls[j][0]: data[ls[j][1]: ls[j][1] + ls[j][2]] for j in range(idx + 1, idx + 11)}
lines = [struct.unpack("<hhHhhhh", d["LINEDEFS"][i:i + 14]) for i in range(0, len(d["LINEDEFS"]), 14)]
verts = [struct.unpack("<hh", d["VERTEXES"][i:i + 4]) for i in range(0, len(d["VERTEXES"]), 4)]
sides = [struct.unpack("<hh8s8s8sh", d["SIDEDEFS"][i:i + 30]) for i in range(0, len(d["SIDEDEFS"]), 30)]
sectors = [struct.unpack("<hh8s8shhh", d["SECTORS"][i:i + 26]) for i in range(0, len(d["SECTORS"]), 26)]
things = [struct.unpack("<hhhhh", d["THINGS"][i:i + 10]) for i in range(0, len(d["THINGS"]), 10)]
px, py = 1132, -3632
for v1, v2, flags, sp, tag, fr, bk in lines:
    (x1, y1), (x2, y2) = verts[v1], verts[v2]
    dx, dy = x2 - x1, y2 - y1
    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy + 1e-9)))
    dist = math.hypot(x1 + t * dx - px, y1 + t * dy - py)
    if dist < 60:
        fs = sectors[sides[fr][5]] if fr != -1 else None
        bs = sectors[sides[bk][5]] if bk != -1 else None
        tex = lambda s: (sides[s][2].strip(b'\0'), sides[s][3].strip(b'\0'), sides[s][4].strip(b'\0')) if s != -1 else None
        print(f"d={dist:3.0f} ({x1},{y1})-({x2},{y2}) flags={flags} special={sp} tag={tag} front floor/ceil={fs[0]}/{fs[1]} back={bs[0] if bs else None}/{bs[1] if bs else None} front tex(up,low,mid)={tex(fr)} back tex={tex(bk)}")
print("things within 120:", [(t[3], t[0], t[1]) for t in things if math.hypot(t[0]-px, t[1]-py) < 120])
PY
