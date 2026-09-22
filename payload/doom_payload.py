"""Doom payload: the "instrument" the flight software carries.

Runs Doom (via ViZDoom) at 35 Hz, keeps the last uplinked controls held, and serves an observation
summary plus JPEG frames (and the map it builds) to the F Prime Doom component over a local TCP socket.

Everything the payload reports comes from what a player could see, never from the level file:
  - the in-game automap in the mode that shows only lines the player has already seen. ZDoom draws
    those lines by category (wall, floor step, ceiling change such as a door, locked door in the
    colour of its key, exit line once looked at); the payload only recolours them so code can read
    the categories off the pixels,
  - the depth buffer (a range camera): free space ahead, and the map cells swept clean of unknown,
  - the labels buffer (an object detector): visible enemies, pickups and keys, remembered once seen,
  - the HUD variables: health, armor, ammo, position and heading (odometry).

There is no route planner. The payload reports, for the four directions around the player, how far
the way is open and how much of that ground has already been walked, what is at arm's length ahead
(a wall, a door, the exit switch, a locked door, something the map does not show), where an exit
line or a key or a pickup was seen, and whether the player is stuck. The ground decides where to go.

Protocol (big-endian; the payload is the server on 127.0.0.1:4242):
  payload -> flight   'D' kind:u8 length:u16 body
     kind 1 STATUS  fixed struct (see STATUS_FMT)
     kind 2 FRAME   seq:u32 jpeg bytes (seq with the high bit set: the map, a PNG)
  flight -> payload   'D' kind:u8 length:u16 body
     kind 0x10 CONTROL      move:i8 strafe:i8 turn:f32 (degrees to turn, +left) fire:u8 use:u8 weapon:u8
     kind 0x11 SET_GOAL     goal:u8
     kind 0x12 RESET
     kind 0x13 FRAME_RATE   hz:u8 quality:u8
     kind 0x14 EXPLORE_HINT bearing:i16 (degrees, positive left) ttl:u8 (seconds)
"""
import argparse
import io
import math
import os
import re
import socket
import struct
import time
from collections import deque

import numpy as np
import vizdoom as vzd
from PIL import Image, ImageDraw

TICRATE = 35
STATUS_FMT = "!hhhhBBHfffBfHHHHHHHHBBBBBHfHfHHHHfffBBBIHBBHBBBhHHHHBBBBBBBBBBBB"   # 120 bytes, 64 fields (see pack_status)
GOALS = ["EXPLORE", "KILL_ENEMY", "STOCK_AMMO", "RESTORE_HEALTH", "ADD_ARMOR", "UPGRADE_WEAPON", "SCOUT", "HOLD"]
AHEAD_KINDS = ["nothing", "wall", "door", "exit", "locked", "barrier", "thing"]
ENEMIES = {"DoomImp", "Zombieman", "ShotgunGuy", "Demon", "Spectre", "ChaingunGuy", "Cacodemon", "HellKnight",
           "BaronOfHell", "LostSoul", "Revenant", "Arachnotron", "Fatso", "PainElemental", "Archvile", "WolfensteinSS"}
ITEM_KIND = {"Stimpack": "health", "Medikit": "health", "HealthBonus": "health", "Soulsphere": "health",
             "Clip": "ammo", "ClipBox": "ammo", "Shell": "ammo", "ShellBox": "ammo",
             "GreenArmor": "armor", "BlueArmor": "armor", "ArmorBonus": "armor",
             "Shotgun": "weapon", "Chaingun": "weapon", "Chainsaw": "weapon",
             "RedCard": "key", "BlueCard": "key", "YellowCard": "key", "RedSkull": "key", "BlueSkull": "key", "YellowSkull": "key"}
KEY_COLOUR = {"RedCard": "red", "RedSkull": "red", "BlueCard": "blue", "BlueSkull": "blue", "YellowCard": "yellow", "YellowSkull": "yellow"}
KEY_BIT = {"red": 1, "blue": 2, "yellow": 4}
SOLID_THINGS = {"ExplosiveBarrel", "BurningBarrel", "Column", "TechPillar", "ShortGreenColumn", "TallGreenColumn", "ShortRedColumn",
                "TallRedColumn", "SkullColumn", "HeartColumn", "EvilEye", "FloatingSkull", "TorchTree", "BlueTorch", "GreenTorch",
                "RedTorch", "ShortBlueTorch", "ShortGreenTorch", "ShortRedTorch", "Stalagtite", "Stalagmite", "BigTree", "TechLamp",
                "TechLamp2", "Candelabra", "Meat2", "Meat3", "Meat4", "Meat5", "HangNoGuts", "HangBNoBrain", "HangTLookingDown",
                "HangTSkull", "HangTLookingUp", "HangTNoBrain"}
BUTTONS = [vzd.Button.MOVE_FORWARD_BACKWARD_DELTA, vzd.Button.MOVE_LEFT_RIGHT_DELTA, vzd.Button.TURN_LEFT_RIGHT_DELTA,
           vzd.Button.ATTACK, vzd.Button.USE, vzd.Button.SELECT_WEAPON2, vzd.Button.SELECT_WEAPON3]
GRID = 32              # map cell for "walked here" memory (map units)
FOV = 90.0             # ViZDoom default horizontal field of view
DEPTH_UNITS = 7.16     # map units per depth-buffer step; the buffer holds perpendicular (z) distance (depth_calib_probe*.py)
DEPTH_FAR = 56         # depth steps beyond which the range camera is not trusted (~400 units)
SENSE_EVERY = 7        # tics between automap stamps and the slower sensing (5 Hz)
UPLINK_TIMEOUT_S = 3.0  # no CONTROL for this long -> release everything (safe mode)
DOOR_TRIES = 10        # use presses at a door before it counts as "does not open for me now"
DOOR_RETRY_S = 120.0   # a door that did not open is treated as a wall for this long
RAY_MAX = 400          # how far the map rays look (units)

