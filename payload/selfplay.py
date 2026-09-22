"""In-process code-only play: the Payload class driven directly (no socket, no real-time pacing) by the
same policy nav_probe.py uses. Fast iteration on the navigator: prints level changes and diagnostics.

    python selfplay.py [tics] [wad] [map]
"""
import argparse
import sys
import time

sys.path.insert(0, ".")
import doom_payload as dp

tics = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
args = argparse.Namespace(port=0, wad=sys.argv[2] if len(sys.argv) > 2 else "doom1.wad", map=sys.argv[3] if len(sys.argv) > 3 else "E1M1",
                          skill=2, seed=7, fps=0, quality=45, status_every=3, map_png="/mnt/c/Users/Kevin/Genai/DoomSat/out/selfplay_map.png")
p = dp.Payload(args)
escape, n_escapes, escape_move = 0, 0, (-1, 0)
t0 = time.time()
last_pos, still_since = None, 0
for tic in range(tics):
    if p.game.is_episode_finished() or p.game.is_player_dead():
        died = p.game.is_player_dead()
        print(f"*** tic {tic}: {'died' if died else 'LEVEL FINISHED'} on {p.map} at {time.time() - t0:.0f} s wall ***", flush=True)
        if died:
            p.new_episode()
        else:
            p.level_finished()
        continue
    state = p.game.get_state()
    o = p.observe(state)
    aim = o["enemy_bearing"] if (o["enemy_count"] and o["enemy_dist"] < 450) else o["route_bearing"]
    turn = max(-50.0, min(50.0, aim))
    aligned = abs(o["route_bearing"]) <= 35
    fire = int(o["enemy_count"] and abs(o["enemy_bearing"]) <= 8 and o["enemy_dist"] <= 450 and (o["shells"] if o["weapon"] == 2 else o["bullets"]) > 0)
    if escape > 0:
        escape -= 1
        ctrl = dict(move=escape_move[0], strafe=escape_move[1], turn=0.0, fire=0, use=1, weapon=0)
    elif o["stuck"]:
        escape, n_escapes = 12, n_escapes + 1
        options = [(-1, 0)] if o["clear_back"] > 24 else []
        options += [(0, -1)] if o["clear_left"] > 60 else []
        options += [(0, 1)] if o["clear_right"] > 60 else []
        escape_move = options[n_escapes % len(options)] if options else (0, 1 if n_escapes % 2 else -1)
        ctrl = dict(move=escape_move[0], strafe=escape_move[1], turn=0.0, fire=0, use=1, weapon=0)
    else:
        ctrl = dict(move=1 if aligned and o["clear_fwd"] > 30 else 0, strafe=0, turn=turn, fire=fire, use=1 if o["door_ahead"] else 0, weapon=0)
    if tic % 12 == 0:   # a ground decision every ~0.35 s
        p.control = ctrl
        p.turn_remaining = ctrl["turn"]
        p.last_control_time = time.time()
    p.game.make_action(p.action(tic), 1)
    near_dbg = state.depth_buffer[196:222].min(axis=0)
    if (near_dbg[::16] == 1).sum() >= 3 and not globals().get("dumped1"):
        from PIL import Image
        import numpy as np
        d = state.depth_buffer
        Image.fromarray(np.clip(d.astype(np.int32) * 3, 0, 255).astype(np.uint8)).save("/mnt/c/Users/Kevin/Genai/DoomSat/out/dn1_depth.png")
        Image.fromarray(state.screen_buffer).save("/mnt/c/Users/Kevin/Genai/DoomSat/out/dn1_screen.png")
        print("DN1 DUMP at tic", tic, "pos", (round(o["x"]), round(o["y"])), "heading", round(o["angle"]), "near per 32 cols:", [int(near_dbg[c]) for c in range(0, 640, 32)], "labels:", [(l.object_name, l.x, l.y, l.width, l.height) for l in state.labels][:6], flush=True)
        globals()["dumped1"] = True
    if o["frontiers"] == 0 and dp.NAV_MODES[o["nav_mode"]] == "idle" and not globals().get("dumped"):
        from PIL import Image
        import numpy as np
        d = state.depth_buffer
        Image.fromarray(np.clip(d.astype(np.int32) * 3, 0, 255).astype(np.uint8)).save("/mnt/c/Users/Kevin/Genai/DoomSat/out/collapse_depth.png")
        Image.fromarray(state.screen_buffer).save("/mnt/c/Users/Kevin/Genai/DoomSat/out/collapse_screen.png")
        near = d[196:222].min(axis=0)
        print("DUMP at tic", tic, "near-band min per 32 cols:", [int(near[c]) for c in range(0, 640, 32)], "labels:", [(l.object_name, l.x, l.y, l.width, l.height) for l in state.labels][:8], flush=True)
        globals()["dumped"] = True
    pos = (round(o["x"]), round(o["y"]))
    still_since = still_since + 1 if pos == last_pos else 0
    last_pos = pos
    if tic % 70 == 0 or (still_since == 140):
        cells = p.explorer.route(p.explorer.cell(*p.target)) if p.target else []
        print(f"tic {tic:5d} L{o['level']} pos={pos} ang={o['angle']:.0f} bear={o['route_bearing']:6.1f} route={o['route_dist']} "
              f"tgt={dp.TARGET_KINDS[o['target_kind']]}/{o['target_dist']} mode={dp.NAV_MODES[o['nav_mode']]} clr={o['clear_fwd']} stuck={o['stuck']} "
              f"use={o['door_ahead']} expl={o['explored']} front={o['frontiers']} doors={o['doors_known']} hunt={o['hunt_left']} keys={o['keys']} hp={o['health']} "
              f"blocked_tics={p.blocked_tics} cells={cells[:4]}" + ("  <-- STILL 4 s" if still_since == 140 else ""), flush=True)
print(f"done: level {p.level}, map {p.map}, {time.time() - t0:.0f} s wall for {tics} tics", flush=True)
