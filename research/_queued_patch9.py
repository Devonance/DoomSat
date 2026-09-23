"""Queued: giving up on a target releases the hold; it does not choose the next one.

Brief section 2, rule 3. When a committed target stops getting closer, the code was giving up on it AND
choosing the replacement, by `rule_score`. The first half is a safety valve and belongs to code -- a
pilot that cannot let go of a door it cannot open stands at it for the rest of the attempt, which one
flight did. The second half is code picking between options, which the brief gives to the model.

It also has a measurable cost. Walk at the exit, wedge, have the code hand you a frontier, walk away,
come back: that is the shape behind 49% of the walking going toward the exit and 51% away, on a rung that
was handed the exit's position.

So: release the commitment and let the next decision be a decision. The target that stalled stays
unattractive for a while, which is what `gave_up` already does and is a description rather than a choice.
"""
import io
import sys

EDITS = [
    ("ground/targeting.py",
     '''            mem.give_up(c["x"], c["y"], int(cfg["select"]["target_give_up_ticks"]))
            mem.give_ups += 1
            detail["gave_up"] = True
            remaining = [i for i in range(len(candidates))
                         if not mem.gave_up_recently(candidates[i]["x"], candidates[i]["y"])]
            if remaining:
                rule = {i: rule_score(state["targets"]["t%d" % i]) for i in remaining}
                pick_i = max(rule, key=lambda i: (rule[i], -candidates[i]["path_units"]))
                mem.commit(candidates[pick_i]["x"], candidates[pick_i]["y"])''',
     '''            mem.give_up(c["x"], c["y"], int(cfg["select"]["target_give_up_ticks"]))
            mem.give_ups += 1
            detail["gave_up"] = True
            # Let go, and stop there. Choosing the replacement by `rule_score` was code picking between
            # options, which charter 3.3 and the brief both give to the model -- and it had a shape you
            # could see from outside: walk at the exit, wedge, be handed a frontier, walk away, come
            # back. The target that stalled stays unattractive for a while, which `gave_up` already
            # arranges and which is a description rather than a choice. The next decision is a decision.
            mem.committed, mem.held = None, 0''')
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
