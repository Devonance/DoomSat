"""One-off patch: Sonnet bumps every minute, a time budget per level attempt (reset + after-action review)."""
import ast

p = "ground/pilot.py"
s = open(p, encoding="utf-8").read()


def rep(old, new):
    global s
    assert old in s, old[:80]
    s = s.replace(old, new, 1)


rep('''        self.progress = []           # (time, explored cells, level) samples for stall detection
        self.last_hint_t = 0.0''', '''        self.progress = []           # (time, explored cells, level) samples
        self.last_hint_t = time.time()
        self.bump_busy = False
        self.level_start_t = time.time()
        self.attempt = 1''')
rep('''    def check_stall(self):
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
        threading.Thread(target=self.stall_consult, daemon=True).start()''',
    '''    def check_stall(self):
        """Every --bump-every seconds, System Two looks at the map and the walk and pushes exploration somewhere;
        after --level-budget seconds without finishing the level, the game is reset and the episode reviewed."""
        t = self.telemetry
        if "EXPLORED_CELLS" not in t or self.system_two is None:
            return
        now = time.time()
        self.progress.append((now, int(t.get("EXPLORED_CELLS", 0)), t.get("LEVEL")))
        self.progress = [p for p in self.progress if now - p[0] < 120.0]
        if self.args.level_budget and now - self.level_start_t > self.args.level_budget:
            print(f"[pilot] level {self.level} not finished within {self.args.level_budget:.0f} s: reset, review, try again (attempt {self.attempt + 1})", flush=True)
            self.episode_outcome = f"level not finished within the {self.args.level_budget:.0f} s budget (attempt {self.attempt})"
            self.command("RESET_GAME")
            self.level_start_t = now
            self.attempt += 1
            self.last_hint_t = now
            return
        if self.bump_busy or now - self.last_hint_t < self.args.bump_every:
            return
        self.last_hint_t = now
        self.bump_busy = True
        threading.Thread(target=self.stall_consult, daemon=True).start()''')
rep('''            prompt = ("The player has made no exploration progress for 90 s. Position ({:.0f}, {:.0f}), heading {:.0f} degrees "
                      "(0 = east, 90 = north). Level {}. Navigator: {}. Frontiers: {}. Doors seen: {}. Keys: {}.\\n"''',
    '''            old = [p for p in self.progress if time.time() - p[0] >= 50.0]
            gained = (self.progress[-1][1] - old[0][1]) if old and self.progress else 0
            prompt = ("Progress check. {:.0f} s into this level attempt (budget {:.0f} s), {} new map cells in the last minute. "
                      "Position ({:.0f}, {:.0f}), heading {:.0f} degrees "
                      "(0 = east, 90 = north). Level {}. Navigator: {}. Frontiers: {}. Doors seen: {}. Keys: {}.\\n"''')
rep('''                t.get("POS_X", 0), t.get("POS_Y", 0), t.get("ANGLE", 0), t.get("LEVEL"), t.get("NAV_MODE"), t.get("FRONTIERS"),
                t.get("DOORS_KNOWN"), t.get("KEYS"), path, amap or "(no map product yet)")''',
    '''                time.time() - self.level_start_t, self.args.level_budget, gained,
                t.get("POS_X", 0), t.get("POS_Y", 0), t.get("ANGLE", 0), t.get("LEVEL"), t.get("NAV_MODE"), t.get("FRONTIERS"),
                t.get("DOORS_KNOWN"), t.get("KEYS"), path, amap or "(no map product yet)")''')
rep('''                      "Pick a compass direction to push exploration toward unexplored space away from the well-trodden area, "
                      "as a bearing in degrees (0 east, 90 north, 180 west, 270 south), how many seconds to hold it, and the "
                      "goal to set. One sentence of reasoning.").format(''',
    '''                      "Pick a compass direction to push exploration toward unexplored space away from the well-trodden area "
                      "(the exit is somewhere unexplored), as a bearing in degrees (0 east, 90 north, 180 west, 270 south), how "
                      "many seconds to hold it, and the goal to set. One sentence of reasoning.").format(''')
rep('''        except Exception as e:
            print(f"[pilot] stall consult failed: {e}", file=sys.stderr)
        finally:
            self.review_busy = False''', '''        except Exception as e:
            print(f"[pilot] stall consult failed: {e}", file=sys.stderr)
        finally:
            self.bump_busy = False''')
rep('''            lv = self.telemetry.get("LEVEL")
            if lv is not None and lv != self.level:
                if self.level is not None:
                    print(f"[pilot] *** LEVEL {self.level} FINISHED -> level {lv} ***", flush=True)
                    self.log.write(json.dumps({"t": time.time(), "kind": "level", "finished": self.level, "started": lv, "controls": self.control_count}) + "\\n")
                self.level = lv''',
    '''            lv = self.telemetry.get("LEVEL")
            if lv is not None and lv != self.level:
                if self.level is not None:
                    print(f"[pilot] *** LEVEL {self.level} FINISHED -> level {lv} (attempt {self.attempt}, {time.time() - self.level_start_t:.0f} s) ***", flush=True)
                    self.log.write(json.dumps({"t": time.time(), "kind": "level", "finished": self.level, "started": lv, "controls": self.control_count,
                                               "attempt": self.attempt, "seconds": round(time.time() - self.level_start_t)}) + "\\n")
                    self.set_ground({"Plan": f"LEVEL {self.level} FINISHED in {time.time() - self.level_start_t:.0f} s (attempt {self.attempt})"})
                self.level = lv
                self.level_start_t = time.time()
                self.attempt = 1''')
rep('''    p.add_argument("--period", type=float, default=0.25, help="seconds between control decisions (lower bound)")''',
    '''    p.add_argument("--period", type=float, default=0.25, help="seconds between control decisions (lower bound)")
    p.add_argument("--bump-every", type=float, default=60.0, help="seconds between System Two progress checks (0 = never)")
    p.add_argument("--level-budget", type=float, default=180.0, help="seconds per level attempt before a reset and a review (0 = none)")''')
rep('''        if self.bump_busy or now - self.last_hint_t < self.args.bump_every:
            return''', '''        if not self.args.bump_every or self.bump_busy or now - self.last_hint_t < self.args.bump_every:
            return''')
open(p, "w", encoding="utf-8", newline="\n").write(s)
ast.parse(s)
print("pilot ok")

p = "payload/doom_payload.py"
s = open(p, encoding="utf-8").read()
old = '''            self.explorer.hint = (self.var("ANGLE") + rel, time.time() + ttl)
            print(f"[payload] explore hint {rel:+d} deg for {ttl} s", flush=True)'''
new = '''            self.explorer.hint = (self.var("ANGLE") + rel, time.time() + ttl)
            if self.target_kind in ("frontier", "far_frontier"):
                self.target, self.target_kind = None, "none"   # re-pick the frontier with the hint in force
            print(f"[payload] explore hint {rel:+d} deg for {ttl} s", flush=True)'''
assert old in s
s = s.replace(old, new, 1)
open(p, "w", encoding="utf-8", newline="\n").write(s)
ast.parse(s)
print("payload ok")