# ---- the automap as a sensor: ViZDoom renders it at screen size, centred on the player, viz_am_scale 2.5 = 0.5 px/unit
AM_W, AM_H, AM_SCALE, AM_CX, AM_CY = 640, 480, 0.5, 320, 240
WPX = 4                # world raster: map units per pixel
WORLD_HALF = 6144      # world raster covers +-6144 units around the level start
NONE, STEP, DOOR, LOCK_RED, LOCK_BLUE, LOCK_YELLOW, LOCKED, EXIT, WALL, BARRIER = range(10)   # merge priority: later wins
BARRIER_S = 45.0
CLASS_RGB = {WALL: (255, 255, 255), STEP: (83, 175, 71), DOOR: (115, 115, 255), LOCK_RED: (255, 0, 0), LOCK_BLUE: (0, 0, 255),
             LOCK_YELLOW: (255, 255, 0), LOCKED: (255, 123, 123), EXIT: (255, 127, 27)}
RENDER_RGB = {**CLASS_RGB, BARRIER: (255, 160, 90)}
ARROW_RGB = (255, 0, 255)
LOCK_KEY = {LOCK_RED: "red", LOCK_BLUE: "blue", LOCK_YELLOW: "yellow"}
# ZDoom's automap categories, given colours code can tell apart (the categories themselves are the engine's defaults:
# am_showkeys on, exit lines coloured, trigger lines off). The palette maps "00 ff 00" to (83,175,71) etc.
AM_CVARS = ['am_backcolor "00 00 00"', 'am_wallcolor "ff ff ff"', 'am_fdwallcolor "00 ff 00"', 'am_cdwallcolor "80 80 ff"',
            'am_lockedcolor "ff 80 80"', 'am_interlevelcolor "ff 80 00"', 'am_intralevelcolor "00 00 00"', 'am_yourcolor "ff 00 ff"',
            'am_tswallcolor "00 00 00"', 'am_secretwallcolor "ff ff ff"', 'am_secretsectorcolor "ff ff ff"', 'am_efwallcolor "ff ff ff"',
            'am_notseencolor "00 00 00"', 'am_gridcolor "00 00 00"', 'am_xhaircolor "00 00 00"', 'am_showgrid 0',
            'am_showtriggerlines 0', 'am_showkeys 1']
_VECS = np.array([np.array(c, np.float32) / np.linalg.norm(c) for c in list(CLASS_RGB.values()) + [ARROW_RGB]])
_VEC_CLASS = np.array(list(CLASS_RGB.keys()) + [NONE], np.uint8)


def bearing_deg(x, y, angle, tx, ty):
    """Signed bearing to (tx, ty) relative to heading `angle`; positive means left."""
    return (math.degrees(math.atan2(ty - y, tx - x)) - angle + 180) % 360 - 180


def classify(am):
    """Automap RGB -> class per pixel. Lines are anti-aliased, so classify by colour direction, any brightness."""
    bright = am.max(axis=2)
    bright[AM_CY - 4:AM_CY + 5, AM_CX - 4:AM_CX + 5] = 0   # the player marker is not a line
    cls = np.zeros(bright.shape, np.uint8)
    ys, xs = np.nonzero(bright >= 40)
    if len(xs):
        p = am[ys, xs].astype(np.float32)
        unit = p / (np.linalg.norm(p, axis=1, keepdims=True) + 1e-6)
        dots = unit @ _VECS.T
        best = dots.argmax(axis=1)
        c = _VEC_CLASS[best]
        c[dots.max(axis=1) < 0.965] = NONE
        cls[ys, xs] = c
    return cls


def next_map(name):
    m = re.fullmatch(r"E(\d)M(\d)", name)
    if m:
        return f"E{m.group(1)}M{int(m.group(2)) + 1}"
    m = re.fullmatch(r"MAP(\d\d)", name)
    return f"MAP{int(m.group(1)) + 1:02d}" if m else name


