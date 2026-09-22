"""Does a CONTROL turn setpoint execute onboard? Send +50 once, watch the heading. (payload on 4243)"""
import socket, struct, time
from doom_payload import STATUS_FMT
s = socket.create_connection(("127.0.0.1", 4243)); s.settimeout(0.02)
def send(kind, body): s.sendall(b"D" + bytes([kind]) + struct.pack("!H", len(body)) + body)
buf, t0, last_print = b"", time.time(), 0
send(0x10, struct.pack("!bbfBBB", 0, 0, 50.0, 0, 0, 0))
while time.time() - t0 < 2.0:
    try: buf += s.recv(65536)
    except socket.timeout: pass
    while len(buf) >= 4:
        kind, length = buf[1], struct.unpack("!H", buf[2:4])[0]
        if len(buf) < 4 + length: break
        body, buf = buf[4:4 + length], buf[4 + length:]
        if kind == 1:
            st = struct.unpack(STATUS_FMT, body)
            if time.time() - last_print > 0.15:
                last_print = time.time(); print(f"t={time.time()-t0:4.2f}s angle={st[9]:6.1f} tic={st[27]}")
send(0x10, struct.pack("!bbfBBB", 0, 0, 0.0, 0, 0, 0))
