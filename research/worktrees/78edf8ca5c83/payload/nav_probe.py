"""Closed-loop check of the onboard navigator with a code-only controller (no models, no flight
software): connect to a payload instance, steer toward the route waypoint, report progress and
level changes. The policy here is the decision graph's control heads written as code.

    python doom_payload.py --port 4243 --fps 0 &   # a second instance; the flight software keeps its own
    python nav_probe.py 4243 600
"""
import socket
import struct
import sys
import time

from doom_payload import STATUS_FMT, NAV_MODES, TARGET_KINDS

port = int(sys.argv[1]) if len(sys.argv) > 1 else 4243
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 60
s = socket.create_connection(("127.0.0.1", port))
s.settimeout(0.02)


def send(kind, body):
    s.sendall(b"D" + bytes([kind]) + struct.pack("!H", len(body)) + body)


def control(move, strafe, turn, fire=0, use=0, weapon=0):
    send(0x10, struct.pack("!bbfBBB", move, strafe, float(turn), fire, use, weapon))


buf, last, t_start, t_end, t_report = b"", None, time.time(), time.time() + seconds, 0
escape, n_escapes, escape_move = 0, 0, (-1, 0)
last_level, last_episode, levels_done = None, None, []
while time.time() < t_end:
    try:
        buf += s.recv(65536)
    except socket.timeout:
        pass
    while len(buf) >= 4:
        kind, length = buf[1], struct.unpack("!H", buf[2:4])[0]
        if len(buf) < 4 + length:
            break
        body, buf = buf[4:4 + length], buf[4 + length:]
        if kind == 1:
            last = struct.unpack(STATUS_FMT, body)
    if last is None:
        continue
    (health, armor, shells, bullets, weapon, own_sg, kills, x, y, angle, n_enemy, e_bearing, e_dist,
     c_fwd, c_left, c_right, c_back, r_bearing, r_dist, t_dist, t_kind, stuck, door, goal,
     h_item, a_item, ar_item, tic, episode, dead, done, explored, frontiers,
     level, keys, nav_mode, doors_known, hunt_left) = last
    if level != last_level:
        if last_level is not None:
            levels_done.append((last_level, round(time.time() - t_start)))
            print(f"*** LEVEL {last_level} FINISHED at t={time.time() - t_start:.0f}s ***", flush=True)
        last_level = level
    if episode != last_episode:
        print(f"--- episode {episode} (level {level}) at t={time.time() - t_start:.0f}s hp={health}", flush=True)
        last_episode = episode
    # the same policy the decision graph expresses in words, here as code
    aim = e_bearing if (n_enemy and e_dist < 450) else r_bearing
    turn = max(-50.0, min(50.0, aim))  # degrees to turn, positive left
    aligned = abs(r_bearing) <= 35
    fire = int(n_enemy and abs(e_bearing) <= 8 and e_dist <= 450 and (shells if weapon == 2 else bullets) > 0)
    if escape > 0:
        escape -= 1
        control(*escape_move, 0, use=1)
    elif stuck:
        escape, n_escapes = 12, n_escapes + 1
        options = [(-1, 0)] if c_back > 24 else []
        options += [(0, -1)] if c_left > 60 else []
        options += [(0, 1)] if c_right > 60 else []
        escape_move = options[n_escapes % len(options)] if options else (0, 1 if n_escapes % 2 else -1)
        control(*escape_move, 0, use=1)
    else:
        control(1 if aligned and c_fwd > 30 else 0, 0, turn, fire=fire, use=1 if door else 0)
    if time.time() - t_report > 1.0:
        t_report = time.time()
        print(f"t={time.time() - t_start:4.0f}s L{level} pos=({x:6.0f},{y:6.0f}) ang={angle:4.0f} bearing={r_bearing:6.1f} "
              f"route={r_dist:5d} target={t_dist:4d}/{TARGET_KINDS[t_kind]} mode={NAV_MODES[nav_mode]} clear f/l/r/b={c_fwd}/{c_left}/{c_right}/{c_back} "
              f"stuck={stuck} use={door} explored={explored} frontiers={frontiers} doors={doors_known} hunt={hunt_left} keys={keys} "
              f"hp={health} enemies={n_enemy} kills={kills} ep={episode}", flush=True)
control(0, 0, 0)
print("levels finished:", levels_done, flush=True)
