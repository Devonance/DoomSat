"""Direct-socket setpoint test after the game has been ticking: send +40, then -40, sample heading at 10 Hz."""
import socket, struct, time
from doom_payload import STATUS_FMT
s = socket.create_connection(("127.0.0.1", 4243)); s.settimeout(0.02)
def send(kind, body): s.sendall(b"D" + bytes([kind]) + struct.pack("!H", len(body)) + body)
buf, last, ang = b"", None, None
def pump():
    global buf, last
    try: buf += s.recv(65536)
    except socket.timeout: pass
    while len(buf) >= 4:
        kind, length = buf[1], struct.unpack("!H", buf[2:4])[0]
        if len(buf) < 4 + length: break
        body, buf = buf[4:4 + length], buf[4 + length:]
        if kind == 1: last = struct.unpack(STATUS_FMT, body)
send(0x10, struct.pack("!bbfBBB", 0, 0, 0.0, 0, 0, 0))
t0 = time.time()
while time.time() - t0 < 2.0: pump()
for turn in (40.0, -40.0, 40.0):
    send(0x10, struct.pack("!bbfBBB", 0, 0, turn, 0, 0, 0)); t1 = time.time(); trail = []
    while time.time() - t1 < 1.2:
        pump()
        if last and (not trail or trail[-1][1] != last[9]): trail.append((round(time.time() - t1, 2), last[9]))
        time.sleep(0.03)
    print(f"turn {turn:+.0f}: heading trail {trail[:8]} ... final {trail[-1][1] if trail else None}")
