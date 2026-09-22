"""Doom payload: the "instrument" the flight software carries.

Runs Freedoom (via ViZDoom) at 35 Hz, keeps the last uplinked controls held, and serves an
observation summary plus JPEG frames to the F Prime Doom component over a local TCP socket.

Everything the payload reports comes from what the player can sense, not from the level file:
  - the depth buffer (a range camera): free space per bearing, and a map the payload builds
    itself as it looks around (occupancy grid + frontier of the unexplored),
  - the labels buffer (an object detector): visible enemies and pickups, remembered once seen,
  - the game variables a HUD shows: health, armor, ammo, position and heading (odometry).
The exit is not known; the navigator explores toward frontiers (optionally biased by a hint
from the ground) until the level ends.

Protocol (big-endian; the payload is the server on 127.0.0.1:4242):
  payload -> flight   'D' kind:u8 length:u16 body
     kind 1 STATUS  fixed struct (see STATUS_FMT)
     kind 2 FRAME   seq:u32 jpeg bytes
  flight -> payload   'D' kind:u8 length:u16 body
     kind 0x10 CONTROL      move:i8 strafe:i8 turn:f32 (degrees to turn, +left) fire:u8 use:u8 weapon:u8
     kind 0x11 SET_GOAL     goal:u8
     kind 0x12 RESET
     kind 0x13 FRAME_RATE   hz:u8 quality:u8
     kind 0x14 EXPLORE_HINT bearing:i16 (degrees, positive left) ttl:u8 (seconds)
"""
import argparse
import heapq
import io
import math
import os
import socket
import struct
import time
from collections import deque

import numpy as np
import vizdoom as vzd
from PIL import Image, ImageDraw

TICRATE = 35
STATUS_FMT = "!hhhhBBHfffBfHHHHHfHHBBBBHHHIHBBHH"
GOALS = ["EXPLORE", "KILL_ENEMY", "STOCK_AMMO", "RESTORE_HEALTH", "ADD_ARMOR", "UPGRADE_WEAPON", "SCOUT", "HOLD"]
TARGET_KINDS = ["frontier", "enemy", "health", "ammo", "armor", "weapon", "far_frontier", "none"]
ENEMIES = {"DoomImp", "Zombieman", "ShotgunGuy", "Demon", "Spectre", "ChaingunGuy", "Cacodemon", "HellKnight",
           "BaronOfHell", "LostSoul", "Revenant", "Arachnotron", "Fatso", "PainElemental", "Archvile", "WolfensteinSS"}
ITEM_KIND = {"Stimpack": "health", "Medikit": "health", "HealthBonus": "health", "Soulsphere": "health",
             "Clip": "ammo", "ClipBox": "ammo", "Shell": "ammo", "ShellBox": "ammo",
             "GreenArmor": "armor", "BlueArmor": "armor", "ArmorBonus": "armor",
             "Shotgun": "weapon", "Chaingun": "weapon", "Chainsaw": "weapon"}
GOAL_KIND = {"STOCK_AMMO": "ammo", "RESTORE_HEALTH": "health", "ADD_ARMOR": "armor", "UPGRADE_WEAPON": "weapon"}
BUTTONS = [vzd.Button.MOVE_FORWARD_BACKWARD_DELTA, vzd.Button.MOVE_LEFT_RIGHT_DELTA, vzd.Button.TURN_LEFT_RIGHT_DELTA,
           vzd.Button.ATTACK, vzd.Button.USE, vzd.Button.SELECT_WEAPON2, vzd.Button.SELECT_WEAPON3]
GRID = 32              # exploration map cell (map units)
FOV = 90.0             # ViZDoom default horizontal field of view
DEPTH_UNITS = 8.5      # map units per depth-buffer step (calibrated, see depth_probe.py)
DEPTH_FAR = 56         # depth steps beyond which the range camera is not trusted (~480 units)
ROUTE_EVERY = 5        # tics between route recomputations
UPLINK_TIMEOUT_S = 3.0  # no CONTROL for this long -> release everything (safe mode)


