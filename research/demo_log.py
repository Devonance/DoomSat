"""The decision log a demo needs: what Jev was offered and what it said, at the moments that decide a run.

Brief section 9.2 asks for "a short decision log showing Jev's probabilities at the key moments (doors,
fights, the exit)". A full flight is a few hundred decisions and nobody reads those. These are the ones
where something changed: the first time the exit is offered, every time a door or a switch is chosen,
every time the engage head says to fight or retreat, and the last decision before the level ends.

    python research/demo_log.py research/out/<run> [--out docs/demo-<name>.md]
"""
import argparse
import glob
import json
import os


def moments(rows):
    """The decisions worth showing, in order, with why each was kept."""
    out, seen_exit, prev_engage, prev_pick_kind = [], False, None, None
    for r in rows:
        cands = r.get("cand_xy") or []
        i = r.get("pick")
        kind = cands[i]["kind"] if (i is not None and i < len(cands)) else None
        why = None
        if not seen_exit and any(c["kind"] == "exit" for c in cands):
            why, seen_exit = "the exit is offered for the first time", True
        elif kind == "exit" and prev_pick_kind != "exit":
            why = "it chooses the exit"
        elif kind in ("door", "switch") and prev_pick_kind != kind:
            why = "it chooses a %s" % kind
        else:
            engage = (r.get("select") or {}).get("engage")
            if engage and engage != prev_engage and engage != "Break off and go round":
                why = "the engage head says %r" % engage
            prev_engage = engage
        prev_pick_kind = kind
        if why:
            out.append((why, r))
    if rows:
        out.append(("the last decision of the attempt", rows[-1]))
    return out


def render(attempt, path):
    rows = [r for r in attempt.get("decisions") or [] if r.get("kind") == "control"]
    lines = ["# %s, %s attempt: %s in %.1f s of game time"
             % (attempt.get("map"), attempt.get("tier"), attempt.get("end_reason"),
                attempt.get("game_seconds") or 0.0),
             "",
             "What Jev was offered and what it said, at the moments that decided the run. Scores are the",
             "target head's, on the nine-level rubric in `ground/graph_config.py`; `gap` is how far the",
             "top answer was clear of the next one.",
             ""]
    for why, r in moments(rows):
        cands = r.get("cand_xy") or []
        ans = [(r.get("answers") or {}).get("g_t%d" % k) for k in range(len(cands))]
        sel = r.get("select") or {}
        i = r.get("pick")
        lines.append("### tic %s, %.1f s -- %s" % (r.get("tic"), (r.get("tic") or 0) / 35.0, why))
        lines.append("")
        lines.append("| | " + " | ".join("t%d" % k for k in range(len(cands))) + " |")
        lines.append("| --- |" + " --- |" * len(cands))
        lines.append("| offered | " + " | ".join(c["kind"] for c in cands) + " |")
        lines.append("| jev | " + " | ".join(str(a) if a is not None else "-" for a in ans) + " |")
        lines.append("")
        lines.append("Picked **t%s** (%s). Gap %s, confidence %s%s. Mode %s.%s" % (
            i, cands[i]["kind"] if (i is not None and i < len(cands)) else "-",
            sel.get("gap"), sel.get("confidence"),
            ", " + str(sel["fallback"]) if sel.get("fallback") else "",
            r.get("mode"),
            "  Engage: %s." % sel["engage"] if sel.get("engage") else ""))
        lines.append("")
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return len(moments(rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--out", default=None)
    ap.add_argument("--which", default=None, help="only this attempt file")
    a = ap.parse_args()
    paths = [a.which] if a.which else sorted(glob.glob(os.path.join(a.run_dir, "attempt-*.json")))
    for p in paths:
        attempt = json.load(open(p, encoding="utf-8"))
        dest = a.out or os.path.join(a.run_dir, os.path.basename(p).replace(".json", "-decisions.md"))
        n = render(attempt, dest)
        print("%s: %d moments -> %s" % (os.path.basename(p), n, dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
