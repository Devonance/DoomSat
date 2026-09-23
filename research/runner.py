"""Run attempts and write the files the grader and the ledger read. Charter 5, phase 1.

Two tiers, one decision function:

  bench   ViZDoom in sync mode, driven in process, no F', no Yamcs. After each decision the game is
          advanced by a latency drawn from a real flight run, so the player waits exactly as long for an
          answer as it would in flight. Fast enough to run a dev set many times over.
  flight  the real stack. The runner does not own it: `scripts/flight.sh start` and the pilot do. What it
          does is the preflight, then turning the pilot's decision log into the same per-attempt files the
          bench writes, so both tiers grade identically.

Only flight results count toward the charter. The bench exists so that a hypothesis can be killed in
minutes instead of an afternoon, and charter 6.3 step 7 exists because a bench that disagrees with flight
is a harness bug, not a result.

    python research/runner.py bench  --set dev --seeds 1 2 3 --decider code --grade
    python research/runner.py bench  --set dev --decider jev --maps E1M1 --grade
    python research/runner.py flight --from-log out/decisions.jsonl --maps E1M1 E1M1 E1M2 --grade

This process is a pilot: it sets DOOMSAT_ROLE=pilot before importing anything, so an accidental import of
the grader raises instead of quietly working (honesty test 6). Grading runs separately, in grade.py.
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time
import uuid
from pathlib import Path

os.environ.setdefault("DOOMSAT_ROLE", "pilot")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "ground"))

import pinned                         # noqa: E402  run from a commit, not from the tree
import decision_graph as dg           # noqa: E402
import graph_config as gc             # noqa: E402
import targeting                      # noqa: E402

try:
    import yaml
except ImportError:                                            # noqa: BLE001
    raise SystemExit("PyYAML is needed to read research/levels.yaml: pip install pyyaml")

TICRATE = 35
DEFAULT_LATENCY_MS = [450.0]          # what a flight run measured before any log exists to sample


def config():
    return yaml.safe_load(open(HERE / "levels.yaml", encoding="utf-8"))


def sha_of(path):
    import hashlib
    return hashlib.sha1(open(path, "rb").read()).hexdigest()[:12]


def versions(cfg):
    def git(*a):
        try:
            return subprocess.check_output(["git"] + list(a), cwd=str(ROOT), text=True).strip()
        except Exception:                                      # noqa: BLE001
            return None
    return {"commit": git("rev-parse", "--short", "HEAD"),
            "pinned": os.environ.get("DOOMSAT_PINNED"),
            "dirty": bool(pinned.dirty_paths(ROOT)),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "graph_version": cfg.get("version"),
            "model": cfg.get("model"),
            "track": config()["track"],
            "levels_sha": sha_of(HERE / "levels.yaml"),
            "knowledge_sha": sha_of(ROOT / "knowledge" / "doom_rules.yaml"),
            "metrics_sha": sha_of(HERE / "frozen_metrics.py")}


# ---------------------------------------------------------------- deciders
class CodeDecider:
    """The rubric as an exact function: the null hypothesis every model answer has to beat.

    Charter phase 2 measures the executor with this in the loop, so that a gait result is not secretly a
    model result. It is the same rule tools/replay.py scores against, which is why it lives in
    decision_graph and not here.
    """
    name = "code"

    def __init__(self, cfg):
        self.cfg, self.levels = cfg, dg.levels_of(cfg)

    def ask(self, state, questions):
        out = dict(targeting.rule_answers(state, [q for q in questions if q[:2] in ("g_", "n_")]))
        for qid in questions:
            if qid in out:
                continue
            if qid.startswith("s_"):
                out[qid] = {"type": "score", "score": dg.rule_score(state["sectors"][qid[2:]], self.levels),
                            "confidence": 1.0}
            elif qid == "danger":
                hurt = state["player"]["health"] in ("critical", "low")
                close = state["combat"]["enemy_distance"] in ("point blank", "close")
                out[qid] = {"type": "score", "score": float(2 * close + hurt), "confidence": 1.0}
            elif qid == "goal":
                out[qid] = {"type": "choice", "choice": "Explore", "confidence": 1.0}
        return {"answers": out, "latency_ms": 0, "usage": {"input_tokens": 0}, "model": "code"}


def jev_decider(cfg, env_files):
    from providers import TypeSafeSystemOne, load_env_key
    key = load_env_key("TYPESAFE_API_KEY", env_files)
    if not key:
        raise SystemExit("TYPESAFE_API_KEY not set (env or ground/.env)")
    one = TypeSafeSystemOne(key, cfg["model"])       # pinned by the graph, so passes are comparable
    one.name = "jev"
    return one


# ---------------------------------------------------------------- the flight link, modelled
# What the F' component does to an observation on its way to Yamcs: rename a few fields and turn the
# integer enums into the names the ground sees. If this ever disagrees with the real thing, the bench and
# flight numbers diverge for a reason that has nothing to do with the pilot -- charter 6.3 step 7 calls
# that a harness bug, and tests/test_runner.py pins it against Doom.fpp.
RENAME = {"x": "POS_X", "y": "POS_Y", "health_item": "HEALTH_ITEM_DIST", "ammo_item": "AMMO_ITEM_DIST",
          "armor_item": "ARMOR_ITEM_DIST", "explored": "EXPLORED_CELLS", "cand_count": "CAND_COUNT",
          "threat_class": "THREAT_CLASS", "threat_count": "THREAT_COUNT",
          "door_presses_total": "DOOR_PRESSES", "door_opens_total": "DOOR_OPENS"}
BOOLS = {"own_shotgun", "stuck", "door_ahead", "dead", "level_done", "hint_active"}
AHEAD_KIND = ["NOTHING", "WALL", "DOOR", "EXIT", "LOCKED", "BARRIER", "THING"]
WEAPON = ["FIST", "PISTOL", "SHOTGUN", "OTHER"]
GOAL = ["EXPLORE", "KILL_ENEMY", "STOCK_AMMO", "RESTORE_HEALTH", "ADD_ARMOR", "UPGRADE_WEAPON", "SCOUT", "HOLD"]
ENUMS = {"ahead_kind": AHEAD_KIND, "weapon": WEAPON, "goal": GOAL}


CAND_FIELDS = ("kind", "x", "y", "dist", "novelty", "flags", "threat_class", "threat_count",
               "opening", "depth", "away")


def telemetry_from(o):
    """One payload observation as the ground would receive it."""
    t = {}
    for k, v in o.items():
        if k == "candidates":
            # the ground sees CAND0..CAND7 as aggregates, the way Yamcs delivers an F' struct
            for i, c in enumerate(v):
                t["CAND%d" % i] = dict(zip(CAND_FIELDS, c))
            continue
        name = RENAME.get(k, k.upper())
        if k in ENUMS:
            v = ENUMS[k][int(v)] if 0 <= int(v) < len(ENUMS[k]) else ENUMS[k][0]
        elif k in BOOLS:
            v = bool(v)
        t[name] = v
    return t


# ---------------------------------------------------------------- bench
FROZEN_LATENCY = HERE / "latency.json"


def latencies(path):
    """The decision latencies the bench plays back onto the game.

    Prefers `research/latency.json`, which is frozen and part of the ruler: a run that sampled a different
    pool waited a different length of time for its answers and is not comparable. Pinning found this --
    a run inside a git worktree has no out/decisions.jsonl, so it silently fell back to a single default
    sample and the player waited 450 ms instead of the measured 529.
    """
    if FROZEN_LATENCY.is_file():
        pool = json.load(open(FROZEN_LATENCY, encoding="utf-8")).get("samples") or []
        if pool:
            return pool
    out = []
    if path and os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("kind") == "control" and r.get("latency_ms"):
                out.append(float(r["latency_ms"]) + float(r.get("cmd_ms") or 0.0))
    return out or list(DEFAULT_LATENCY_MS)


def knowledge():
    return yaml.safe_load(open(ROOT / "knowledge" / "doom_rules.yaml", encoding="utf-8"))


def intent_bytes(it):
    """An intent as the uplink carries it. Same struct the payload unpacks, so the bench tests the packing."""
    import struct
    return struct.pack("!HIBffBBBBBBH", it["intent_id"], it["based_on_tic"],
                       targeting.MODE_INDEX.get(it["mode"], 0), it["target_x"], it["target_y"],
                       int(it["has_target"]), targeting.STANCE_INDEX.get(it["stance"], 0),
                       it["fire_policy"], it["fire_target_id"], it["weapon"],
                       int(it["use_at_target"]), it["ttl_ms"])


def bench_attempt(wad_path, map_name, seed, skill, budget_s, decider, graph, lat_pool, rng, verbose=False,
                  control="intent", geometry="off", oracle="off"):
    """One level attempt, in process. Returns the attempt record the grader eats."""
    sys.path.insert(0, str(ROOT / "payload"))
    import doom_payload as dp

    import argparse as _ap
    p = dp.Payload(_ap.Namespace(port=0, wad=wad_path, map=map_name, skill=skill, seed=seed,
                                 fps=0, quality=45, status_every=3, map_png=None,
                                 geometry=geometry, oracle=oracle))
    mem = dg.NavMemory(graph)
    tmem = targeting.TargetMemory(graph)
    cache = targeting.DecisionCache()      # charter 3.4: an identical state gets an identical action
    rules = knowledge()
    goal, rows, deaths, unavailable = "EXPLORE", [], 0, 0
    tic, n, t_wall = 0, 0, time.time()
    o, tic_ms = None, []
    end_reason, end_xy = "timeout", None
    start_xy = None
    while tic / TICRATE < budget_s:
        if p.game.is_episode_finished() or p.game.is_player_dead():
            if p.game.is_player_dead():
                deaths += 1
                # charter 8.1: retry the level, keep the clock running, and count it
                p.new_episode()
                mem, tmem = dg.NavMemory(graph), targeting.TargetMemory(graph)
                rows.append({"kind": "episode", "reason": "died", "t": time.time(), "tic": tic})
                continue
            end_reason = "exit"
            break
        state = p.game.get_state()
        if state is None:
            break
        if o is None:
            o = p.observe(state)          # the first one; after this the tic loop keeps it fresh
        if start_xy is None:
            start_xy = [o["x"], o["y"]]
        end_xy = [o["x"], o["y"]]
        t = telemetry_from(o)
        try:
            if control == "intent":
                cands = targeting.candidates_from(t)
                d = targeting.decide(t, cands, graph, tmem, decider, rules, n,
                                     ask_need=bool(graph["goal_every"]) and n % graph["goal_every"] == 0,
                                     cache=cache)
                # through the same uplink the flight stack uses, so the bench exercises the packing too
                p.handle(0x15, intent_bytes(d["intent"]))
                cmd = d["intent"]
                if d.get("unavailable"):
                    unavailable += 1
            else:
                d = dg.decide(t, graph, mem, goal, decider, n)
                if "goal" in d["answers"]:
                    goal = dg.GOAL_FROM_CHOICE.get(d["answers"]["goal"].get("choice"), goal)
                    p.goal = goal
                c = d["control"]
                p.control = dict(move=c["move"], strafe=c["strafe"], turn=c["turn"],
                                 fire=int(bool(c["fire"])), use=int(bool(c["use"])),
                                 weapon={"PISTOL": 1, "SHOTGUN": 2}.get(c["weapon"], 0))
                p.turn_remaining = c["turn"]
                p.last_control_time = time.time()
                cmd = c
        except Exception as e:                                 # noqa: BLE001
            import traceback
            rows.append({"kind": "error", "t": time.time(), "tic": tic, "error": str(e),
                         "traceback": traceback.format_exc()[-800:]})
            end_reason = "crash"
            break
        reply = d["reply"]
        rows.append({"t": tic / TICRATE, "kind": "control", "episode": o["episode"], "tic": tic,
                     "graph_version": graph.get("version"), "mode": d["mode"], "goal": goal,
                     "pick": d["pick"], "select": d["detail"],
                     "latency_ms": reply.get("latency_ms", 0), "cmd_ms": 0, "tel_age_ms": 0,
                     "model": reply.get("model"), "usage": reply.get("usage"),
                     # why this decision was or was not the model's; frozen_metrics.decision_reasons
                     # reads these, and without them "not jev" is one undifferentiated number
                     "cached": bool(d.get("cached")), "unavailable": d.get("unavailable"),
                     "answers": {k: dg.answer_label(v) for k, v in d["answers"].items()},
                     "control": cmd, "health": o["health"], "kills": o["kills"],
                     "candidates": int(t.get("CAND_COUNT", 0) or 0),
                     "cand_xy": [{"kind": c["kind"], "x": round(c["x"], 1), "y": round(c["y"], 1)}
                                 for c in (cands if control == "intent" else [])],
                     "raw": {k: t.get(k) for k in _RAW_KEYS}})
        n += 1
        # The game waits exactly as long for this answer as flight would -- and it SENSES the whole time,
        # which it did not until the 23 September brief pointed at it. The bench used to call observe()
        # once per decision and then run nineteen tics of make_action with nothing updating `exec_obs`,
        # so the executor steered nineteen tics on a stale position while the flight executor steered on
        # a fresh one every tic. That is not a slower robot, it is a different robot: measured on the
        # same seed of a dev map, 175 units/s and 29 cells against 95 and 23. Every constant tuned on the
        # old bench was tuned on something that does not fly.
        step = max(1, int(round(rng.choice(lat_pool) / 1000.0 * TICRATE)))
        for _ in range(step):
            if p.game.is_episode_finished() or p.game.is_player_dead():
                break
            st = p.game.get_state()
            if st is None:
                break
            t_tic = time.perf_counter()
            o = p.observe(st)
            p.game.make_action(p.action(tic), 1)
            tic_ms.append((time.perf_counter() - t_tic) * 1000.0)
            tic += 1
        if verbose and n % 50 == 0:
            print("    %s seed %d: %4d decisions, %5.1f game s, %s" % (map_name, seed, n, tic / TICRATE, d["mode"]),
                  flush=True)
    # Charter phase 2's exit test is about freezes, and a freeze is only visible as the watchdog having
    # had to step in. Counting the trips per attempt is the measurement; zero across 50 episodes is the bar.
    wd = dict(p.executor.watchdog.trips) if p.executor is not None else {}
    trip_log = list(p.executor.watchdog.trip_log)[:40] if p.executor is not None else []
    ex_stats = dict(p.executor.stats) if p.executor is not None else {}
    try:
        p.game.close()
    except Exception:                                          # noqa: BLE001
        pass
    geom_stats = p.geom.stats() if getattr(p, "geom", None) is not None else None
    # The tic loop's own cost. 1/35 s is 28.6 ms, so a p95 above that is a payload that cannot keep up
    # with the game even before F', JPEG and Yamcs are in the picture.
    tic_ms.sort()
    tic_cost = ({"n": len(tic_ms), "median_ms": round(tic_ms[len(tic_ms) // 2], 2),
                 "p95_ms": round(tic_ms[int(0.95 * (len(tic_ms) - 1))], 2),
                 "over_28_6_ms": round(sum(1 for v in tic_ms if v > 28.6) / len(tic_ms), 4),
                 "phases": {k: round(v * 1000.0 / max(1, len(tic_ms)), 3)
                            for k, v in sorted(p.phase_s.items(), key=lambda kv: -kv[1])}}
                if tic_ms else None)
    return {"tier": "bench", "wad_path": wad_path, "map": map_name, "seed": seed, "skill": skill,
            # ORACLE runs carry the rung they were flown on, and grade.py refuses to summarise them.
            # A diagnostic that can be mistaken for a result is worse than no diagnostic.
            "oracle": None if oracle == "off" else oracle, "geometry": geometry,
            "geometry_stats": geom_stats,
            "tic_rate": round(tic / max(1e-6, time.time() - t_wall), 1),
            "tic_cost": tic_cost,
            "watchdog_trips": wd, "watchdog_context": trip_log, "executor_stats": ex_stats,
            "model_unavailable": unavailable,
            "door_presses": int((rows[-1].get("raw") or {}).get("DOOR_PRESSES") or 0) if rows else 0,
            "door_opens": int((rows[-1].get("raw") or {}).get("DOOR_OPENS") or 0) if rows else 0,
            "budget_s": budget_s, "start_xy": start_xy, "end_xy": end_xy, "end_reason": end_reason,
            "game_seconds": round(tic / TICRATE, 2), "deaths": deaths, "wall_seconds": round(time.time() - t_wall, 1),
            "decider": getattr(decider, "name", "?"), "decisions": rows,
            "cache_hit_rate": round(cache.hit_rate, 4)}


_RAW_KEYS = ("CLEAR_FWD", "CLEAR_LEFT", "CLEAR_RIGHT", "CLEAR_BACK", "CLEAR_AL", "CLEAR_AR", "CLEAR_BL", "CLEAR_BR",
             "CLEAR_MAP_FWD", "NEW_FWD", "NEW_LEFT", "NEW_RIGHT", "NEW_BACK", "NEW_AL", "NEW_AR", "NEW_BL", "NEW_BR",
             "DOOR_FWD", "DOOR_AL", "DOOR_LEFT", "DOOR_BL", "DOOR_BACK", "DOOR_BR", "DOOR_RIGHT", "DOOR_AR",
             "AHEAD_KIND", "AHEAD_DIST", "EXIT_DIST", "EXIT_BEARING", "KEY_DIST", "KEY_BEARING",
             "DOOR_PRESSES", "DOOR_OPENS",
             "HEALTH_ITEM_DIST", "HEALTH_BEARING", "AMMO_ITEM_DIST", "AMMO_BEARING", "ARMOR_ITEM_DIST", "ARMOR_BEARING",
             "STUCK", "POS_X", "POS_Y", "ANGLE", "ENEMY_COUNT", "ENEMY_BEARING", "ENEMY_DIST",
             "HEALTH", "ARMOR", "SHELLS", "BULLETS", "WEAPON", "OWN_SHOTGUN",
             "EXPLORED_CELLS", "LEVEL", "LEVEL_DONE", "KEYS", "HINT_ACTIVE", "HINT_REL")


# ---------------------------------------------------------------- flight log -> attempts
def flight_attempts(log_path, wad_path, budget_s, skill, seed):
    """Split a pilot's decision log into one record per level attempt.

    The pilot logs a `level` row when a level is finished and an `episode` row when one ends, which is
    enough to cut the log without the runner having to have been watching.
    """
    rows = []
    for line in open(log_path, encoding="utf-8"):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    out, cur, deaths = [], [], 0
    level_no = None

    def close(reason):
        if not cur:
            return
        pos = [(r["raw"]["POS_X"], r["raw"]["POS_Y"]) for r in cur
               if r.get("kind") == "control" and (r.get("raw") or {}).get("POS_X") is not None]
        span = (cur[-1].get("t") or 0) - (cur[0].get("t") or 0)
        out.append({"tier": "flight", "wad_path": wad_path, "map": None, "seed": seed, "skill": skill,
                    "budget_s": budget_s, "start_xy": list(pos[0]) if pos else None,
                    "end_xy": list(pos[-1]) if pos else None, "end_reason": reason,
                    "game_seconds": round(span, 2), "deaths": deaths, "decider": "jev",
                    "decisions": list(cur)})

    for r in rows:
        kind = r.get("kind")
        if kind == "control":
            lv = (r.get("raw") or {}).get("LEVEL")
            if level_no is None:
                level_no = lv
            cur.append(r)
        elif kind == "level":
            close("exit")
            cur, deaths, level_no = [], 0, r.get("started")
        elif kind == "episode" and r.get("reason") == "died":
            deaths += 1
            cur.append(r)
    close("timeout")
    return out


# ---------------------------------------------------------------- driving it
def run_bench(a):
    conf = config()
    which = conf["dev_optional"] if a.set == "dev_optional" else conf[a.set]
    if a.set == "test" and not a.i_am_a_person:
        raise SystemExit("the test set is scored by a person at a milestone, never by the loop "
                         "(charter 2.5 and 5 phase 6). Pass --i-am-a-person if that is what this is.")
    graph = gc.load()
    decider = CodeDecider(graph) if a.decider == "code" else jev_decider(graph, a.env_files)
    maps = a.maps or which["maps"]
    seeds = a.seeds or conf["run"]["seeds"]
    budget = a.budget or conf["run"]["level_budget_s"]
    skill = a.skill or conf["run"]["skill"]
    wad_path = a.wad or os.path.join(conf["run"]["wad_dir"], which["wad"])
    lat_pool = latencies(a.latency_log)
    rng = random.Random(20260922)
    run_id = a.run_id or ("%s-%s-%s" % (time.strftime("%Y%m%dT%H%M%S"), a.decider, uuid.uuid4().hex[:4]))
    out_dir = Path(a.out or (HERE / "out" / run_id))
    out_dir.mkdir(parents=True, exist_ok=True)
    vers = versions(graph)
    print("run %s: %s %s, maps %s, seeds %s, budget %ds, skill %d, decider %s%s"
          % (run_id, a.set, which["wad"], ",".join(maps), seeds, budget, skill, a.decider,
             "" if a.oracle == "off" else ("  ORACLE %s -- diagnostic, never scored" % a.oracle)), flush=True)
    print("latency pool: %d samples, median %.0f ms  (frozen in research/latency.json)"
          % (len(lat_pool), sorted(lat_pool)[len(lat_pool) // 2]), flush=True)
    made = []
    for map_name in maps:
        for seed in seeds:
            t0 = time.time()
            att = bench_attempt(wad_path, map_name, seed, skill, budget, decider, graph, lat_pool, rng,
                                a.verbose, control=a.control, geometry=a.geometry, oracle=a.oracle)
            att.update({"run_id": run_id, "versions": vers,
                        # per attempt, not just per run: the bench starts a fresh payload each time, so
                        # "which code ran" is an attempt-level fact
                        "commit": vers.get("pinned") or vers.get("commit"),
                        "dirty": vers.get("dirty")})
            path = out_dir / ("attempt-%s-%s.json" % (map_name, seed))
            json.dump(att, open(path, "w", encoding="utf-8"))
            made.append(str(path))
            print("  %-6s seed %-3d %-8s %5.1f game s, %4d decisions, %d deaths, %.0f s wall"
                  % (map_name, seed, att["end_reason"], att["game_seconds"], len(att["decisions"]),
                     att["deaths"], time.time() - t0), flush=True)
    json.dump({"run_id": run_id, "tier": "bench", "set": a.set, "decider": a.decider, "versions": vers,
               "attempts": made}, open(out_dir / "run.json", "w", encoding="utf-8"), indent=1)
    print("\n%d attempts in %s" % (len(made), out_dir), flush=True)
    return grade(out_dir) if a.grade else print_next(out_dir)


def print_next(out_dir):
    print("now: python research/grade.py %s" % out_dir, flush=True)
    return 0


def grade(out_dir):
    """Grade in a separate process, with the pilot role dropped, using the CURRENT harness.

    Two separations, both load-bearing. The grader reads the level file, so it cannot run in here: this
    process declared itself a pilot before it imported anything (honesty test 6). And when the run is
    pinned, the pilot code comes from the worktree but the grader must not -- the ruler is one version
    across every experiment, or two rows were scored by two different rulers. `DOOMSAT_HARNESS` is the
    main checkout; without it a pinned run would grade itself with whatever grader that commit happened
    to carry, which is how m1-base came back with no deaths_by_mode.
    """
    env = {k: v for k, v in os.environ.items() if k != "DOOMSAT_ROLE"}
    harness = Path(os.environ.get("DOOMSAT_HARNESS") or ROOT)
    print(flush=True)
    return subprocess.call([sys.executable, str(harness / "research" / "grade.py"), str(out_dir)],
                           env=env, cwd=str(harness))


def run_flight(a):
    conf = config()
    budget = a.budget or conf["run"]["level_budget_s"]
    wad_path = a.wad or os.path.join(conf["run"]["wad_dir"], conf["test"]["wad"])
    run_id = a.run_id or ("%s-flight-%s" % (time.strftime("%Y%m%dT%H%M%S"), uuid.uuid4().hex[:4]))
    out_dir = Path(a.out or (HERE / "out" / run_id))
    out_dir.mkdir(parents=True, exist_ok=True)
    atts = flight_attempts(a.from_log, wad_path, budget, a.skill or conf["run"]["skill"], a.seeds[0] if a.seeds else 0)
    vers = versions(gc.load())
    made = []
    for i, att in enumerate(atts):
        att["map"] = a.maps[i] if a.maps and i < len(a.maps) else (a.maps[-1] if a.maps else None)
        if att["map"] is None:
            raise SystemExit("flight attempts carry a level number, not a map name: pass --maps in the order "
                             "they were played, e.g. --maps E1M1 E1M1 E1M2")
        att.update({"run_id": run_id, "versions": vers})
        path = out_dir / ("attempt-%s-%d.json" % (att["map"], i))
        att["seed"] = i
        json.dump(att, open(path, "w", encoding="utf-8"))
        made.append(str(path))
        print("  attempt %d: %s %s %.0f s, %d decisions" % (i, att["map"], att["end_reason"],
                                                            att["game_seconds"], len(att["decisions"])))
    json.dump({"run_id": run_id, "tier": "flight", "versions": vers, "attempts": made},
              open(out_dir / "run.json", "w", encoding="utf-8"), indent=1)
    print("\n%d attempts in %s" % (len(made), out_dir))
    return grade(out_dir) if a.grade else print_next(out_dir)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="tier", required=True)
    for name in ("bench", "flight"):
        s = sub.add_parser(name)
        s.add_argument("--set", default="dev", choices=["dev", "dev_optional", "test"])
        s.add_argument("--maps", nargs="*", default=None)
        s.add_argument("--seeds", nargs="*", type=int, default=None)
        s.add_argument("--skill", type=int, default=None)
        s.add_argument("--budget", type=float, default=None)
        s.add_argument("--wad", default=None)
        s.add_argument("--out", default=None)
        s.add_argument("--run-id", default=None)
        s.add_argument("--verbose", action="store_true")
        s.add_argument("--pin", default=None, metavar="COMMIT",
                       help="check this commit out into its own git worktree and measure there, so the "
                            "row can be re-run and mean the same thing. HEAD is usually what you want.")
        s.add_argument("--pinned-at", default=None, help=argparse.SUPPRESS)
        s.add_argument("--allow-dirty", action="store_true",
                       help="a scratch run from an uncommitted tree; recorded in the attempt so a row "
                            "built from one is obvious")
        s.add_argument("--i-am-a-person", action="store_true", help="required to touch the test set")
        s.add_argument("--grade", action="store_true",
                       help="grade the run when it finishes, in a separate process (charter phase 1: one "
                            "command turns a commit into a graded run)")
        s.add_argument("--geometry", default="off", choices=["off", "on"],
                       help="exact lines from the engine, released only once the automap has drawn them")
        s.add_argument("--oracle", default="off", choices=["off", "L0", "L1", "L2"],
                       help="the diagnostic ladder of the 23 September brief. Never scored: every "
                            "attempt is stamped with its rung and grade.py refuses to summarise it.")
        s.add_argument("--control", default="intent", choices=["intent", "legacy"],
                       help="intent: the charter's executor with an INTENT and a TTL. legacy: the "
                            "pre-charter CONTROL command every tick, kept so the two can be compared.")
        if name == "bench":
            s.add_argument("--decider", default="code", choices=["code", "jev"])
            s.add_argument("--latency-log", default=str(ROOT / "out" / "decisions.jsonl"),
                           help="flight log to draw decision latencies from")
            s.add_argument("--env-files", nargs="*", default=[str(ROOT / "ground" / ".env"), str(ROOT / ".env")])
        else:
            s.add_argument("--from-log", required=True)
    a = ap.parse_args(argv)
    handed_off = pinned.prepare(a, list(argv if argv is not None else sys.argv[1:]), ROOT)
    if handed_off is not None:
        return handed_off
    return run_bench(a) if a.tier == "bench" else run_flight(a)


if __name__ == "__main__":
    raise SystemExit(main())
