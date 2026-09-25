"""The autonomy block the Open MCT GROUND screens read, published from each decision row.

Drop into DoomSat/ground/ and wire it into pilot.py (two lines, see the bottom of this file). It reads only
what the pilot already logs, writes only /DoomGround parameters, and nothing in the loop reads them back:
the displays sit downstream of the stack, never upstream of a decision.

Every value is published with an expiry, so a stalled pilot shows as stale (grey) in Open MCT instead of
freezing on its last good number.
"""
import time
from collections import deque

GROUND = "/DoomGround"
KIND = {"frontier": "FRONTIER", "door": "DOOR", "exit": "EXIT", "key": "KEY", "item": "ITEM",
        "switch": "SWITCH", "enemy": "ENEMY"}


def decision_source(row):
    """Why this decision came out the way it did; the same buckets as summary.json decision_reasons."""
    sel = row.get("select") or {}
    if row.get("cached"):
        return "CACHED"
    if sel.get("gave_up"):
        return "RULE"
    if sel.get("fallback"):
        return "UNSURE_BAND"
    if sel.get("held"):
        return "HELD"
    if not row.get("answers"):
        return "UNAVAILABLE"
    return "JEV"


class OpsTelemetry:
    def __init__(self, processor, window=40, every_s=1.0, expires_s=3.0):
        self.proc = processor
        self.changes = deque(maxlen=window)    # was_jev, per intent change (charter 7: jev_share)
        self.sources = deque(maxlen=window)    # per decision (fallback_rate)
        self.last_intent = None
        self.every_s, self.expires_s = every_s, expires_s
        self.last_pub = 0.0

    def update(self, row, cands):
        src = decision_source(row)
        self.sources.append(src)
        c = row.get("control") or {}
        key = (c.get("mode"), c.get("target_x"), c.get("target_y"))
        if key != self.last_intent:
            self.changes.append(src == "JEV")
            self.last_intent = key
        if time.time() - self.last_pub < self.every_s:
            return
        self.last_pub = time.time()
        sel, ans = row.get("select") or {}, row.get("answers") or {}
        pick = row.get("pick") if isinstance(row.get("pick"), int) else None   # the sector pilot picks a word
        values = {
            # Approximation until the payload reports the tic an intent first took effect (charter 3.4):
            # telemetry age at decision + jev round trip + command issue time.
            "DecisionAgeMs": float((row.get("tel_age_ms") or 0) + (row.get("latency_ms") or 0) + (row.get("cmd_ms") or 0)),
            "IntentMode": row.get("mode"),
            "DecisionSource": src,
            "PickSlot": pick if pick is not None else 255,
            "PickKind": KIND.get(cands[pick]["kind"], "NONE") if pick is not None and pick < len(cands) else "NONE",
            "PickGap": float(sel.get("gap") or 0),
            "PickConfidence": float(sel.get("confidence") or 0),
            "JevShare": sum(self.changes) / max(len(self.changes), 1),
            "FallbackRate": sum(s != "JEV" for s in self.sources) / max(len(self.sources), 1),
            "GraphVersion": int(row.get("graph_version") or 0),
            "Attempt": int(row.get("episode") or 0),
        }
        for n in range(8):
            v = ans.get(f"g_t{n}")
            values[f"Score{n}"] = float(v) if v not in (None, "") else 0.0
        if "engage" in ans:
            values["EngageAnswer"] = str(ans["engage"])
        for k, v in values.items():
            try:
                try:
                    self.proc.set_parameter_value(f"{GROUND}/{k}", v, expires_in=self.expires_s)
                except TypeError:   # yamcs-client without expires_in: publish without the staleness expiry
                    self.proc.set_parameter_value(f"{GROUND}/{k}", v)
            except Exception as e:  # never let a display feed take the loop down
                print(f"[ops] {k}: {e}")


# Wired into ground/pilot.py (Pilot.__init__ and intent_step; control_step likewise with cands=[]):
#
#     from ops_telemetry import OpsTelemetry
#     self.ops = OpsTelemetry(self.pub_processor)
#     ...
#     self.rows.append(row)
#     self.ops.update(row, cands)
#
# And in research/preflight.py, once the honesty suite has run (and again at every level start):
#
#     processor.set_parameter_value("/DoomGround/HonestyStatus", "PASS" if ok else "FAIL")
