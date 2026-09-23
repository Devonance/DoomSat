"""One CONTROL through the real chain (Yamcs -> F Prime -> payload): does the heading move by the setpoint?"""
import sys, time
from yamcs.client import YamcsClient
c = YamcsClient("localhost:8090"); p = c.get_processor("fprime-project", "realtime")
name = "/DoomSat_DoomSat/DoomSat/doom/"
ang = lambda: p.get_parameter_value(name + "ANGLE").eng_value
cmds = lambda: p.get_parameter_value(name + "CMDS_RECEIVED").eng_value
turn = float(sys.argv[1]) if len(sys.argv) > 1 else 50.0
a0, n0 = ang(), cmds()
p.issue_command(name + "CONTROL", args={"move": 0, "strafe": 0, "turn": turn, "fire": False, "use": False, "weapon": "FIST"})
t0 = time.time()
while time.time() - t0 < 2.5:
    time.sleep(0.25)
    print(f"t={time.time()-t0:4.2f}s angle={ang():6.1f} (start {a0:.1f}, delta {((ang()-a0+180)%360-180):+.1f}) cmds={cmds()-n0}")
p.issue_command(name + "CONTROL", args={"move": 0, "strafe": 0, "turn": 0.0, "fire": False, "use": False, "weapon": "FIST"})
