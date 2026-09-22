"""Closed-loop check of the onboard explorer with a code-only controller (no models, no flight
software): connect to a payload instance, steer toward the route waypoint, report progress.

    python doom_payload.py --port 4243 --fps 0 &   # a second instance; the flight software keeps its own
    python nav_probe.py 4243 90
"""
import socket
import struct
import sys
import time

from doom_payload import STATUS_FMT

port = int(sys.argv[1]) if len(sys.argv) > 1 else 4243
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 60
s = socket.create_connection(("127.0.0.1", port))
s.settimeout(0.02)


def send(kind, body):
    s.sendall(b"D" + bytes([kind]) + struct.pack("!H", len(body)) + body)


def control(move, strafe, turn, fire=0, use=0, weapon=0):
    send(0x10, struct.pack("!bbfBBB", move, strafe, float(turn), fire, use, weapon))


buf, last, t_end, t_report = b"", None, time.time() + seconds, 0
escape, n_escapes, escape_move = 0, 0, (-1, 0)
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
     h_item, a_item, ar_item, tic, episode, dead, done, explored, frontiers) = last
    # the same policy the decision graph expresses in words, here as code
    turn = max(-50.0, min(50.0, r_bearing))  # degrees to turn, positive left
    aligned = abs(r_bearing) <= 35
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
        control(1 if aligned and c_fwd > 45 else 0, 0, turn, use=1 if door else 0)
    detail = seconds - (t_end - time.time()) < 15
    if time.time() - t_report > (0.5 if detail else 1.0):
        t_report = time.time()
        print(f"t={seconds - (t_end - time.time()):4.0f}s pos=({x:6.0f},{y:6.0f}) ang={angle:4.0f} route_bearing={r_bearing:6.1f} "
              f"route={r_dist:5d} target={t_dist:4d}/{t_kind} clear f/l/r/b={c_fwd}/{c_left}/{c_right}/{c_back} stuck={stuck} door={door} "
              f"explored={explored} frontiers={frontiers} hp={health} enemies={n_enemy} kills={kills} ep={episode} done={done}", flush=True)
control(0, 0, 0)
