"""Why does a map report no route to its exit? Developer-side, never on the flight path.

`survey.py` says which maps the grader cannot measure progress on. This says why: how much of the grid is
void, how much the walls take, how big the component holding the player start is, and whether the exit is
in it. Two shareware maps report no route today (E1M3 and E1M8) and this is the tool for anyone who wants
to fix that -- but read charter 2.5 first: the fix has to be a general improvement to the walkability
model, justified on its own terms, not a change made until those two particular maps go green.

    python research/grader/explain.py /root/doom/wads/doom1.wad E1M3
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from grader import wad

path, name = sys.argv[1], sys.argv[2]
level = wad.Level(path, name)
f = wad.DistanceField(level)
void = f._void(level)
n = f.w * f.h
print("grid %dx%d = %d cells" % (f.w, f.h, n))
print("void (outside the level)      %d" % sum(void))
print("blocked after wall dilation   %d" % sum(f.blocked))
print("exit seed cells               %d" % len(f.exit_cells))
print("reachable from the exit       %d" % sum(1 for v in f.dist if v != float("inf")))
sx, sy = level.start()
cx, cy = f.cell_of(sx, sy)
print("start %s -> cell %s  void=%d blocked=%d" % ((sx, sy), (cx, cy),
                                                   void[cy * f.w + cx], f.blocked[cy * f.w + cx]))
free = [i for i, b in enumerate(f.blocked) if not b]
print("walkable cells                %d" % len(free))
# how big is the walkable component the start sits in?
from collections import deque
seen = {(cx, cy)}
q = deque([(cx, cy)])
while q:
    ax, ay = q.popleft()
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = ax + dx, ay + dy
        if (0 <= nx < f.w and 0 <= ny < f.h and not f.blocked[ny * f.w + nx] and (nx, ny) not in seen):
            seen.add((nx, ny))
            q.append((nx, ny))
print("component containing the start %d cells" % len(seen))
ex = [f.cell_of(level.verts[l[0]][0], level.verts[l[0]][1]) for l in level.exit_lines()]
print("exit line cells %s -> in start component: %s" % (ex[:4], [c in seen for c in ex[:4]]))

from collections import Counter
print("specials:", sorted(Counter(l[3] for l in level.lines if l[3]).items()))
print("exit lines:", [(l[3], level.verts[l[0]], level.verts[l[1]]) for l in level.exit_lines()][:6])
print("teleport lines:", sum(1 for l in level.lines if l[3] in wad.TELEPORT))