class Explorer:
    """The map the payload builds for itself for one level attempt: the in-game automap (lines the player has
    seen) stamped into a world raster, floor swept by the range camera, where the player has walked, what it
    remembers seeing (items, keys) and what it learned by bumping into (barriers)."""

    def __init__(self, x0, y0):
        self.ox, self.oy = x0 - WORLD_HALF, y0 + WORLD_HALF   # raster origin: top-left corner in map units
        self.n = 2 * WORLD_HALF // WPX
        self.raster = np.zeros((self.n, self.n), np.uint8)
        self.barrier_t = np.full((self.n, self.n), -1e9, np.float32)   # when a barrier was confirmed there
        self.ux = (np.arange(AM_W) - AM_CX) / AM_SCALE          # automap column -> x offset from the player (units)
        self.vy = -(np.arange(AM_H) - AM_CY) / AM_SCALE         # automap row -> y offset (map y is up)
        self.free = set()
        self.visited = {}      # cell -> tics the player has stood in it (the walk, remembered)
        self.items = {}        # (kind, rounded x, rounded y) -> {"kind", "name", "x", "y", "seen"}
        self.keys = set()      # colours of keys picked up
        self.hint = None       # (absolute bearing, expiry)
        self.stamps = 0

    @staticmethod
    def cell(x, y):
        return int(math.floor(x / GRID)), int(math.floor(y / GRID))

    def wpx(self, x, y):
        return int((x - self.ox) / WPX), int((self.oy - y) / WPX)

    # ------------------------------------------------------------------ sensing
    def stamp(self, am, px, py):
        """Write the automap window (everything mapped within it) into the world raster, replacing the region."""
        cls = classify(am)
        ys, xs = np.nonzero(cls)
        ix0, iy0 = self.wpx(px + self.ux[0], py + self.vy[0])
        ix1, iy1 = self.wpx(px + self.ux[-1], py + self.vy[-1])
        a, b, c, d = max(0, ix0 + 2), min(self.n, ix1 - 1), max(0, iy0 + 2), min(self.n, iy1 - 1)
        cx_, cy_ = self.wpx(px, py)
        under = self.raster[cy_ - 5:cy_ + 6, cx_ - 5:cx_ + 6].copy()   # the arrow hides the lines beneath it
        if a < b and c < d:
            self.raster[c:d, a:b] = 0
        if len(xs):
            ix = ((px + self.ux[xs] - self.ox) / WPX).astype(np.intp)
            iy = ((self.oy - (py + self.vy[ys])) / WPX).astype(np.intp)
            ok = (ix >= 0) & (ix < self.n) & (iy >= 0) & (iy < self.n)
            np.maximum.at(self.raster, (iy[ok], ix[ok]), cls[ys[ok], xs[ok]])
        blk = self.raster[cy_ - 5:cy_ + 6, cx_ - 5:cx_ + 6]
        if blk.shape == under.shape:
            np.maximum(blk, under, out=blk)
        self.stamps += 1

    def sweep(self, x, y, angle, depth_row):
        """One range-camera sweep: every cell a ray passes through (farthest surface in the eye-level band) is
        free floor the player has seen."""
        here = self.cell(x, y)
        self.free.add(here)
        self.visited[here] = self.visited.get(here, 0) + 1
        w = len(depth_row)
        for col in range(0, w, 16):
            rel = math.degrees(math.atan((0.5 - col / (w - 1)) * 2 * math.tan(math.radians(FOV / 2))))
            dist = min(int(depth_row[col]), DEPTH_FAR) * DEPTH_UNITS / math.cos(math.radians(rel))
            a = math.radians(angle + rel)
            ca, sa = math.cos(a), math.sin(a)
            r = GRID / 2
            while r < dist - GRID / 2:
                self.free.add(self.cell(x + r * ca, y + r * sa))
                r += GRID / 2

    def remember_items(self, x, y, labels):
        for lab in labels:
            kind = ITEM_KIND.get(lab.object_name)
            if kind:
                key = (kind, round(lab.object_position_x / 16), round(lab.object_position_y / 16))
                self.items[key] = {"kind": kind, "name": lab.object_name, "x": lab.object_position_x,
                                   "y": lab.object_position_y, "seen": time.time()}
        for key in [k for k, v in self.items.items() if math.hypot(v["x"] - x, v["y"] - y) < 40]:
            if self.items[key]["kind"] == "key":
                self.keys.add(KEY_COLOUR.get(self.items[key]["name"], "red"))
                self.barrier_t[:] = np.minimum(self.barrier_t, time.time() - 1e6)   # locked doors deserve a fresh try
                print(f"[payload] picked up the {self.items[key]['name']}", flush=True)
            del self.items[key]  # walked over it: picked up (or not a pickup we can take)

    def nearest_item(self, x, y, kind):
        best = None
        for v in self.items.values():
            if v["kind"] == kind:
                d = math.hypot(v["x"] - x, v["y"] - y)
                if best is None or d < best[0]:
                    best = (d, v)
        return best

    def mark_barrier(self, x, y, heading, seconds, dist=24):
        """Something the map does not show blocks the way `heading` from (x, y): mark it, three marks wide."""
        dist = max(24, dist)
        a = math.radians(heading)
        bx, by = x + dist * math.cos(a), y + dist * math.sin(a)
        lx, ly = -math.sin(a), math.cos(a)
        until = time.time() + seconds - BARRIER_S
        for k in (-12, 0, 12):
            ix, iy = self.wpx(bx + k * lx, by + k * ly)
            if 1 <= ix < self.n - 1 and 1 <= iy < self.n - 1:
                self.barrier_t[iy - 1:iy + 2, ix - 1:ix + 2] = until

    def klass(self, ix, iy, now, r=1):
        """Class of the raster around a pixel ((2r+1)^2 window), barriers included."""
        if not (r <= ix < self.n - r and r <= iy < self.n - r):
            return NONE
        c = int(self.raster[iy - r:iy + r + 1, ix - r:ix + r + 1].max())
        if (now - self.barrier_t[iy - r:iy + r + 1, ix - r:ix + r + 1]).min() < BARRIER_S:
            return BARRIER
        return c

    def probe(self, x, y, heading, dist, now):
        """What the map says about the surface the camera sees at `dist` along `heading`: look a little short
        of and beyond the hit (the range is quantised) and report the most telling category found."""
        a = math.radians(heading)
        found = set()
        for r in range(max(4, int(dist) - 14), int(dist) + 22, 4):
            c = self.klass(*self.wpx(x + r * math.cos(a), y + r * math.sin(a)), now, r=2)
            if c != NONE:
                found.add(c)
        for c in (EXIT, DOOR, LOCK_RED, LOCK_BLUE, LOCK_YELLOW, LOCKED, BARRIER, WALL, STEP):
            if c in found:
                return c
        return NONE

    def sector(self, x, y, heading, now):
        """A direction judged over three rays: (space, novelty). Unseen ground on the way beats everything seen:
        space is then how far the seen floor goes (at least 64) and novelty is 255, the word for unexplored."""
        best = None
        for off in (-15, 0, 15):
            r = self.ray(x, y, heading + off, now)
            if r[4] and r[4] < r[0]:
                cand = (max(64, r[4]), r[1], r[2], r[3], r[4]), 255
                score = 1000 + r[4]
            else:
                nov = self.novelty(x, y, heading + off, r[0])
                cand = (r, nov)
                score = r[0] + 2 * nov
            if best is None or score > best[0]:
                best = (score, cand)
        return best[1]

    def ray(self, x, y, heading, now, max_units=RAY_MAX):
        """Walk the map from the player in one direction: (distance to the first wall-like thing or max_units,
        distance to the first door on the way or 0, distance to an exit line or 0, class that stopped the ray,
        distance to the first ground never seen or 0)."""
        a = math.radians(heading)
        ca, sa = math.cos(a), math.sin(a)
        door, unseen = 0, 0
        for r in range(20, max_units + 1, 4):   # the player's own body is free space
            px_, py_ = x + r * ca, y + r * sa
            ix, iy = self.wpx(px_, py_)
            c = self.klass(ix, iy, now)
            if c in (WALL, BARRIER, LOCKED):
                return r, door, 0, c, unseen
            if not unseen and r % 16 == 0 and r >= 32 and self.cell(px_, py_) not in self.free:
                unseen = r
            if c in LOCK_KEY:
                if LOCK_KEY[c] in self.keys:
                    door = door or r
                else:
                    return r, door, 0, c, unseen
            elif c == EXIT:
                return r, door, r, c, unseen
            elif c == DOOR and not door:
                door = r
        return max_units, door, 0, NONE, unseen

    def novelty(self, x, y, heading, dist):
        """How much of the ground that way has not been walked: 0..100 (100 = all new), over cells up to `dist`."""
        a = math.radians(heading)
        if dist < 48:
            return 0   # a wall at arm's length: nothing to walk there
        cells, new = 0, 0
        for r in range(32, int(min(dist, 288)) + 1, 32):
            c = self.cell(x + r * math.cos(a), y + r * math.sin(a))
            cells += 1
            if self.visited.get(c, 0) == 0:
                new += 1
        return int(100 * new / cells) if cells else 100

    def nearest_exit(self, x, y, now):
        """Nearest exit-line pixel seen within 600 units, or None."""
        ix, iy = self.wpx(x, y)
        r = 150
        win = self.raster[max(0, iy - r):iy + r, max(0, ix - r):ix + r]
        ys, xs = np.nonzero(win == EXIT)
        if not len(xs):
            return None
        ex = self.ox + (max(0, ix - r) + xs) * WPX
        ey = self.oy - (max(0, iy - r) + ys) * WPX
        d = np.hypot(ex - x, ey - y)
        k = int(d.argmin())
        return float(ex[k]), float(ey[k]), float(d[k])

    def render(self, x, y, angle):
        """Draw the self-built map (for the ground display and the map product)."""
        if not self.free:
            return None
        xs = [c[0] for c in self.free]
        ys = [c[1] for c in self.free]
        cx0, cx1, cy0, cy1 = min(xs) - 2, max(xs) + 3, min(ys) - 2, max(ys) + 3
        W, H = cx1 - cx0, cy1 - cy0
        S = 5
        img = Image.new("RGB", (W * S, H * S), (24, 24, 28))
        d = ImageDraw.Draw(img)
        px = lambda c: ((c[0] - cx0) * S, (cy1 - 1 - c[1]) * S)   # map y up
        for c in self.free:
            a, b = px(c)
            d.rectangle((a, b, a + S - 1, b + S - 1), fill=(64, 64, 72))
        for c, n in self.visited.items():
            a, b = px(c)
            d.rectangle((a + 1, b + 1, a + S - 2, b + S - 2), fill=(40, min(255, 90 + n), 60))
        ix0, iy0 = self.wpx(cx0 * GRID, cy1 * GRID)
        ix1, iy1 = self.wpx(cx1 * GRID, cy0 * GRID)
        sub = self.raster[max(0, iy0):iy1, max(0, ix0):ix1]
        now = time.time()
        bar = (now - self.barrier_t[max(0, iy0):iy1, max(0, ix0):ix1]) < BARRIER_S
        ys_, xs_ = np.nonzero((sub > 0) | bar)
        for u, v in zip(xs_, ys_):
            cls = BARRIER if bar[v, u] else int(sub[v, u])
            wx, wy = self.ox + (max(0, ix0) + u) * WPX, self.oy - (max(0, iy0) + v) * WPX
            d.point(((wx / GRID - cx0) * S, (cy1 - wy / GRID) * S), fill=RENDER_RGB.get(cls, (200, 200, 200)))
        a, b = (x / GRID - cx0) * S, (cy1 - y / GRID) * S
        d.ellipse((a - 4, b - 4, a + 4, b + 4), fill=(255, 60, 60))
        d.line((a, b, a + 12 * math.cos(math.radians(angle)), b - 12 * math.sin(math.radians(angle))), fill=(255, 60, 60), width=2)
        return img


