"""Switch and exit-sign pictures, read out of the IWAD the game is already running.

Charter 2.1 calls this game knowledge: what a switch looks like is true of Doom, not of any level, and
every player knows it before they start. The brief of 24 September says the same thing in the honesty
suite's terms -- texture, patch and sprite lumps are allowed; map lumps are not. This module reads only
the first kind, and `research/honesty.py` is what holds it to that.

It exists because the exit cannot be seen any other way. Probed at sixty-eight units from a level's exit
switch, looking all around, with `am_interlevelcolor` set and `am_showtriggerlines` both off and on: 458
wall pixels, 106 door pixels, **zero exit pixels**. ZDoom draws a one-sided line as plain wall before it
ever asks whether the line is an exit, and a Doom exit switch is a one-sided wall. The pilot has been
searching for something it cannot perceive, and the only honest way to find an exit switch is to
recognise the picture of one -- which is what a player does.

What it gives you:

    Textures(wad_path).switches()   -> [(name, HxWx3 uint8 RGB), ...]  every SW1*/SW2* texture
    Textures(wad_path).named("EXITSIGN")

Doom's picture format, briefly, because it is not obvious: a patch is a header (width, height, two
offsets) then one 32-bit file offset per column. A column is a run of "posts": a top row, a length, a
padding byte, `length` palette indices, another padding byte. A post starting at row 255 ends the column.
Everything not covered by a post is transparent, which matters -- a switch's plate is usually opaque and
the surround is not, and matching on the transparent part would match anything.
"""
import struct

SWITCH_PREFIXES = ("SW1", "SW2")
EXIT_SIGN = "EXITSIGN"
TRANSPARENT = -1


class Wad:
    """The lump directory, and nothing that knows what a level is."""

    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()
        ident, n, off = struct.unpack("<4sii", self.data[:12])
        if ident not in (b"IWAD", b"PWAD"):
            raise ValueError("%s is not a WAD" % path)
        self.index = {}
        self.order = []
        for i in range(n):
            p, size, name = struct.unpack("<ii8s", self.data[off + 16 * i: off + 16 * i + 16])
            name = name.rstrip(b"\0").decode("ascii", "replace")
            self.index.setdefault(name, (p, size))
            self.order.append(name)

    def lump(self, name):
        got = self.index.get(name)
        if not got:
            return None
        p, size = got
        return self.data[p:p + size]


def palette(wad):
    """The game's first palette, as 256 RGB triples."""
    pal = wad.lump("PLAYPAL")
    if not pal:
        return [(0, 0, 0)] * 256
    return [tuple(pal[i * 3:i * 3 + 3]) for i in range(256)]


def patch_names(wad):
    raw = wad.lump("PNAMES")
    if not raw:
        return []
    n = struct.unpack("<i", raw[:4])[0]
    return [raw[4 + 8 * i: 12 + 8 * i].rstrip(b"\0").decode("ascii", "replace").upper()
            for i in range(n)]


def read_patch(raw):
    """A Doom picture as a list of rows of palette indices, TRANSPARENT where nothing was drawn."""
    if not raw or len(raw) < 8:
        return None, 0, 0
    w, h, _lx, _ly = struct.unpack("<HHhh", raw[:8])
    if not (0 < w <= 4096 and 0 < h <= 4096) or len(raw) < 8 + 4 * w:
        return None, 0, 0
    offsets = struct.unpack("<%dI" % w, raw[8:8 + 4 * w])
    rows = [[TRANSPARENT] * w for _ in range(h)]
    for x, off in enumerate(offsets):
        i = off
        while 0 <= i < len(raw):
            top = raw[i]
            if top == 0xFF:
                break
            if i + 1 >= len(raw):
                break
            length = raw[i + 1]
            start = i + 3                      # one padding byte after the length
            for k in range(length):
                y = top + k
                if 0 <= y < h and start + k < len(raw):
                    rows[y][x] = raw[start + k]
            i = start + length + 1             # and one after the pixels
    return rows, w, h


def texture_table(wad):
    """Every composite texture in TEXTURE1/TEXTURE2: name -> (width, height, [(patch index, x, y)])."""
    out = {}
    names = patch_names(wad)
    for lump in ("TEXTURE1", "TEXTURE2"):
        raw = wad.lump(lump)
        if not raw:
            continue
        count = struct.unpack("<i", raw[:4])[0]
        offs = struct.unpack("<%di" % count, raw[4:4 + 4 * count])
        for off in offs:
            if not (0 <= off < len(raw) - 22):
                continue
            name = raw[off:off + 8].rstrip(b"\0").decode("ascii", "replace").upper()
            w, h, npatch = struct.unpack("<HH", raw[off + 12:off + 16])[0:2] + \
                (struct.unpack("<H", raw[off + 20:off + 22])[0],)
            patches = []
            for i in range(npatch):
                q = off + 22 + 10 * i
                if q + 10 > len(raw):
                    break
                px, py, pidx = struct.unpack("<hhH", raw[q:q + 6])
                patches.append((pidx, px, py))
            out[name] = (w, h, patches, names)
    return out


def compose(wad, entry, pal):
    """One composite texture as an HxWx3 RGB array plus an HxW opacity mask."""
    import numpy as np
    w, h, patches, names = entry
    idx = np.full((h, w), TRANSPARENT, np.int16)
    for pidx, px, py in patches:
        if not (0 <= pidx < len(names)):
            continue
        rows, pw, ph = read_patch(wad.lump(names[pidx]))
        if rows is None:
            continue
        for y in range(ph):
            ty = py + y
            if not (0 <= ty < h):
                continue
            row = rows[y]
            for x in range(pw):
                tx = px + x
                if 0 <= tx < w and row[x] != TRANSPARENT:
                    idx[ty, tx] = row[x]
    solid = idx >= 0
    lut = np.array(pal, np.uint8)
    rgb = np.zeros((h, w, 3), np.uint8)
    rgb[solid] = lut[idx[solid]]
    return rgb, solid


class Textures:
    """The pictures a player brings to a level, and nothing about the level."""

    def __init__(self, wad_path):
        self.wad = Wad(wad_path)
        self.pal = palette(self.wad)
        self.table = texture_table(self.wad)

    def named(self, name):
        entry = self.table.get(name.upper())
        return compose(self.wad, entry, self.pal) if entry else None

    def switches(self):
        """Every switch texture, on and off. A switch is a switch whichever way it is thrown."""
        out = []
        for name in sorted(self.table):
            if name.startswith(SWITCH_PREFIXES):
                got = self.named(name)
                if got is not None:
                    out.append((name, got[0], got[1]))
        return out

    def exit_signs(self):
        got = self.named(EXIT_SIGN)
        return [(EXIT_SIGN, got[0], got[1])] if got else []

    def summary(self):
        sw = self.switches()
        return {"textures": len(self.table), "switches": len(sw),
                "exit_signs": len(self.exit_signs()),
                "switch_names": [n for n, _r, _m in sw][:8]}
