"""One-off patch: map products through the frame path, stall detection with a System Two bump, walk summary."""
import ast

p = "ground/pilot.py"
s = open(p, encoding="utf-8").read()


def rep(old, new):
    global s
    assert old in s, old[:80]
    s = s.replace(old, new, 1)


rep('''        seq, index, count, length = CHUNK_HEADER.unpack_from(raw)
        frame = self.partial.setdefault(seq, {"count": count, "parts": {}, "t0": time.time()})
        frame["parts"][index] = bytes(raw[CHUNK_HEADER.size:CHUNK_HEADER.size + length])
        done = None
        if len(frame["parts"]) == count:
            jpeg = b"".join(frame["parts"][i] for i in range(count))
            path = self.out_dir / f"frame-{seq:06d}.jpg"
            path.write_bytes(jpeg)
            (self.out_dir / "latest.jpg").write_bytes(jpeg)
            self.complete += 1
            self.last_path = path
            del self.partial[seq]
            done = (seq, path)''',
    '''        seq, index, count, length = CHUNK_HEADER.unpack_from(raw)
        frame = self.partial.setdefault(seq, {"count": count, "parts": {}, "t0": time.time()})
        frame["parts"][index] = bytes(raw[CHUNK_HEADER.size:CHUNK_HEADER.size + length])
        done = None
        if len(frame["parts"]) == count:
            data = b"".join(frame["parts"][i] for i in range(count))
            if seq & 0x80000000:   # the navigator's map, a PNG product
                path = self.out_dir / "latest_map.png"
                path.write_bytes(data)
                self.maps += 1
            else:
                path = self.out_dir / f"frame-{seq:06d}.jpg"
                path.write_bytes(data)
                (self.out_dir / "latest.jpg").write_bytes(data)
                self.complete += 1
                self.last_path = path
            del self.partial[seq]
            done = (seq, path)''')
rep('''        self.complete = 0
        self.incomplete = 0
        self.last_path = None''', '''        self.complete = 0
        self.incomplete = 0
        self.maps = 0
        self.last_path = None''')
rep('''    def publish_frame(self, seq, path):
        """Put the image product in the Yamcs bucket for Open MCT, at most twice a second."""
        if time.time() - self.last_publish < 0.5:
            return''', '''    def publish_frame(self, seq, path):
        """Put the image product in the Yamcs bucket for Open MCT, at most twice a second (maps: every time)."""
        if seq & 0x80000000:
            try:
                with open(path, "rb") as f:
                    self.bucket.upload_object("map.png", f)
                self.set_ground({"DoomMap": f"{self.args.yamcs_public}/api/buckets/{self.instance}/doomframes/objects/map.png?s={seq & 0xFFFF}"})
            except Exception as e:
                print(f"[pilot] map publish failed: {e}", file=sys.stderr)
            return
        if time.time() - self.last_publish < 0.5:
            return''')
rep('''        self.review_busy = False
        self.bucket = self._ensure_bucket()''', '''        self.review_busy = False
        self.progress = []           # (time, explored cells, level) samples for stall detection
        self.last_hint_t = 0.0
        self.bucket = self._ensure_bucket()''')

