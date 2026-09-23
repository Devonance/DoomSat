"""Queued: the unsure band falls back to the fallback the brief allows, not to a second rule.

Brief section 2, rule 3: "Code never picks between options, except safety reflexes and the one frozen
fallback: keep the current target, else the nearest frontier."

When the top two answers are within `unsure_gap`, the code was falling back to `rule_score` -- exit, then
key, then an untried door, then the nearest unexplored edge. That is a rule, and it is not the frozen
fallback. On the E1M1 flight it settled 31% of decisions; on the dev bench, 17%.

The frozen fallback is one line of English and now it is one line of code. Keeping the current target is
also what the pilot should do when it cannot tell the difference between two options -- changing your mind
on a coin toss is how three and a half seconds becomes a destination.
"""
import io
import sys

EDITS = [
    ("ground/targeting.py",
     '''    if gap < float(sel["unsure_gap"]) or conf < float(sel["unsure_conf"]):
        # a near tie is not a reason to dither: fall back to the exact rule, which always has an opinion
        rule = {i: rule_score(state["targets"]["t%d" % i]) for i in scored}
        best = max(rule, key=lambda i: (rule[i], -candidates[i]["path_units"]))
        detail["fallback"] = "unsure gap" if gap < float(sel["unsure_gap"]) else "unsure answer"
        mem.fallbacks += 1''',
     '''    if gap < float(sel["unsure_gap"]) or conf < float(sel["unsure_conf"]):
        # A near tie is not a reason to dither, and it is not a reason for a second rule either. Charter
        # 3.3 gives the choice to the model; the brief allows code exactly one fallback when the model
        # cannot be used -- keep the current target, else the nearest frontier -- and this is it. It used
        # to fall back to `rule_score`, which settled 31% of the decisions of an E1M1 flight by a rule
        # the brief does not sanction.
        held = [i for i, c in enumerate(candidates)
                if i in scored and mem.is_committed(c["x"], c["y"])]
        if held:
            best = held[0]
            detail["fallback"] = "unsure: held"
        else:
            ways_on = [i for i in scored if candidates[i]["kind"] in ("frontier", "door")]
            best = min(ways_on or list(scored), key=lambda i: candidates[i]["path_units"])
            detail["fallback"] = "unsure: nearest way on"
        mem.fallbacks += 1'''),
]


def main():
    bad = 0
    for path, old, new in EDITS:
        text = io.open(path, encoding="utf-8").read()
        if new in text:
            print("  %s: already applied" % path)
            continue
        if old not in text:
            print("  MISSING %s: %r" % (path, old.splitlines()[0][:70]))
            bad += 1
            continue
        io.open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))
        print("  %s: patched" % path)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
