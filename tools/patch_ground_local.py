"""One-off patch: ground software for the local-sensing telemetry layout (channels, raw keys, report, dashboard)."""
import ast


def edit(path, pairs):
    s = open(path, encoding="utf-8").read()
    for old, new in pairs:
        assert old in s, (path, old[:70])
        s = s.replace(old, new, 1)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    if path.endswith(".py"):
        ast.parse(s)
    print(path, "ok")


edit("ground/pilot.py", [
    ('''STATUS_CHANNELS = ["HEALTH", "ARMOR", "SHELLS", "BULLETS", "WEAPON", "OWN_SHOTGUN", "KILLS", "POS_X", "POS_Y", "ANGLE",
                   "ENEMY_COUNT", "ENEMY_BEARING", "ENEMY_DIST", "CLEAR_FWD", "CLEAR_LEFT", "CLEAR_RIGHT", "CLEAR_BACK",
                   "ROUTE_BEARING", "ROUTE_DIST", "TARGET_DIST", "TARGET_KIND", "STUCK", "DOOR_AHEAD", "GOAL",
                   "HEALTH_ITEM_DIST", "AMMO_ITEM_DIST", "ARMOR_ITEM_DIST", "TIC", "EPISODE", "DEAD", "LEVEL_DONE",
                   "FRAMES_SENT", "CHUNKS_SENT", "FRAME_BYTES", "PAYLOAD_LINK", "CMDS_RECEIVED", "EXPLORED_CELLS", "FRONTIERS",
                   "LEVEL", "KEYS", "NAV_MODE", "DOORS_KNOWN", "HUNT_LEFT"]''',
     '''STATUS_CHANNELS = ["HEALTH", "ARMOR", "SHELLS", "BULLETS", "WEAPON", "OWN_SHOTGUN", "KILLS", "POS_X", "POS_Y", "ANGLE",
                   "ENEMY_COUNT", "ENEMY_BEARING", "ENEMY_DIST", "CLEAR_FWD", "CLEAR_LEFT", "CLEAR_RIGHT", "CLEAR_BACK",
                   "CLEAR_FL", "CLEAR_FR", "CLEAR_MAP_FWD", "NEW_FWD", "NEW_LEFT", "NEW_RIGHT", "NEW_BACK", "AHEAD_KIND", "AHEAD_DIST",
                   "EXIT_BEARING", "EXIT_DIST", "KEY_BEARING", "KEY_DIST", "HEALTH_ITEM_DIST", "AMMO_ITEM_DIST", "ARMOR_ITEM_DIST",
                   "HEALTH_BEARING", "AMMO_BEARING", "ARMOR_BEARING", "STUCK", "DOOR_AHEAD", "GOAL", "TIC", "EPISODE", "DEAD",
                   "LEVEL_DONE", "EXPLORED_CELLS", "LEVEL", "KEYS", "HINT_ACTIVE", "HINT_REL",
                   "FRAMES_SENT", "CHUNKS_SENT", "FRAME_BYTES", "PAYLOAD_LINK", "CMDS_RECEIVED"]'''),
    ('''RAW_KEYS = ("ROUTE_BEARING", "CLEAR_FWD", "CLEAR_LEFT", "CLEAR_RIGHT", "STUCK", "POS_X", "POS_Y", "ANGLE", "ENEMY_COUNT", "EXPLORED_CELLS",
            "LEVEL", "NAV_MODE", "KEYS", "DOORS_KNOWN", "HUNT_LEFT")''',
     '''RAW_KEYS = ("CLEAR_FWD", "CLEAR_LEFT", "CLEAR_RIGHT", "CLEAR_BACK", "NEW_FWD", "NEW_LEFT", "NEW_RIGHT", "NEW_BACK", "AHEAD_KIND",
            "AHEAD_DIST", "EXIT_DIST", "STUCK", "POS_X", "POS_Y", "ANGLE", "ENEMY_COUNT", "EXPLORED_CELLS", "LEVEL", "KEYS", "HINT_ACTIVE")'''),
    ('''        cargs = dg.control_args(answers, cfg)''', '''        cargs = dg.control_args(answers, cfg, t)'''),
    ('''               "seen": state["navigation"] | {"enemy_where": state["combat"]["enemy_where"]},''',
     '''               "seen": state["surroundings"] | {"exit": state["seen"]["exit"], "enemy_where": state["combat"]["enemy_where"]},'''),
    ('''            prompt = ("Progress check. {:.0f} s into this level attempt (budget {:.0f} s), {} new map cells in the last minute. "
                      "Position ({:.0f}, {:.0f}), heading {:.0f} degrees "
                      "(0 = east, 90 = north). Level {}. Navigator: {}. Frontiers: {}. Doors seen: {}. Keys: {}.\\n"''',
     '''            prompt = ("Progress check. {:.0f} s into this level attempt (budget {:.0f} s), {} new map cells in the last minute. "
                      "Position ({:.0f}, {:.0f}), heading {:.0f} degrees "
                      "(0 = east, 90 = north). Level {}. Ahead: {}. Exit line seen at: {} units. Stuck: {}. Keys: {}.\\n"'''),
    ('''                t.get("POS_X", 0), t.get("POS_Y", 0), t.get("ANGLE", 0), t.get("LEVEL"), t.get("NAV_MODE"), t.get("FRONTIERS"),
                t.get("DOORS_KNOWN"), t.get("KEYS"), path, amap or "(no map product yet)")''',
     '''                t.get("POS_X", 0), t.get("POS_Y", 0), t.get("ANGLE", 0), t.get("LEVEL"), t.get("AHEAD_KIND"), t.get("EXIT_DIST"),
                t.get("STUCK"), t.get("KEYS"), path, amap or "(no map product yet)")'''),
])

