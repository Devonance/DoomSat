"""The ground pilot: plays Doom through Yamcs.

  telemetry (Yamcs WebSocket)  -> words -> System One (jev): 7 control heads -> CONTROL command (Yamcs -> F Prime)
  frames (FRAME_CHUNK records)  -> reassembled JPEG -> Yamcs bucket + DoomFrame parameter (Open MCT imagery)
  every few seconds / on events -> System Two (Claude Sonnet 5): goal + rationale -> SET_GOAL command

Code owns the loop, the thresholds and the command mapping; the models only answer questions.
Run with --help for provider options (TypeSafe / OpenAI-compatible System One; Claude CLI /
Anthropic API / OpenAI-compatible System Two).
"""
import argparse
import json
import os
import struct
import sys
import threading
import time
from collections import deque
from pathlib import Path

from yamcs.client import YamcsClient

import decision_graph as dg
from providers import make_system_one, make_system_two

HERE = Path(__file__).resolve().parent
SPACE_SYSTEM = "/DoomSat_DoomSat/DoomSat/doom"
GROUND = "/DoomGround"
STATUS_CHANNELS = ["HEALTH", "ARMOR", "SHELLS", "BULLETS", "WEAPON", "OWN_SHOTGUN", "KILLS", "POS_X", "POS_Y", "ANGLE",
                   "ENEMY_COUNT", "ENEMY_BEARING", "ENEMY_DIST", "CLEAR_FWD", "CLEAR_LEFT", "CLEAR_RIGHT", "CLEAR_BACK",
                   "ROUTE_BEARING", "ROUTE_DIST", "TARGET_DIST", "TARGET_KIND", "STUCK", "DOOR_AHEAD", "GOAL",
                   "HEALTH_ITEM_DIST", "AMMO_ITEM_DIST", "ARMOR_ITEM_DIST", "TIC", "EPISODE", "DEAD", "LEVEL_DONE",
                   "FRAMES_SENT", "CHUNKS_SENT", "FRAME_BYTES", "PAYLOAD_LINK", "CMDS_RECEIVED", "EXPLORED_CELLS", "FRONTIERS"]
CHUNK_HEADER = struct.Struct("!IHHH")  # seq, index, count, length (then 960 data bytes)


class FrameAssembler:
    """Puts FRAME_CHUNK records back together into JPEG files; tolerates loss and reordering."""

    def __init__(self, out_dir):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.partial = {}
        self.complete = 0
        self.incomplete = 0
        self.last_path = None
        self.last_seq = 0
        self.last_bytes = 0

    def add(self, value, generation_time):
        raw = value if isinstance(value, (bytes, bytearray)) else self._from_aggregate(value)
        if raw is None or len(raw) < CHUNK_HEADER.size:
            return None
        seq, index, count, length = CHUNK_HEADER.unpack_from(raw)
        data = bytes(raw[CHUNK_HEADER.size:CHUNK_HEADER.size + length])
        frame = self.partial.setdefault(seq, {"count": count, "parts": {}, "t0": time.time()})
        frame["parts"][index] = data
        done = None
        if len(frame["parts"]) == count:
            jpeg = b"".join(frame["parts"][i] for i in range(count))
            path = self.out_dir / f"frame-{seq:06d}.jpg"
            path.write_bytes(jpeg)
            (self.out_dir / "latest.jpg").write_bytes(jpeg)
            self.complete += 1
            self.last_path, self.last_seq, self.last_bytes = path, seq, len(jpeg)
            del self.partial[seq]
            done = (seq, path, len(jpeg), generation_time)
        # forget frames older than the newest complete one by more than a few seconds
        for old in [s for s, f in self.partial.items() if time.time() - f["t0"] > 3.0]:
            self.incomplete += 1
            del self.partial[old]
        return done

    @staticmethod
    def _from_aggregate(value):
        """Fallback when the XTCE decodes FrameChunk as an aggregate with an array member."""
        try:
            d = value if isinstance(value, dict) else dict(value)
            data = d["data"] if isinstance(d["data"], (bytes, bytearray)) else bytes(int(b) & 0xFF for b in d["data"])
            return CHUNK_HEADER.pack(int(d["seq"]), int(d["index"]), int(d["count"]), int(d["length"])) + data
        except Exception:
            return None


