# /// script
# requires-python = ">=3.10"
# dependencies = ["yamcs-client>=1.9"]
# ///
"""Apply the flight-parameter alarm ranges in ground/yamcs/alarm-ranges.json to a running Yamcs.

    python tools/set_yamcs_alarms.py                 # localhost:8090, fprime-project, realtime
    python tools/set_yamcs_alarms.py --dry-run

fprime-xtce emits no alarms, so without this Open MCT has no limit lines, no coloured values and nothing in
Fault Management for flight telemetry. These are MDB overrides on one processor: they do not survive a Yamcs
restart, so scripts/flight.sh start should call this after Yamcs is up. openmct-yamcs subscribes to MDB
changes, so an open Open MCT picks them up without a reload.

Enumerated alarms (DEAD, STUCK, PAYLOAD_LINK) cannot be set through this API; the Open MCT condition sets
cover them live. The durable fix is FPP limits on the channels plus fprime-xtce support for them.
"""
import argparse
import json
from pathlib import Path

from yamcs.client import YamcsClient

LEVELS = ("watch", "warning", "distress", "critical", "severe")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="localhost:8090")
    ap.add_argument("--instance", default="fprime-project")
    ap.add_argument("--processor", default="realtime")
    ap.add_argument("--ranges", default=str(Path(__file__).resolve().parents[1] / "ground" / "yamcs" / "alarm-ranges.json"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    ranges = {k: v for k, v in json.loads(Path(a.ranges).read_text()).items() if k.startswith("/")}
    proc = None if a.dry_run else YamcsClient(a.url).get_processor(a.instance, a.processor)
    done, skipped = 0, []
    for q, r in ranges.items():
        if "enum" in r:
            skipped.append(q.rsplit("/", 1)[1])
            continue
        kw = {lvl: tuple(r[lvl]) for lvl in LEVELS if lvl in r}
        print(f"{'would set' if a.dry_run else 'set'} {q}: {kw}")
        if proc:
            try:
                proc.set_default_alarm_ranges(q, **kw)
                done += 1
            except Exception as e:  # a parameter the running MDB lacks (a deployment built from an older Doom.fpp) is reported, not fatal
                print(f"  failed: {e}")
    print(f"{done} parameters have alarm ranges; enumerated (condition sets only): {', '.join(skipped)}")


if __name__ == "__main__":
    main()