edit("ground/after_action.py", [
    ('''    modes = Counter(str(r.get("NAV_MODE")) for r in raw if r.get("NAV_MODE") is not None)''',
     '''    modes = Counter(str(r.get("AHEAD_KIND")) for r in raw if r.get("AHEAD_KIND") is not None)'''),
    ('''        "navigator_modes_ticks": dict(modes.most_common()),''', '''        "ahead_kind_ticks": dict(modes.most_common()),
        "exit_line_seen": any((r.get("EXIT_DIST") or 0) > 0 for r in raw),'''),
    ('''        "doors_seen": max((r.get("DOORS_KNOWN", 0) or 0) for r in raw) if raw else None,''', ''''''),
    ('''    for head in ("move", "turn", "strafe", "dodge", "fire", "use", "weapon", "goal"):''',
     '''    for head in ("steer", "move", "turn", "strafe", "dodge", "fire", "use", "weapon", "goal"):'''),
    ('''        last.append(f"hp={r.get('health')} goal={r.get('goal')} aim={s.get('aim_offset')} ahead={s.get('space_ahead')} "
                    f"stuck={s.get('stuck')} enemy={s.get('enemy_where', '-')[:30]} -> " + " ".join(f"{k}={v}" for k, v in r["answers"].items()))''',
     '''        last.append(f"hp={r.get('health')} goal={r.get('goal')} ahead={s.get('ahead')}/{s.get('ahead_ground')} left={s.get('left')}/{s.get('left_ground')} "
                    f"right={s.get('right')}/{s.get('right_ground')} arm={s.get('at_arms_length_ahead')} exit={s.get('exit')} stuck={s.get('stuck')} -> "
                    + " ".join(f"{k}={v}" for k, v in r["answers"].items()))'''),
])