def bearing_deg(x, y, angle, tx, ty):
    """Signed bearing to (tx, ty) relative to heading `angle`; positive means left."""
    return (math.degrees(math.atan2(ty - y, tx - x)) - angle + 180) % 360 - 180


class Explorer:
    """The map the payload builds for itself from range-camera sweeps, plus what it remembers seeing."""

    def __init__(self):
        self.known = {}        # cell -> True (free) / False (wall)
        self.visited = set()
        self.items = {}        # (kind, rounded x, rounded y) -> {"kind", "name", "x", "y", "seen"}
        self.hint = None       # (bearing_deg absolute, expiry time)
        self.route_cache = (None, None, 0, -1)

    @staticmethod
    def cell(x, y):
        return int(math.floor(x / GRID)), int(math.floor(y / GRID))

    @staticmethod
    def xy(c):
        return (c[0] + 0.5) * GRID, (c[1] + 0.5) * GRID

    def sweep(self, x, y, angle, depth_row):
        """One range-camera sweep: walk each ray, mark free cells up to the hit, mark the hit as wall."""
        here = self.cell(x, y)
        self.known[here] = True
        self.visited.add(here)
        w = len(depth_row)
        for col in range(0, w, 8):
            rel = math.degrees(math.atan((0.5 - col / (w - 1)) * 2 * math.tan(math.radians(FOV / 2))))
            d = int(depth_row[col])
            dist = min(d, DEPTH_FAR) * DEPTH_UNITS
            a = math.radians(angle + rel)
            step = GRID / 2
            r = step
            while r < dist - GRID / 2:
                c = self.cell(x + r * math.cos(a), y + r * math.sin(a))
                self.known[c] = True  # seeing through a cell beats an older hit there (monsters move)
                r += step
            if d < DEPTH_FAR:
                c = self.cell(x + dist * math.cos(a), y + dist * math.sin(a))
                if c not in self.visited:
                    self.known[c] = False

    def free(self, c):
        return self.known.get(c, False)

    def frontier_cells(self):
        out = []
        for c, is_free in self.known.items():
            if not is_free:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if (c[0] + dx, c[1] + dy) not in self.known:
                    out.append(c)
                    break
        return out

    def near_wall(self, c):
        return any(self.known.get((c[0] + dx, c[1] + dy)) is False
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy)

    def path(self, x, y, goal_xy, budget=15000):
        """A* over known-free cells (cells beside a known wall cost extra, so routes keep to the middle);
        falls back to the closest reachable cell if the goal is not reachable."""
        start, goal = self.cell(x, y), self.cell(*goal_xy)
        h = lambda c: math.hypot(c[0] - goal[0], c[1] - goal[1])
        queue, cost, parent, seen = [(h(start), start)], {start: 0.0}, {}, 0
        best, best_h = start, h(start)
        while queue and seen < budget:
            _, node = heapq.heappop(queue)
            seen += 1
            if h(node) < best_h:
                best, best_h = node, h(node)
            if node == goal:
                best = node
                break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nxt = (node[0] + dx, node[1] + dy)
                if not self.free(nxt) and nxt != goal:
                    continue
                if dx and dy and not (self.free((node[0] + dx, node[1])) and self.free((node[0], node[1] + dy))):
                    continue
                c = cost[node] + math.hypot(dx, dy) + (1.5 if self.near_wall(nxt) else 0.0)
                if c < cost.get(nxt, 1e9):
                    cost[nxt], parent[nxt] = c, node
                    heapq.heappush(queue, (c + h(nxt), nxt))
        out = [best]
        while best in parent:
            best = parent[best]
            out.append(best)
        return [self.xy(c) for c in reversed(out)]

    def reach(self, x, y, limit=4000):
        """Breadth-first walking distance (cells) to every known-free cell reachable from the player."""
        start = self.cell(x, y)
        dist, queue = {start: 0}, deque([start])
        while queue and len(dist) < limit:
            node = queue.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (node[0] + dx, node[1] + dy)
                if nxt not in dist and self.free(nxt):
                    dist[nxt] = dist[node] + 1
                    queue.append(nxt)
        return dist

    def pick_frontier(self, x, y, angle, farthest=False):
        """Nearest (or farthest) reachable frontier by walking distance, with the hint as a bias."""
        cells = self.frontier_cells()
        if not cells:
            return None
        dist = self.reach(x, y)
        hint = self.hint if self.hint and time.time() < self.hint[1] else None
        scored = []
        for c in cells:
            if c not in dist or dist[c] < 4:  # unreachable, or too close to be worth a trip
                continue
            cx, cy = self.xy(c)
            d = dist[c] * GRID
            if hint is not None:
                off = abs((math.degrees(math.atan2(cy - y, cx - x)) - hint[0] + 180) % 360 - 180)
                d += off * 4.0  # 90 degrees off the hint costs as much as 360 units of distance
            scored.append((d, (cx, cy)))
        if not scored:
            # Nothing unexplored in reach: go to the farthest known place not walked yet (a look around)
            far = [(dist[c], c) for c in dist if c not in self.visited and dist[c] >= 3]
            if not far:
                return None
            return self.xy(max(far)[1])
        scored.sort()
        return scored[-1][1] if farthest else scored[0][1]

    def reachable(self, x, y, xy):
        return self.cell(*xy) in self.reach(x, y)

    def is_frontier(self, xy):
        c = self.cell(*xy)
        return self.free(c) and any((c[0] + dx, c[1] + dy) not in self.known for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))

    def side_clearance(self, x, y, angle, side_deg):
        """Space to one side from the self-built map: 0 wall, 24 unknown, 64+ known free (map units)."""
        a = math.radians(angle + side_deg)
        for k in (1, 2):
            c = self.cell(x + k * GRID * math.cos(a), y + k * GRID * math.sin(a))
            known = self.known.get(c)
            if known is False:
                return 0 if k == 1 else GRID
            if known is None:
                return 24 if k == 1 else GRID
        return 2 * GRID + 8

    def render(self, x, y, angle, target, path):
        """Draw the self-built map (for the ground display and for debugging)."""
        if not self.known:
            return None
        xs = [c[0] for c in self.known]
        ys = [c[1] for c in self.known]
        x0, x1, y0, y1 = min(xs) - 2, max(xs) + 3, min(ys) - 2, max(ys) + 3
        S = 6
        img = Image.new("RGB", ((x1 - x0) * S, (y1 - y0) * S), (24, 24, 28))
        d = ImageDraw.Draw(img)
        px = lambda c: ((c[0] - x0) * S, (y1 - 1 - c[1]) * S)   # map y up
        for c, is_free in self.known.items():
            a, b = px(c)
            d.rectangle((a, b, a + S - 1, b + S - 1), fill=(70, 70, 78) if is_free else (200, 200, 210))
        for c in self.visited:
            a, b = px(c)
            d.rectangle((a + 2, b + 2, a + S - 3, b + S - 3), fill=(40, 120, 60))
        for c in self.frontier_cells():
            a, b = px(c)
            d.rectangle((a + 1, b + 1, a + S - 2, b + S - 2), outline=(230, 190, 40))
        for wx, wy in path or []:
            a, b = px(self.cell(wx, wy))
            d.rectangle((a + 2, b + 2, a + S - 3, b + S - 3), fill=(60, 150, 230))
        if target:
            a, b = px(self.cell(*target))
            d.ellipse((a - 3, b - 3, a + S + 2, b + S + 2), outline=(255, 90, 60), width=2)
        a, b = px(self.cell(x, y))
        cx, cy = a + S / 2, b + S / 2
        d.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=(255, 60, 60))
        d.line((cx, cy, cx + 12 * math.cos(math.radians(angle)), cy - 12 * math.sin(math.radians(angle))), fill=(255, 60, 60), width=2)
        return img

    def remember_items(self, x, y, labels):
        for lab in labels:
            kind = ITEM_KIND.get(lab.object_name)
            if kind:
                key = (kind, round(lab.object_position_x / 16), round(lab.object_position_y / 16))
                self.items[key] = {"kind": kind, "name": lab.object_name, "x": lab.object_position_x,
                                   "y": lab.object_position_y, "seen": time.time()}
        for key in [k for k, v in self.items.items() if math.hypot(v["x"] - x, v["y"] - y) < 40]:
            del self.items[key]  # walked over it: picked up (or not a pickup we can take)

    def nearest_item(self, x, y, kind):
        best = None
        for v in self.items.values():
            if v["kind"] == kind:
                d = math.hypot(v["x"] - x, v["y"] - y)
                if best is None or d < best[0]:
                    best = (d, v)
        return best


