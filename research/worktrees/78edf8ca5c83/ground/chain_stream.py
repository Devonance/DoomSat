"""Uplink latency under a steady stream: alternate +40/-40 turn commands every 0.6 s, sample the heading at 10 Hz."""
import time
from yamcs.client import YamcsClient
c = YamcsClient("localhost:8090"); p = c.get_processor("fprime-project", "realtime")
name = "/DoomSat_DoomSat/DoomSat/doom/"
ang = lambda: p.get_parameter_value(name + "ANGLE").eng_value
t0 = time.time(); sent = []; samples = []
for i in range(8):
    turn = 40.0 if i % 2 == 0 else -40.0
    p.issue_command(name + "CONTROL", args={"move": 0, "strafe": 0, "turn": turn, "fire": False, "use": False, "weapon": "FIST"})
    sent.append((time.time() - t0, turn))
    for _ in range(6):
        samples.append((time.time() - t0, ang())); time.sleep(0.1)
p.issue_command(name + "CONTROL", args={"move": 0, "strafe": 0, "turn": 0.0, "fire": False, "use": False, "weapon": "FIST"})
for _ in range(20):
    samples.append((time.time() - t0, ang())); time.sleep(0.1)
print("sent:", [(round(t, 1), v) for t, v in sent])
last = None
for t, a in samples:
    if last is None or abs((a - last + 180) % 360 - 180) >= 1:
        print(f"  t={t:5.1f}s heading {a:6.1f}")
    last = a