STALL = '''    # ------------------------------------------------------------ System Two: a bump when the walk stalls
    def check_stall(self):
        """No new map cells for a while and no level change: ask System Two which way to push exploration."""
        t = self.telemetry
        if "EXPLORED_CELLS" not in t or self.system_two is None:
            return
        now = time.time()
        self.progress.append((now, int(t.get("EXPLORED_CELLS", 0)), t.get("LEVEL")))
        self.progress = [p for p in self.progress if now - p[0] < 120.0]
        old = [p for p in self.progress if now - p[0] >= 90.0]
        if not old or self.review_busy or now - self.last_hint_t < 150.0:
            return
        if self.progress[-1][1] > old[0][1] + 3 or self.progress[-1][2] != old[0][2]:
            return
        self.last_hint_t = now
        self.review_busy = True
        threading.Thread(target=self.stall_consult, daemon=True).start()

    def ascii_map(self, path, cols=72):
        """The navigator's map product as text Sonnet can read: # wall, . seen floor, o walked, F frontier, P player."""
        try:
            from PIL import Image
            im = Image.open(path).convert("RGB")
        except Exception:
            return None
        w, h = im.size
        step = max(1, w // cols)
        rows = []
        for yy in range(0, h, step):
            line = ""
            for xx in range(0, w, step):
                r, g, b = im.getpixel((min(xx + step // 2, w - 1), min(yy + step // 2, h - 1)))
                if r > 200 and g < 100 and b < 100:
                    line += "P"
                elif r > 200 and g > 150 and b < 100:
                    line += "F"
                elif r > 180 and g > 180 and b > 180:
                    line += "#"
                elif g > r + 30 and g > b + 30:
                    line += "o"
                elif r + g + b > 150:
                    line += "."
                else:
                    line += " "
            rows.append(line.rstrip())
        return "\\n".join(rows)

    def stall_consult(self):
        try:
            from collections import Counter
            t = dict(self.telemetry)
            recent = [r for r in self.rows[-240:] if r.get("kind") == "control" and r.get("raw")]
            pts = [(round(r["raw"]["POS_X"] / 64) * 64, round(r["raw"]["POS_Y"] / 64) * 64) for r in recent if r["raw"].get("POS_X") is not None]
            path = [f"({x},{y}) x{n}" for (x, y), n in Counter(pts).most_common(8)]
            amap = self.ascii_map(self.frames.out_dir / "latest_map.png")
            prompt = ("The player has made no exploration progress for 90 s. Position ({:.0f}, {:.0f}), heading {:.0f} degrees "
                      "(0 = east, 90 = north). Level {}. Navigator: {}. Frontiers: {}. Doors seen: {}. Keys: {}.\\n"
                      "Where the walk has been in the last two minutes (64-unit bins, most visited first): {}.\\n"
                      "Map the navigator built (# wall, . seen floor, o walked, F unexplored edge, P player; north is up):\\n{}\\n\\n"
                      "Pick a compass direction to push exploration toward unexplored space away from the well-trodden area, "
                      "as a bearing in degrees (0 east, 90 north, 180 west, 270 south), how many seconds to hold it, and the "
                      "goal to set. One sentence of reasoning.").format(
                t.get("POS_X", 0), t.get("POS_Y", 0), t.get("ANGLE", 0), t.get("LEVEL"), t.get("NAV_MODE"), t.get("FRONTIERS"),
                t.get("DOORS_KNOWN"), t.get("KEYS"), path, amap or "(no map product yet)")
            schema = {"type": "object", "properties": {"bearing_deg": {"type": "integer"}, "hold_s": {"type": "integer"},
                                                       "goal": {"type": "string", "enum": ["Explore", "Scout"]},
                                                       "reason": {"type": "string", "maxLength": 300}},
                      "required": ["bearing_deg", "hold_s", "reason"], "additionalProperties": False}
            t0 = time.time()
            r = self.system_two.structured("You are the mission's System Two. The fast model plays; you only redirect exploration "
                                           "when it stalls. Answer from the map.", prompt, schema)
            rel = int(round((r["bearing_deg"] - float(t.get("ANGLE", 0)) + 180) % 360 - 180))
            ttl = int(max(20, min(120, r.get("hold_s", 60))))
            self.command("EXPLORE_HINT", {"bearing": rel, "ttl": ttl})
            if r.get("goal") == "Scout":
                self.set_goal("SCOUT")
            row = {"t": time.time(), "kind": "system_two_hint", "bearing_deg": r["bearing_deg"], "relative": rel, "ttl": ttl,
                   "goal": r.get("goal"), "reason": r.get("reason"), "latency_ms": int((time.time() - t0) * 1000),
                   "model": r.get("model"), "cost_usd": r.get("cost_usd"), "path": path}
            self.log.write(json.dumps(row) + "\\n")
            self.rows.append(row)
            self.set_ground({"SystemTwoHint": f"push {r['bearing_deg']} deg for {ttl} s: {r.get('reason')}"[:900],
                             "SystemTwoLatencyMs": float(row["latency_ms"])})
            print(f"[pilot] System Two bump: bearing {r['bearing_deg']} deg (relative {rel:+d}) for {ttl} s, goal {r.get('goal')}: "
                  f"{r.get('reason')}", flush=True)
        except Exception as e:
            print(f"[pilot] stall consult failed: {e}", file=sys.stderr)
        finally:
            self.review_busy = False

    # ------------------------------------------------------------ System Two: after-action review'''
rep('''    # ------------------------------------------------------------ System Two: after-action review''', STALL)
rep('''            n += 1
            if row and n % 10 == 0:''', '''            n += 1
            if n % 20 == 0:
                self.check_stall()
            if row and n % 10 == 0:''')
open(p, "w", encoding="utf-8", newline="\n").write(s)
ast.parse(s)
print("pilot ok")

p = "ground/after_action.py"
s = open(p, encoding="utf-8").read()
old = '''    modes = Counter(str(r.get("NAV_MODE")) for r in raw if r.get("NAV_MODE") is not None)'''
new = '''    modes = Counter(str(r.get("NAV_MODE")) for r in raw if r.get("NAV_MODE") is not None)
    bins = Counter((round(r["POS_X"] / 128) * 128, round(r["POS_Y"] / 128) * 128) for r in raw if r.get("POS_X") is not None)
    walk = {"distinct_128u_bins": len(bins), "revisit_ratio": round(1 - len(bins) / max(1, len(raw)), 2),
            "most_visited": [f"({x},{y}) x{n}" for (x, y), n in bins.most_common(5)],
            "hints_from_system_two": sum(1 for r in episode_rows if r.get("kind") == "system_two_hint")}'''
assert old in s
s = s.replace(old, new, 1)
old2 = '''        "navigator_modes_ticks": dict(modes.most_common()),'''
new2 = '''        "navigator_modes_ticks": dict(modes.most_common()),
        "walk": walk,'''
assert old2 in s
s = s.replace(old2, new2, 1)
open(p, "w", encoding="utf-8", newline="\n").write(s)
ast.parse(s)
print("after_action ok")
