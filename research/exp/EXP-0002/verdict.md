# EXP-0002 — verdict: discard, and the row cannot say why

    parent 0.0499 -> new 0.0362   delta -0.0137   se 0.0156   8 wins / 12 losses
    keep rule says discard -- no gain

## What this actually measured

It bundles three changes that went in together while the executor landed:

1. the engage backstop (retreat when hurt, outnumbered or dry),
2. an obstacle guard scaled to 0.35 s of travel instead of a fixed 72 units,
3. the target rubric rewrite, which also changed the code rule by giving it `relative_distance`.

`research/PROGRAM.md` says one change per experiment, and this is why. The row is real, the verdict is
correct, and neither can be attributed. That is my error, not the rule's.

## What the numbers under the score say

| | parent | new |
| --- | --- | --- |
| suite score | 0.0499 | 0.0362 |
| `progress_best` | 0.20 | **0.22** |
| `revisit_fraction` | 0.23 | **0.18** |
| `idle_fraction` | 0.31 | **0.28** |
| `speed_explore` | 139 | 144 |
| deaths, 30 attempts | 142 | **160** |

Every process metric moved the right way and the score moved the wrong way by less than one standard
error. That is the resolution problem `docs/CHARTER-STATUS.md` flagged at the noise floor: the score is
progress measured **where the attempt ended**, and for a pilot that thrashes it quantises almost
everything to zero, so it is mostly measuring which side of a doorway the clock stopped on.
`progress_best` has resolution and says the opposite.

**The deaths did not fall.** That was the point of the change, and it failed. 142 to 160 is not an
improvement by any reading. The most likely culprit is the third piece of the guard rather than the
retreat rule: `if obs["enemies"][0][2] < FIGHT_KEEP_UNITS: cmd["move"] = min(cmd["move"], 0.0)` stops the
player dead inside 260 units of anything, and standing still in front of a hitscan monster is how a Doom
player dies. It was added on reasoning, not on evidence, which is the same mistake as the charter's
map-ray hypothesis.

## What follows

Three separate experiments, in this order, each against `t2-code-v2`:

- **EXP-0003** remove the fight-keep stop, leaving the retreat rule and the scaled guard. This is the
  suspect, and it is one line.
- **EXP-0004** the retreat rule alone, against no retreat rule.
- **EXP-0005** the scaled guard alone.

And one decision that is Kevin's, because it is a change to the ruler and starts a new track: score
unfinished levels on the closest approach rather than the final position. Until that is settled, every
row on this track is being decided by a number with almost no resolution, and this row is the first
casualty.

Not reverted. Two of the three parts are architecture the review asked for rather than tuning — the
rubric must not be a restatement of the code rule — and reverting them to satisfy a row that cannot
attribute anything would be worse than carrying a discard forward with its reason written down.
