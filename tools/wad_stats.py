"""Developer-side level statistics (never used by the agent): what a level demands of a player.
Counts linedef specials by class: exits, doors, key doors, switches, lifts, teleports; plus map size.
"""
import struct, sys, os

DOOR = {1, 2, 3, 4, 16, 29, 31, 42, 46, 50, 61, 63, 75, 76, 86, 90, 103, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 175, 196}
KEY_DOOR = {26, 27, 28, 32, 33, 34, 99, 133, 134, 135, 136, 137}
EXIT = {11, 51, 52, 124, 197, 198}
LIFT = {10, 21, 62, 88, 120, 121, 122, 123}
TELE = {39, 97, 125, 126, 174, 195}
SWITCH_FLOOR = {18, 20, 23, 14, 15, 45, 55, 60, 64, 65, 66, 67, 68, 69, 70, 71, 101, 102, 131, 132, 140}
WALK_FLOOR = {5, 19, 30, 36, 37, 38, 56, 58, 59, 82, 83, 84, 91, 92, 93, 94, 95, 96, 98, 100, 119, 128, 129, 130}
KEY_THINGS = {5: "BlueCard", 6: "YellowCard", 13: "RedCard", 38: "RedSkull", 39: "YellowSkull", 40: "BlueSkull"}

def lumps(path):
    with open(path, "rb") as f:
        data = f.read()
    ident, n, off = struct.unpack("<4sii", data[:12])
    out = []
    for i in range(n):
        p, size, name = struct.unpack("<ii8s", data[off + 16 * i: off + 16 * i + 16])
        out.append((name.rstrip(b"\0").decode(), p, size))
    return data, out

def level(path, name):
    data, ls = lumps(path)
    idx = [i for i, l in enumerate(ls) if l[0] == name][0]
    d = {ls[j][0]: data[ls[j][1]: ls[j][1] + ls[j][2]] for j in range(idx + 1, min(idx + 11, len(ls)))}
    lines = [struct.unpack("<hhHhhhh", d["LINEDEFS"][i:i + 14]) for i in range(0, len(d["LINEDEFS"]), 14)]
    verts = [struct.unpack("<hh", d["VERTEXES"][i:i + 4]) for i in range(0, len(d["VERTEXES"]), 4)]
    things = [struct.unpack("<hhhhh", d["THINGS"][i:i + 10]) for i in range(0, len(d["THINGS"]), 10)]
    return lines, verts, things

def report(path, name):
    lines, verts, things = level(path, name)
    xs = [v[0] for v in verts]; ys = [v[1] for v in verts]
    cls = {"door": 0, "key_door": 0, "exit_switch": 0, "exit_walk": 0, "lift": 0, "teleport": 0, "switch_floor": 0, "walk_floor": 0, "other": 0}
    ex = []
    for v1, v2, flags, special, tag, fr, bk in lines:
        if special == 0: continue
        if special in DOOR: cls["door"] += 1
        elif special in KEY_DOOR: cls["key_door"] += 1
        elif special in EXIT:
            if special in (11, 51, 197): cls["exit_switch"] += 1
            else: cls["exit_walk"] += 1
            ex.append((special, verts[v1], verts[v2]))
        elif special in LIFT: cls["lift"] += 1
        elif special in TELE: cls["teleport"] += 1
        elif special in SWITCH_FLOOR: cls["switch_floor"] += 1
        elif special in WALK_FLOOR: cls["walk_floor"] += 1
        else: cls["other"] += 1
    keys = [KEY_THINGS[t[3]] for t in things if t[3] in KEY_THINGS]
    start = [(t[0], t[1], t[2]) for t in things if t[3] == 1]
    monsters = sum(1 for t in things if t[3] in (3004, 9, 3001, 3002, 58, 65, 3005, 69, 3003, 3006, 66, 68, 67, 71, 64, 84, 7, 16))
    print(f"{os.path.basename(path)} {name}: {len(lines)} lines, bbox x {min(xs)}..{max(xs)} y {min(ys)}..{max(ys)}, start {start}")
    print(f"   specials {cls}, keys {keys}, exits {ex}, monster things {monsters}")
    if "--lines" in sys.argv:
        for v1, v2, flags, special, tag, fr, bk in lines:
            if special in KEY_DOOR or special in DOOR:
                print(f"   {'key_door' if special in KEY_DOOR else 'door'} special={special} {verts[v1]}-{verts[v2]}")
        print("   keys at", [(KEY_THINGS[t[3]], t[0], t[1]) for t in things if t[3] in KEY_THINGS])

if __name__ == "__main__":
    path = sys.argv[1]
    for name in [a for a in sys.argv[2:] if not a.startswith("--")]:
        report(path, name)