edit("ground/dashboard/index.html", [
    ('''const TLM = ["HEALTH","ARMOR","SHELLS","BULLETS","WEAPON","KILLS","POS_X","POS_Y","ANGLE","ENEMY_COUNT","ENEMY_DIST","CLEAR_FWD",
  "ROUTE_BEARING","TARGET_KIND","TARGET_DIST","STUCK","DOOR_AHEAD","GOAL","TIC","EPISODE","LEVEL","KEYS","NAV_MODE","DOORS_KNOWN",
  "HUNT_LEFT","FRONTIERS","FRAMES_SENT"];''',
     '''const TLM = ["HEALTH","ARMOR","SHELLS","BULLETS","WEAPON","KILLS","POS_X","POS_Y","ANGLE","ENEMY_COUNT","ENEMY_DIST","CLEAR_FWD",
  "CLEAR_LEFT","CLEAR_RIGHT","CLEAR_BACK","NEW_FWD","NEW_LEFT","NEW_RIGHT","NEW_BACK","AHEAD_KIND","AHEAD_DIST","EXIT_DIST","EXIT_BEARING",
  "STUCK","DOOR_AHEAD","GOAL","TIC","EPISODE","LEVEL","KEYS","EXPLORED_CELLS","FRAMES_SENT"];'''),
    ('''          <tr><td class="k">Navigator</td><td id="NAV_MODE" class="acc"></td></tr>
          <tr><td class="k">Target</td><td><span id="TARGET_KIND"></span> <span id="TARGET_DIST" class="dim"></span></td></tr>
          <tr><td class="k">Route bearing / space ahead</td><td><span id="ROUTE_BEARING"></span>&deg; / <span id="CLEAR_FWD"></span> u</td></tr>
          <tr><td class="k">Frontiers / doors seen</td><td><span id="FRONTIERS"></span> / <span id="DOORS_KNOWN"></span></td></tr>''',
     '''          <tr><td class="k">At arm's length ahead</td><td><span id="AHEAD_KIND" class="acc"></span> <span id="AHEAD_DIST" class="dim"></span></td></tr>
          <tr><td class="k">Space ahead / left / right / behind</td><td><span id="CLEAR_FWD"></span> / <span id="CLEAR_LEFT"></span> / <span id="CLEAR_RIGHT"></span> / <span id="CLEAR_BACK"></span> u</td></tr>
          <tr><td class="k">New ground ahead / left / right / behind</td><td><span id="NEW_FWD"></span> / <span id="NEW_LEFT"></span> / <span id="NEW_RIGHT"></span> / <span id="NEW_BACK"></span> %</td></tr>
          <tr><td class="k">Exit line seen / cells walked</td><td><span id="EXIT_DIST"></span> u / <span id="EXPLORED_CELLS"></span></td></tr>'''),
    ('''    $("NAV_MODE").textContent = (v.NAV_MODE || "") + (MODE[v.NAV_MODE] ? " - " + MODE[v.NAV_MODE] : "") + (v.NAV_MODE === "HUNT" ? ` (${v.HUNT_LEFT} walls left)` : "");
    $("TARGET_DIST").textContent = v.TARGET_DIST ? `${v.TARGET_DIST} u away` : "";''',
     '''    $("AHEAD_DIST").textContent = v.AHEAD_KIND && v.AHEAD_KIND !== "NOTHING" ? `${v.AHEAD_DIST} u` : "";'''),
])

edit("tools/run_report.py", [
    ('''modes = Counter(str((r.get("raw") or {}).get("NAV_MODE")) for r in ctrl if (r.get("raw") or {}).get("NAV_MODE") is not None)
if modes:
    print("  navigator: " + ", ".join(f"{k} {v}" for k, v in modes.most_common()))''',
     '''modes = Counter(str((r.get("raw") or {}).get("AHEAD_KIND")) for r in ctrl if (r.get("raw") or {}).get("AHEAD_KIND") is not None)
if modes:
    print("  at arm's length: " + ", ".join(f"{k} {v}" for k, v in modes.most_common()))
steer = Counter(r["answers"].get("steer") for r in ctrl if "steer" in r["answers"])
if steer:
    print("  steer:  " + ", ".join(f"{k} {v}" for k, v in steer.most_common()))'''),
])