class Pilot:
    def __init__(self, args):
        self.args = args
        self.client = YamcsClient(args.yamcs)
        self.instance = args.instance
        self.processor = self.client.get_processor(args.instance, "realtime")
        self.system_one = make_system_one(args.system_one, args)
        self.system_two = make_system_two(args.system_two, args)
        self.telemetry = {}
        self.telemetry_time = 0.0
        self.frames = FrameAssembler(args.out_dir / "frames")
        self.goal = "EXPLORE"
        self.standing_order = args.standing_order
        self.plan = {"goal": self.goal, "rationale": "initial standing order", "model": "code"}
        self.last_plan_time = 0.0
        self.planned_episode = None
        self.progress_mark = (time.time(), 0)
        self.plan_busy = False
        self.control_count = 0
        self.resubscribes = 0
        self.subscription = None
        self.log = open(args.out_dir / "decisions.jsonl", "a", buffering=1, encoding="utf-8")
        self.recent_health = deque(maxlen=20)
        self.last_enemy_seen = 0.0
        self.stuck_since = None
        self.bucket = self._ensure_bucket()
        args.out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ Yamcs plumbing
    def _ensure_bucket(self):
        storage = self.client.get_storage_client()
        for b in storage.list_buckets():
            if b.name == "doomframes":
                return b
        storage.create_bucket("doomframes")
        return storage.get_bucket("doomframes")

    def subscribe(self):
        names = [f"{SPACE_SYSTEM}/{c}" for c in STATUS_CHANNELS + ["FRAME_CHUNK"]]
        self.subscription = self.processor.create_parameter_subscription(names, on_data=self.on_data)
        self.telemetry_time = time.time()

    def resubscribe(self):
        """The Yamcs WebSocket drops now and then; rebuild the client and the subscription."""
        try:
            self.subscription.cancel()
        except Exception:
            pass
        try:
            self.client = YamcsClient(self.args.yamcs)
            self.processor = self.client.get_processor(self.instance, "realtime")
            self.subscribe()
            self.resubscribes += 1
            print(f"[pilot] telemetry went stale: resubscribed (#{self.resubscribes})", flush=True)
        except Exception as e:
            print(f"[pilot] resubscribe failed: {e}", file=sys.stderr)

    def on_data(self, data):
        for pv in data.parameters:
            name = pv.name.rsplit("/", 1)[-1]
            if name == "FRAME_CHUNK":
                done = self.frames.add(pv.raw_value if pv.raw_value is not None else pv.eng_value, pv.generation_time)
                if done:
                    self.publish_frame(*done)
            else:
                v = pv.eng_value
                if v == "True" or v == "False":  # F´ bools arrive as enumerated strings; "False" must not be truthy
                    v = v == "True"
                self.telemetry[name] = v
                self.telemetry_time = time.time()
                if name == "HEALTH":
                    self.recent_health.append(v)
                if name == "ENEMY_COUNT" and v:
                    self.last_enemy_seen = time.time()

    def publish_frame(self, seq, path, nbytes, gen_time):
        name = f"frame-{seq:06d}.jpg"
        try:
            with open(path, "rb") as f:
                self.bucket.upload_object(name, f)
            url = f"{self.args.yamcs_public}/api/buckets/{self.instance}/doomframes/objects/{name}"
            self.set_ground({"DoomFrame": url, "FrameSeq": seq, "FramesComplete": self.frames.complete,
                             "FramesIncomplete": self.frames.incomplete})
            if seq > 40:  # keep the bucket small
                try:
                    self.bucket.delete_object(f"frame-{seq - 40:06d}.jpg")
                    (self.frames.out_dir / f"frame-{seq - 40:06d}.jpg").unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception as e:
            print(f"[pilot] frame publish failed: {e}", file=sys.stderr)

    def set_ground(self, values):
        try:
            for k, v in values.items():
                self.processor.set_parameter_value(f"{GROUND}/{k}", v)
        except Exception as e:
            print(f"[pilot] ground parameter set failed: {e}", file=sys.stderr)

    def command(self, name, args=None):
        return self.processor.issue_command(f"{SPACE_SYSTEM}/{name}", args=args or {})

    # ------------------------------------------------------------ System One loop
    def control_step(self):
        if time.time() - self.telemetry_time > 4.0:
            self.resubscribe()
            return None
        if time.time() - self.telemetry_time > 2.0:
            return None  # stale telemetry: hold what the payload holds (its own uplink timeout releases controls)
        t = dict(self.telemetry)
        state = dg.build_state(t, self.goal, self.standing_order)
        questions = dg.control_questions(t, self.goal)
        if self.system_two is None:
            questions.update(dg.goal_question(t))  # System One plans only when there is no System Two
        reply = self.system_one.ask(state, questions)
        answers = reply["answers"]
        cargs = dg.control_args(answers)
        self.command("CONTROL", cargs)
        self.control_count += 1
        if "goal" in answers and self.system_two is None:
            self.set_goal(dg.GOAL_FROM_CHOICE.get(answers["goal"]["choice"], self.goal), "jev", answers["goal"])
        row = {"t": time.time(), "kind": "control", "latency_ms": reply["latency_ms"], "model": reply.get("model"),
               "request_id": reply.get("request_id"), "usage": reply.get("usage"),
               "answers": {k: v.get("choice") for k, v in answers.items()},
               "confidence": {k: round(v.get("confidence", 0.0), 2) for k, v in answers.items()},
               "control": cargs, "goal": self.goal, "health": t.get("HEALTH"), "tic": t.get("TIC"),
               "seen": state["navigation"], "raw": {k: t.get(k) for k in ("ROUTE_BEARING", "CLEAR_FWD", "CLEAR_LEFT", "CLEAR_RIGHT", "STUCK", "POS_X", "POS_Y", "ANGLE")}}
        self.log.write(json.dumps(row) + "\n")
        summary = " ".join(f"{k}={v['choice']}" for k, v in answers.items() if k in dg.CONTROL_HEADS)
        self.set_ground({"SystemOneLatencyMs": float(reply["latency_ms"]), "ControlCommands": self.control_count,
                         "Controls": summary})
        return row

    def set_goal(self, goal, who, detail=None):
        if goal not in dg.GOALS:
            return
        if goal != self.goal:
            self.command("SET_GOAL", {"goal": goal})
            print(f"[pilot] goal {self.goal} -> {goal} ({who})", flush=True)
        self.goal = goal

    # ------------------------------------------------------------ System Two loop
    def plan_trigger(self):
        """System Two is for strategy: once per episode, then only when code sees a reason."""
        t = self.telemetry
        now = time.time()
        if self.plan_busy or not t:
            return None
        episode = t.get("EPISODE", 0)
        if episode != self.planned_episode:
            self.planned_episode = episode
            self.progress_mark = (now, t.get("EXPLORED_CELLS", 0))
            return "new episode: level strategy"
        if now - self.last_plan_time < self.args.plan_floor:
            return None
        if len(self.recent_health) >= 2 and self.recent_health[0] - self.recent_health[-1] >= 25:
            return "health dropped"
        explored = t.get("EXPLORED_CELLS", 0)
        mark_t, mark_cells = self.progress_mark
        if explored > mark_cells:
            self.progress_mark = (now, explored)
        elif now - mark_t > self.args.no_progress and not t.get("ENEMY_COUNT", 0):
            self.progress_mark = (now, explored)
            return "no progress"
        if self.args.plan_every and now - self.last_plan_time > self.args.plan_every:
            return "periodic"
        return None

    def plan_step(self, reason):
        self.plan_busy = True
        self.last_plan_time = time.time()
        try:
            t = dict(self.telemetry)
            situation = dg.build_state(t, self.goal, self.standing_order)
            situation["why_asked"] = reason
            situation["last_plan"] = {"goal": self.plan.get("goal"), "rationale": self.plan.get("rationale")}
            situation["downlink"] = {"frames_complete": self.frames.complete, "frames_incomplete": self.frames.incomplete,
                                     "last_frame_age_s": round(time.time() - os.path.getmtime(self.frames.last_path), 1) if self.frames.last_path else None}
            plan = self.system_two.plan(situation, str(self.frames.last_path) if self.frames.last_path and self.args.vision else None)
            self.plan = plan
            self.set_goal(plan.get("goal", self.goal), self.system_two.name, plan)
            hint = {"ahead": 0, "left": 60, "right": -60, "behind": 180}.get(plan.get("steer_hint"))
            if hint is not None:
                self.command("EXPLORE_HINT", {"bearing": hint, "ttl": 25})
            if plan.get("frame_rate_hz") is not None:
                self.command("FRAME_RATE", {"hz": int(plan["frame_rate_hz"]), "quality": self.args.quality})
            row = {"t": time.time(), "kind": "plan", "reason": reason, **{k: v for k, v in plan.items()}}
            self.log.write(json.dumps(row) + "\n")
            self.set_ground({"SystemTwoLatencyMs": float(plan.get("latency_ms", 0)),
                             "Plan": f"{plan.get('goal')}{(' / steer ' + plan['steer_hint']) if plan.get('steer_hint') not in (None, 'none') else ''}: {plan.get('rationale', '')} {('[frame: ' + plan['frame_note'] + ']') if plan.get('frame_note') else ''}"})
            print(f"[pilot] plan ({reason}, {plan.get('latency_ms')} ms, {plan.get('model')}): {plan.get('goal')} - {plan.get('rationale')}", flush=True)
        except Exception as e:
            print(f"[pilot] System Two failed: {e}", file=sys.stderr)
            self.log.write(json.dumps({"t": time.time(), "kind": "plan_error", "error": str(e)}) + "\n")
        finally:
            self.plan_busy = False

    # ------------------------------------------------------------ main
    def run(self):
        self.subscribe()
        key = getattr(self.system_one, "api_key", "")
        print(f"[pilot] subscribed; System One = {self.system_one.name} (key {key[:14]}...), System Two = {self.system_two.name if self.system_two else 'none'} ({getattr(self.system_two, 'model', '-')})", flush=True)
        self.command("FRAME_RATE", {"hz": self.args.fps, "quality": self.args.quality})
        self.command("SET_GOAL", {"goal": self.goal})
        deadline = time.time() + self.args.duration if self.args.duration else None
        n = 0
        while deadline is None or time.time() < deadline:
            t0 = time.time()
            try:
                row = self.control_step()
            except Exception as e:
                row = None
                print(f"[pilot] System One failed: {e}", file=sys.stderr)
                time.sleep(1.0)
            if self.system_two is not None:
                reason = self.plan_trigger()
                if reason:
                    threading.Thread(target=self.plan_step, args=(reason,), daemon=True).start()
            n += 1
            if row and n % 10 == 0:
                print(f"[pilot] #{n} {row['latency_ms']} ms  hp={row['health']} goal={self.goal} "
                      f"{' '.join(f'{k}={v}' for k, v in row['answers'].items() if k in dg.CONTROL_HEADS)}  "
                      f"frames ok={self.frames.complete} lost={self.frames.incomplete}", flush=True)
            remaining = self.args.period - (time.time() - t0)
            if remaining > 0:
                time.sleep(remaining)
        self.command("CONTROL", dg.control_args({}))
        print("[pilot] done", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--yamcs", default="localhost:8090", help="Yamcs host:port for the client")
    p.add_argument("--yamcs-public", default="http://localhost:8090", help="Yamcs base URL as the browser reaches it (frame URLs)")
    p.add_argument("--instance", default="fprime-project")
    p.add_argument("--system-one", default="typesafe", choices=["typesafe", "openai"])
    p.add_argument("--system-one-model", default=None)
    p.add_argument("--system-two", default="claude-cli", choices=["claude-cli", "anthropic", "openai", "none"])
    p.add_argument("--system-two-model", default=None, help="e.g. sonnet (CLI alias), claude-sonnet-5, gpt-4o")
    p.add_argument("--openai-base-url", default=os.environ.get("OPENAI_BASE_URL", "http://localhost:1234/v1"))
    p.add_argument("--env-files", nargs="*", default=[str(HERE / ".env"), str(HERE.parent / ".env"),
                                                       str(HERE.parent.parent / "typesafe-decision-game" / ".env")])
    p.add_argument("--period", type=float, default=0.25, help="seconds between control decisions (lower bound)")
    p.add_argument("--plan-every", type=float, default=0.0, help="periodic System Two plans every N seconds (0 = triggers only)")
    p.add_argument("--plan-floor", type=float, default=30.0, help="minimum seconds between System Two plans")
    p.add_argument("--no-progress", type=float, default=20.0, help="seconds without new map cells before asking System Two")
    p.add_argument("--no-vision", dest="vision", action="store_false", help="do not show System Two the last frame")
    p.add_argument("--fps", type=int, default=10)
    p.add_argument("--quality", type=int, default=45)
    p.add_argument("--duration", type=float, default=0.0, help="stop after this many seconds (0 = run forever)")
    p.add_argument("--standing-order", default="Find the level exit alive; fight what blocks the way; pick up supplies when they are needed.")
    p.add_argument("--out-dir", type=Path, default=HERE.parent / "out")
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    Pilot(args).run()


if __name__ == "__main__":
    main()