class Payload:
    def __init__(self, args):
        self.args = args
        self.wad = self._find_wad(args.wad)
        self.map = args.map
        self.game = self._make_game()
        self.explorer = None
        self.explorer_map = None
        self.goal = "EXPLORE"
        self.control = dict(move=0, strafe=0, turn=0.0, fire=0, use=0, weapon=0)
        self.last_control_time = 0.0
        self.frame_hz, self.quality = args.fps, args.quality
        self.frame_seq = 0
        self.episode = 0
        self.level = 0
        self.positions = deque(maxlen=35)
        self.motions = deque(maxlen=35)
        self.stuck = False
        self.cmd_count = 0
        self.last_obs = None
        self.turn_remaining = 0.0
        self.carry = None
        self.map_png_bytes, self.map_seq = None, 0
        self.sense = None            # the slower sensing (rays, novelty, exit) refreshed every SENSE_EVERY tics
        self.door_presses, self.door_at = 0, None
        self.use_ok = False
        self.new_episode()

    @staticmethod
    def _find_wad(name):
        for p in (name, os.path.join("/root/doom/wads", name), os.path.join(os.path.dirname(vzd.__file__), name)):
            if os.path.isfile(p):
                return p
        raise SystemExit(f"WAD not found: {name}")

    def _make_game(self):
        g = vzd.DoomGame()
        g.set_doom_game_path(self.wad)
        g.set_doom_map(self.map)
        g.set_doom_skill(self.args.skill)
        g.set_available_buttons(BUTTONS)
        g.set_button_max_value(vzd.Button.TURN_LEFT_RIGHT_DELTA, 6)
        g.set_button_max_value(vzd.Button.MOVE_FORWARD_BACKWARD_DELTA, 14)
        g.set_button_max_value(vzd.Button.MOVE_LEFT_RIGHT_DELTA, 14)
        g.set_window_visible(False)
        g.set_screen_resolution(vzd.ScreenResolution.RES_640X480)
        g.set_screen_format(vzd.ScreenFormat.RGB24)
        g.set_render_hud(True)
        g.set_render_crosshair(False)   # it is drawn into the depth buffer too (depth 0 at the centre)
        g.set_depth_buffer_enabled(True)
        g.set_labels_buffer_enabled(True)
        g.set_automap_buffer_enabled(True)
        g.set_automap_mode(vzd.AutomapMode.NORMAL)      # only what the player has seen
        g.set_automap_rotate(False)
        g.set_automap_render_textures(False)
        g.set_sound_enabled(False)
        g.set_episode_timeout(0)
        g.set_seed(self.args.seed)
        g.set_mode(vzd.Mode.PLAYER)
        g.add_game_args("+am_colorset 0 +am_drawmapback 0 +viz_am_scale 2.5")
        g.init()
        for c in AM_CVARS:
            g.send_game_command(c)
        return g

    def new_episode(self):
        """A fresh attempt: the level restarts; the map of this level is kept (weapons carry over between levels)."""
        self.game.set_doom_map(self.map)
        self.game.new_episode()
        loadout = self.carry or {"shotgun": True, "shells": 4, "bullets": 30}
        cmds = ["take Shell 999", "take Clip 999", f"give Shell {loadout['shells']}", f"give Clip {loadout['bullets']}"]
        if loadout["shotgun"]:
            cmds.insert(0, "give shotgun")
        for cmd in cmds:
            self.game.send_game_command(cmd)
        self.game.make_action([0] * len(BUTTONS), 1)
        self.episode += 1
        if self.explorer is None or self.explorer_map != self.map:
            # a new level: a new map. Another attempt at the same level keeps the map (a player remembers the layout);
            # the game itself restarts from the beginning with everything in it.
            self.level += 1
            self.explorer = Explorer(self.var("POSITION_X"), self.var("POSITION_Y"))
        else:
            self.explorer.items.clear()
            self.explorer.hint = None
        self.explorer_map = self.map
        self.positions.clear()
        self.motions.clear()
        self.goal = "EXPLORE"
        self.control = dict(move=0, strafe=0, turn=0.0, fire=0, use=0, weapon=0)
        self.sense, self.door_presses, self.door_at = None, 0, None
        print(f"[payload] episode {self.episode} started on {self.map} (level {self.level})", flush=True)

    def level_finished(self):
        """Carry weapons and ammunition into the next map, as the game does (keys stay behind)."""
        self.carry = {"shotgun": self.var("WEAPON3") > 0, "shells": int(self.var("AMMO3")), "bullets": int(self.var("AMMO2"))}
        self.map = next_map(self.map)
        self.new_episode()

    # ------------------------------------------------------------------ observation
    def var(self, name):
        return float(self.game.get_game_variable(getattr(vzd.GameVariable, name)))

    @staticmethod
    def band_clearance(depth_row, lo_deg, hi_deg):
        """Nearest range (map units) in a bearing band of the range camera; positive bearings are left."""
        w = len(depth_row)
        best = None
        for col in range(0, w, 8):
            rel = math.degrees(math.atan((0.5 - col / (w - 1)) * 2 * math.tan(math.radians(FOV / 2))))
            if lo_deg <= rel <= hi_deg:
                dist = min(int(depth_row[col]), DEPTH_FAR) * DEPTH_UNITS / math.cos(math.radians(rel))
                best = dist if best is None else min(best, dist)
        return 2000 if best is None else int(best)

    def slow_sense(self, x, y, angle, now, clear_fwd, enemies):
        """Map rays, novelty, what is ahead, exit position: refreshed every few tics."""
        ex = self.explorer
        ix, iy = ex.wpx(x, y)
        ex.barrier_t[iy - 3:iy + 4, ix - 3:ix + 4] = -1e9   # the player stands here: nothing solid within 12 units
        dirs = (("fwd", 0), ("al", 45), ("left", 90), ("bl", 135), ("back", 180), ("br", -135), ("right", -90), ("ar", -45))
        rays, nov = {}, {}
        rays["fwd"], nov["fwd"] = ex.sector(x, y, angle, now)
        for name, off in dirs[1:]:
            rays[name], nov[name] = ex.sector(x, y, angle + off, now)
        # A door on the way used to overwrite the novelty value, so the ground could not tell whether a door
        # led anywhere new. Doors now ride their own channel: distance / 8 units, 0 = no door (issue 9).
        doors = {name: (max(1, min(254, int(rays[name][1]) // 8)) if rays[name][1] and rays[name][1] < 440 else 0)
                 for name in rays}
        # what is at arm's length ahead, from the camera's range and the map's category there
        ahead_kind, ahead_dist = "nothing", 0
        if clear_fwd < 120:
            ahead_dist = clear_fwd
            c = ex.probe(x, y, angle, clear_fwd, now)
            if enemies and abs(enemies[0][1]) < 15 and abs(enemies[0][2] - clear_fwd) < 40:
                ahead_kind = "thing"
            elif c == EXIT:
                ahead_kind = "exit"
            elif c == DOOR or (c in LOCK_KEY and LOCK_KEY[c] in ex.keys):
                ahead_kind = "door"
            elif c in LOCK_KEY or c == LOCKED:
                ahead_kind = "locked"
            elif c == WALL:
                ahead_kind = "wall"
            elif c == BARRIER:
                ahead_kind = "barrier"
            elif c == STEP:
                ahead_kind = "wall"       # a step the camera sees as a wall is a ledge
            elif clear_fwd < 70:
                ahead_kind = "barrier"    # the map shows nothing here, the eyes do (bars, a fake door)
            else:
                ahead_kind, ahead_dist = "nothing", 0   # too far to be sure; walk up and look
        # a door on the forward ray counts as "door ahead" when close, even if the camera looks past its frame
        if ahead_kind == "nothing" and rays["fwd"][1] and rays["fwd"][1] < 100:
            ahead_kind, ahead_dist = "door", rays["fwd"][1]
        return dict(rays=rays, nov=nov, doors=doors, ahead_kind=ahead_kind, ahead_dist=ahead_dist,
                    exit_seen=ex.nearest_exit(x, y, now))

    def observe(self, state):
        x, y, angle = self.var("POSITION_X"), self.var("POSITION_Y"), self.var("ANGLE")
        ex = self.explorer
        now = time.time()
        depth = np.where(state.depth_buffer == 0, 255, state.depth_buffer)   # 0 is the sky (nothing there): far
        band = depth[depth.shape[0] * 5 // 12: depth.shape[0] * 7 // 12]
        depth_row = band.max(axis=0)                                            # farthest surface: sees past bars and sprites
        near_row = depth[196 * depth.shape[0] // 480: 222 * depth.shape[0] // 480].min(axis=0)   # nearest surface at eye level
        slow = state.tic % 3 == 0 or self.sense is None
        if state.tic % SENSE_EVERY == 0 or ex.stamps == 0:
            ex.stamp(state.automap_buffer, x, y)
        ex.sweep(x, y, angle, depth_row)
        ex.remember_items(x, y, state.labels)
        for lab in state.labels:
            if lab.object_name in SOLID_THINGS and 24 < math.hypot(lab.object_position_x - x, lab.object_position_y - y) < 400:
                ix, iy = ex.wpx(lab.object_position_x, lab.object_position_y)
                if 1 <= ix < ex.n - 1 and 1 <= iy < ex.n - 1:
                    ex.barrier_t[iy - 1:iy + 2, ix - 1:ix + 2] = now   # a barrel or pillar: an obstacle while remembered
        enemies = []
        for lab in state.labels:
            if lab.object_name in ENEMIES:
                b = bearing_deg(x, y, angle, lab.object_position_x, lab.object_position_y)
                enemies.append((abs(b), b, math.hypot(lab.object_position_x - x, lab.object_position_y - y), lab))
        enemies.sort(key=lambda e: e[0])
        clear_fwd = self.band_clearance(near_row, -12, 12)
        clear_fl = self.band_clearance(near_row, 20, 45)
        clear_fr = self.band_clearance(near_row, -45, -20)
        if slow:
            self.sense = self.slow_sense(x, y, angle, now, clear_fwd, enemies)
        s = self.sense
        # stuck: a motion command has been held for a while and the player did not get anywhere
        self.positions.append((x, y))
        self.motions.append((self.control["move"], self.control["strafe"]))
        pushing = len(self.motions) == self.motions.maxlen and sum(1 for m in self.motions if m != (0, 0)) >= 8
        was_stuck = self.stuck
        self.stuck = bool(pushing and math.hypot(x - self.positions[0][0], y - self.positions[0][1]) < 12)
        if self.stuck and not was_stuck:
            mv, st = self.control["move"], self.control["strafe"]
            push = math.degrees(math.atan2(-st, mv)) if (mv or st) else 0.0
            if s["ahead_kind"] not in ("door", "exit") or abs(push) > 45:
                ex.mark_barrier(x, y, angle + push, 3600.0)
                print(f"[payload] stuck pushing at ({x:.0f},{y:.0f}) toward {(angle + push) % 360:.0f} deg: barrier remembered", flush=True)
                self.sense = None
        # doors: presses are counted while something usable is at arm's length; a door that never opens becomes a wall for a while
        usable = s["ahead_kind"] in ("door", "exit") and s["ahead_dist"] <= 80
        self.use_ok = usable
        if usable:
            at = (round(x / 32), round(y / 32), round(angle / 45))
            if at != self.door_at:
                self.door_at, self.door_presses = at, 0
            if self.door_presses >= DOOR_TRIES and s["ahead_kind"] == "door":
                ex.mark_barrier(x, y, angle, DOOR_RETRY_S, dist=s["ahead_dist"] + 6)
                print(f"[payload] door at ({x:.0f},{y:.0f}) did not open after {self.door_presses} presses; a wall for a while", flush=True)
                self.door_presses, self.sense = 0, None
        elif clear_fwd > 120:
            self.door_presses = 0
        if state.tic % 35 == 0:
            img = ex.render(x, y, angle)
            if img is not None:
                if state.tic % 175 == 0:
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    self.map_png_bytes = buf.getvalue()
                if self.args.map_png:
                    try:
                        img.save(self.args.map_png + ".tmp.png")
                        os.replace(self.args.map_png + ".tmp.png", self.args.map_png)
                    except OSError:
                        pass
        weapon = {1: 0, 2: 1, 3: 2}.get(int(self.var("SELECTED_WEAPON")), 3)
        item = lambda k: ex.nearest_item(x, y, k)
        item_b = lambda k: bearing_deg(x, y, angle, item(k)[1]["x"], item(k)[1]["y"]) if item(k) else 0.0
        item_d = lambda k: int(min(item(k)[0], 65535)) if item(k) else 0
        hint = ex.hint if ex.hint and now < ex.hint[1] else None
        exit_b = bearing_deg(x, y, angle, s["exit_seen"][0], s["exit_seen"][1]) if s["exit_seen"] else 0.0
        rays, nov, doors = s["rays"], s["nov"], s["doors"]
        return dict(
            health=int(self.var("HEALTH")), armor=int(self.var("ARMOR")),
            shells=int(self.var("AMMO3")), bullets=int(self.var("AMMO2")),
            weapon=weapon, own_shotgun=int(self.var("WEAPON3") > 0), kills=int(self.var("KILLCOUNT")),
            x=x, y=y, angle=angle,
            enemy_count=len(enemies), enemy_bearing=enemies[0][1] if enemies else 0.0,
            enemy_dist=int(min(enemies[0][2], 65535)) if enemies else 0,
            clear_fwd=clear_fwd, clear_fl=clear_fl, clear_fr=clear_fr,
            clear_left=min(rays["left"][0], 65535), clear_right=min(rays["right"][0], 65535), clear_back=min(rays["back"][0], 65535),
            clear_map_fwd=min(rays["fwd"][0], 65535),
            new_fwd=nov["fwd"], new_left=nov["left"], new_right=nov["right"], new_back=nov["back"],
            ahead_kind=AHEAD_KINDS.index(s["ahead_kind"]), ahead_dist=int(min(s["ahead_dist"], 65535)),
            exit_bearing=exit_b, exit_dist=int(min(s["exit_seen"][2], 65535)) if s["exit_seen"] else 0,
            key_bearing=item_b("key"), key_dist=item_d("key"),
            health_item=item_d("health"), ammo_item=item_d("ammo"), armor_item=item_d("armor"),
            health_bearing=item_b("health"), ammo_bearing=item_b("ammo"), armor_bearing=item_b("armor"),
            stuck=int(self.stuck), door_ahead=int(usable), goal=GOALS.index(self.goal),
            tic=int(state.tic), episode=self.episode,
            dead=int(self.game.is_player_dead()),
            level_done=int(self.game.is_episode_finished() and not self.game.is_player_dead()),
            explored=min(len(ex.visited), 65535),
            level=self.level, keys=sum(KEY_BIT[k] for k in ex.keys),
            hint_active=int(hint is not None),
            hint_rel=int(round(((hint[0] - angle + 180) % 360) - 180)) if hint else 0,
            clear_al=min(rays["al"][0], 65535), clear_ar=min(rays["ar"][0], 65535), clear_bl=min(rays["bl"][0], 65535), clear_br=min(rays["br"][0], 65535),
            new_al=nov["al"], new_ar=nov["ar"], new_bl=nov["bl"], new_br=nov["br"],
            door_fwd=doors["fwd"], door_al=doors["al"], door_left=doors["left"], door_bl=doors["bl"],
            door_back=doors["back"], door_br=doors["br"], door_right=doors["right"], door_ar=doors["ar"])

    @staticmethod
    def pack_status(o):
        return struct.pack(STATUS_FMT, o["health"], o["armor"], o["shells"], o["bullets"], o["weapon"], o["own_shotgun"],
                           o["kills"], o["x"], o["y"], o["angle"], o["enemy_count"], o["enemy_bearing"], o["enemy_dist"],
                           o["clear_fwd"], o["clear_fl"], o["clear_fr"], o["clear_left"], o["clear_right"], o["clear_back"], o["clear_map_fwd"],
                           o["new_fwd"], o["new_left"], o["new_right"], o["new_back"],
                           o["ahead_kind"], o["ahead_dist"], o["exit_bearing"], o["exit_dist"], o["key_bearing"], o["key_dist"],
                           o["health_item"], o["ammo_item"], o["armor_item"], o["health_bearing"], o["ammo_bearing"], o["armor_bearing"],
                           o["stuck"], o["door_ahead"], o["goal"], o["tic"], o["episode"], o["dead"], o["level_done"], o["explored"],
                           o["level"], o["keys"], o["hint_active"], o["hint_rel"],
                           o["clear_al"], o["clear_ar"], o["clear_bl"], o["clear_br"], o["new_al"], o["new_ar"], o["new_bl"], o["new_br"],
                           o["door_fwd"], o["door_al"], o["door_left"], o["door_bl"],
                           o["door_back"], o["door_br"], o["door_right"], o["door_ar"])

    # ------------------------------------------------------------------ uplink
    def handle(self, kind, body):
        self.cmd_count += 1
        if kind == 0x10 and len(body) >= 9:
            move, strafe, turn, fire, use, weapon = struct.unpack("!bbfBBB", body[:9])
            self.control = dict(move=move, strafe=strafe, turn=max(-180.0, min(180.0, turn)), fire=fire, use=use, weapon=weapon)
            self.turn_remaining = self.control["turn"]  # degrees still to turn, positive left
            self.last_control_time = time.time()
        elif kind == 0x11 and body:
            self.goal = GOALS[body[0]] if body[0] < len(GOALS) else "HOLD"
            print(f"[payload] goal -> {self.goal}", flush=True)
        elif kind == 0x12:
            self.new_episode()
        elif kind == 0x13 and len(body) >= 2:
            self.frame_hz, self.quality = body[0], max(10, min(95, body[1]))
            print(f"[payload] frames {self.frame_hz} Hz quality {self.quality}", flush=True)
        elif kind == 0x14 and len(body) >= 3:
            rel, ttl = struct.unpack("!hB", body[:3])
            self.explorer.hint = (self.var("ANGLE") + rel, time.time() + ttl)
            print(f"[payload] explore hint {rel:+d} deg for {ttl} s", flush=True)
        else:
            print(f"[payload] unknown uplink kind {kind:#x}", flush=True)

    def action(self, tic):
        c = self.control
        if time.time() - self.last_control_time > UPLINK_TIMEOUT_S:
            return [0] * len(BUTTONS)  # safe mode: no uplink, hold still
        use = int(c["use"]) and int(tic % 8 == 0)  # Doom triggers USE on the press edge: pulse a held use
        if use and self.use_ok:
            self.door_presses += 1
        step = max(-6.0, min(6.0, self.turn_remaining))  # onboard attitude loop: turn to the setpoint, then stop
        self.turn_remaining -= step
        return [14 * c["move"], 14 * c["strafe"], -step, int(c["fire"]), use,
                int(c["weapon"] == 1), int(c["weapon"] == 2)]

    # ------------------------------------------------------------------ main loop
    def serve(self):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", self.args.port))
        srv.listen(1)
        print(f"[payload] listening on {self.args.port}", flush=True)
        while True:
            conn, _ = srv.accept()
            conn.setblocking(False)
            print("[payload] flight software connected", flush=True)
            try:
                self.run(conn)
            except (ConnectionError, OSError) as e:
                print(f"[payload] link dropped: {e}", flush=True)
            finally:
                conn.close()

    def run(self, conn):
        inbuf = b""
        next_frame = 0.0
        t0 = time.perf_counter()
        tic = 0
        while True:
            try:
                data = conn.recv(65536)
                if data == b"":
                    return
                inbuf += data
            except BlockingIOError:
                pass
            while len(inbuf) >= 4 and inbuf[0] == ord("D"):
                kind, length = inbuf[1], struct.unpack("!H", inbuf[2:4])[0]
                if len(inbuf) < 4 + length:
                    break
                self.handle(kind, inbuf[4:4 + length])
                inbuf = inbuf[4 + length:]
            if inbuf and inbuf[0] != ord("D"):
                inbuf = b""  # resync
            if self.game.is_episode_finished() or self.game.is_player_dead():
                died = self.game.is_player_dead()
                if self.last_obs is not None:
                    self.last_obs["dead"] = int(died)
                    self.last_obs["level_done"] = int(not died)
                    self.send(conn, 1, self.pack_status(self.last_obs))
                print(f"[payload] episode {self.episode} over on {self.map}: {'died' if died else 'LEVEL FINISHED'} at tic {tic}", flush=True)
                time.sleep(2.0)
                if died:
                    self.new_episode()
                else:
                    self.level_finished()
                t0, tic = time.perf_counter(), 0
                continue
            state = self.game.get_state()
            obs = self.observe(state)
            self.last_obs = obs
            self.game.make_action(self.action(tic), 1)
            tic += 1
            if tic % self.args.status_every == 0:
                self.send(conn, 1, self.pack_status(obs))
            now = time.perf_counter()
            if self.frame_hz and now >= next_frame:
                next_frame = now + 1.0 / self.frame_hz
                buf = io.BytesIO()
                Image.fromarray(state.screen_buffer).resize((320, 240), Image.BILINEAR).save(buf, format="JPEG", quality=self.quality)
                self.frame_seq += 1
                self.send(conn, 2, struct.pack("!I", self.frame_seq) + buf.getvalue())
            if self.map_png_bytes and self.frame_hz and len(self.map_png_bytes) < 60000:
                self.map_seq += 1   # map products share the frame path; the high bit of seq marks them
                self.send(conn, 2, struct.pack("!I", 0x80000000 | self.map_seq) + self.map_png_bytes)
                self.map_png_bytes = None
            remaining = t0 + tic / TICRATE - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
            elif remaining < -1.0:
                t0 = time.perf_counter() - tic / TICRATE

    @staticmethod
    def send(conn, kind, body):
        conn.sendall(b"D" + bytes([kind]) + struct.pack("!H", len(body)) + body)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=4242)
    p.add_argument("--wad", default="doom1.wad", help="IWAD file name or path (shareware doom1.wad, freedoom1.wad, freedoom2.wad)")
    p.add_argument("--map", default="E1M1", help="first map; the payload advances to the next map when a level is finished")
    p.add_argument("--skill", type=int, default=2)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--fps", type=int, default=10, help="frame downlink rate")
    p.add_argument("--quality", type=int, default=45, help="JPEG quality")
    p.add_argument("--status-every", type=int, default=3, help="status record every N tics (35 Hz game)")
    p.add_argument("--map-png", default=None, help="also write the self-built map here every second (diagnostics)")
    Payload(p.parse_args()).serve()


if __name__ == "__main__":
    main()