class Payload:
    def __init__(self, args):
        self.args = args
        self.wad = os.path.join(os.path.dirname(vzd.__file__), "freedoom2.wad")
        self.game = self._make_game()
        self.explorer = Explorer()
        self.goal = "EXPLORE"
        self.control = dict(move=0, strafe=0, turn=0.0, fire=0, use=0, weapon=0)
        self.last_control_time = 0.0
        self.frame_hz, self.quality = args.fps, args.quality
        self.frame_seq = 0
        self.episode = 0
        self.positions = deque(maxlen=20)
        self.stuck = False
        self.cmd_count = 0
        self.last_obs = None
        self.frontier_target, self.frontier_since, self.frontier_kind = None, 0, None
        self.turn_remaining = 0.0
        self.new_episode()

    def _make_game(self):
        g = vzd.DoomGame()
        g.set_doom_game_path(self.wad)
        g.set_doom_map(self.args.map)
        g.set_doom_skill(self.args.skill)
        g.set_available_buttons(BUTTONS)
        g.set_button_max_value(vzd.Button.TURN_LEFT_RIGHT_DELTA, 6)
        g.set_button_max_value(vzd.Button.MOVE_FORWARD_BACKWARD_DELTA, 14)
        g.set_button_max_value(vzd.Button.MOVE_LEFT_RIGHT_DELTA, 14)
        g.set_window_visible(False)
        g.set_screen_resolution(vzd.ScreenResolution.RES_320X240)
        g.set_screen_format(vzd.ScreenFormat.RGB24)
        g.set_render_hud(True)
        g.set_render_crosshair(True)
        g.set_depth_buffer_enabled(True)
        g.set_labels_buffer_enabled(True)
        g.set_sound_enabled(False)
        g.set_episode_timeout(0)
        g.set_seed(self.args.seed)
        g.set_mode(vzd.Mode.PLAYER)
        g.init()
        return g

    def new_episode(self):
        self.game.new_episode()
        for cmd in ("give shotgun", "take Shell 999", "give Shell 4", "take Clip 999", "give Clip 30"):
            self.game.send_game_command(cmd)
        self.game.make_action([0] * len(BUTTONS), 1)
        self.episode += 1
        self.positions.clear()
        self.goal = "EXPLORE"
        self.control = dict(move=0, strafe=0, turn=0.0, fire=0, use=0, weapon=0)
        self.explorer.items.clear()  # pickups respawn; the map stays (the player remembers the level)
        self.explorer.route_cache = (None, None, 0, -1)
        self.frontier_target = None
        print(f"[payload] episode {self.episode} started", flush=True)

    # ------------------------------------------------------------------ observation
    def var(self, name):
        return float(self.game.get_game_variable(getattr(vzd.GameVariable, name)))

    @staticmethod
    def sector_clearance(depth_row, lo_deg, hi_deg):
        """Nearest range (map units) in a bearing band of the range camera; positive bearings are left."""
        w = len(depth_row)
        cols = []
        for col in range(0, w, 4):
            rel = math.degrees(math.atan((0.5 - col / (w - 1)) * 2 * math.tan(math.radians(FOV / 2))))
            if lo_deg <= rel <= hi_deg:
                cols.append(int(depth_row[col]))
        if not cols:
            return 2000
        return int(min(min(cols), DEPTH_FAR) * DEPTH_UNITS)

    def observe(self, state):
        x, y, angle = self.var("POSITION_X"), self.var("POSITION_Y"), self.var("ANGLE")
        ex = self.explorer
        depth = state.depth_buffer
        band = depth[depth.shape[0] * 5 // 12: depth.shape[0] * 7 // 12]   # a horizontal band around eye level
        depth_row = band.max(axis=0)                                        # floor/ceiling do not count as walls
        ex.sweep(x, y, angle, depth_row)
        ex.remember_items(x, y, state.labels)
        enemies = []
        for lab in state.labels:
            if lab.object_name in ENEMIES:
                b = bearing_deg(x, y, angle, lab.object_position_x, lab.object_position_y)
                enemies.append((abs(b), b, math.hypot(lab.object_position_x - x, lab.object_position_y - y), lab))
        enemies.sort(key=lambda e: e[0])
        # target selection is deterministic code over what has been sensed or remembered
        target, kind = None, "none"
        if self.goal == "KILL_ENEMY" and enemies:
            e = enemies[0][3]
            target, kind = (e.object_position_x, e.object_position_y), "enemy"
        elif self.goal in GOAL_KIND:
            found = ex.nearest_item(x, y, GOAL_KIND[self.goal])
            if found:
                target, kind = (found[1]["x"], found[1]["y"]), GOAL_KIND[self.goal]
        if target is None and self.goal != "HOLD":
            # Frontier targets are sticky: keep the current one until it is reached, stops being a frontier,
            # or a while passes without progress. Otherwise the choice flips as the view changes.
            kind = "far_frontier" if self.goal == "SCOUT" else "frontier"
            cur = self.frontier_target
            # A chosen frontier stays the destination until it is reached, turns out to be a wall or
            # unreachable, or a while passes; it need not stay a frontier (it is still a waypoint).
            reached = cur is not None and math.hypot(cur[0] - x, cur[1] - y) < 40
            gone = cur is not None and (ex.known.get(ex.cell(*cur)) is False or not ex.reachable(x, y, cur))
            stale = cur is not None and state.tic - self.frontier_since > 35 * 25
            if cur is None or reached or gone or stale or self.frontier_kind != kind:
                cur = ex.pick_frontier(x, y, angle, farthest=(kind == "far_frontier"))
                self.frontier_target, self.frontier_since, self.frontier_kind = cur, state.tic, kind
            target = cur
            if target is None:
                kind = "none"
        route_bearing, route_dist, target_dist, path = 0.0, 0, 0, []
        if target:
            target_dist = math.hypot(target[0] - x, target[1] - y)
            cached_target, cached_wp, cached_len, cached_tic = ex.route_cache
            if cached_wp is None or cached_target != target or state.tic < cached_tic or state.tic - cached_tic >= ROUTE_EVERY:
                path = ex.path(x, y, target)
                if len(path) > 1:
                    cached_wp, cached_len = path[min(3, len(path) - 1)], (len(path) - 1) * GRID
                else:
                    cached_wp, cached_len = target, int(target_dist)
                ex.route_cache = (target, cached_wp, cached_len, state.tic)
            route_bearing, route_dist = bearing_deg(x, y, angle, *cached_wp), cached_len
        elif self.goal != "HOLD":
            route_bearing = 90.0  # nowhere to go that we know of: ask for a turn so the camera sees more
        self.positions.append((x, y))
        moving = self.control["move"] != 0 or self.control["strafe"] != 0
        self.stuck = bool(moving and len(self.positions) == self.positions.maxlen
                          and math.hypot(x - self.positions[0][0], y - self.positions[0][1]) < 12)
        clear_fwd = self.sector_clearance(depth_row, -20, 20)
        clear_left = min(self.sector_clearance(depth_row, 25, 45), ex.side_clearance(x, y, angle, 90))
        clear_right = min(self.sector_clearance(depth_row, -45, -25), ex.side_clearance(x, y, angle, -90))
        clear_back = ex.side_clearance(x, y, angle, 180)
        if self.args.map_png and state.tic % 70 == 0:
            img = ex.render(x, y, angle, target, path or None)
            if img is not None:
                try:
                    img.save(self.args.map_png + ".tmp.png")
                    os.replace(self.args.map_png + ".tmp.png", self.args.map_png)
                except OSError:
                    pass
        # something at arm's reach where the route wants to go: a door, a switch, or just a wall to try
        door_ahead = bool(target and abs(route_bearing) < 30 and clear_fwd < 80) or self.stuck
        weapon = {1: 0, 2: 1, 3: 2}.get(int(self.var("SELECTED_WEAPON")), 3)
        frontiers = ex.frontier_cells()
        near_item = lambda k: int(min(ex.nearest_item(x, y, k)[0], 65535)) if ex.nearest_item(x, y, k) else 65535
        return dict(
            health=int(self.var("HEALTH")), armor=int(self.var("ARMOR")),
            shells=int(self.var("AMMO3")), bullets=int(self.var("AMMO2")),
            weapon=weapon, own_shotgun=int(self.var("WEAPON3") > 0), kills=int(self.var("KILLCOUNT")),
            x=x, y=y, angle=angle,
            enemy_count=len(enemies),
            enemy_bearing=enemies[0][1] if enemies else 0.0,
            enemy_dist=int(min(enemies[0][2], 65535)) if enemies else 0,
            clear_fwd=clear_fwd, clear_left=clear_left, clear_right=clear_right, clear_back=clear_back,
            route_bearing=route_bearing, route_dist=int(min(route_dist, 65535)),
            target_dist=int(min(target_dist, 65535)), target_kind=TARGET_KINDS.index(kind),
            stuck=int(self.stuck), door_ahead=int(door_ahead), goal=GOALS.index(self.goal),
            health_item=near_item("health"), ammo_item=near_item("ammo"), armor_item=near_item("armor"),
            tic=int(state.tic), episode=self.episode,
            dead=int(self.game.is_player_dead()),
            level_done=int(self.game.is_episode_finished() and not self.game.is_player_dead()),
            explored=min(len(ex.visited), 65535), frontiers=min(len(frontiers), 65535))

    @staticmethod
    def pack_status(o):
        return struct.pack(STATUS_FMT, o["health"], o["armor"], o["shells"], o["bullets"], o["weapon"], o["own_shotgun"],
                           o["kills"], o["x"], o["y"], o["angle"], o["enemy_count"], o["enemy_bearing"], o["enemy_dist"],
                           o["clear_fwd"], o["clear_left"], o["clear_right"], o["clear_back"], o["route_bearing"],
                           o["route_dist"], o["target_dist"], o["target_kind"],
                           o["stuck"], o["door_ahead"], o["goal"], o["health_item"], o["ammo_item"], o["armor_item"],
                           o["tic"], o["episode"], o["dead"], o["level_done"], o["explored"], o["frontiers"])

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
        step = max(-6.0, min(6.0, self.turn_remaining))  # onboard attitude loop: turn to the setpoint, then stop
        self.turn_remaining -= step
        if step and os.environ.get("DOOM_DEBUG_TURN"):
            print(f"[turn] tic={tic} step={step:+.1f} remaining={self.turn_remaining:+.1f} angle={self.var('ANGLE'):.1f}", flush=True)
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
                if self.last_obs is not None:
                    self.last_obs["dead"] = int(self.game.is_player_dead())
                    self.last_obs["level_done"] = int(not self.game.is_player_dead())
                    self.send(conn, 1, self.pack_status(self.last_obs))
                print(f"[payload] episode {self.episode} over: {'died' if self.game.is_player_dead() else 'level finished'}", flush=True)
                time.sleep(2.0)
                self.new_episode()
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
                Image.fromarray(state.screen_buffer).save(buf, format="JPEG", quality=self.quality)
                self.frame_seq += 1
                self.send(conn, 2, struct.pack("!I", self.frame_seq) + buf.getvalue())
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
    p.add_argument("--map", default="MAP01")
    p.add_argument("--skill", type=int, default=2)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--fps", type=int, default=10, help="frame downlink rate")
    p.add_argument("--quality", type=int, default=45, help="JPEG quality")
    p.add_argument("--status-every", type=int, default=3, help="status record every N tics (35 Hz game)")
    p.add_argument("--map-png", default=None, help="write the self-built map here every 2 s (diagnostics/display)")
    Payload(p.parse_args()).serve()


if __name__ == "__main__":
    main()
