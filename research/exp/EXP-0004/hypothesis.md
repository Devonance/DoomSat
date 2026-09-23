# EXP-0004 — a retreat that does not shoot is a slower death

Written before the change, per `research/PROGRAM.md` step 2.

- **track** t2
- **area** executor
- **author** claude-code
- **parent** `research/out/m1-base` (pinned at 78edf8c)
- **tier** bench, dev set, seeds 1-5

## What the evidence says

The mode split, added so that a jev-versus-code row could not read a navigation loss as a combat loss,
answered a different question first. On the M1 baseline, 30 attempts, 203 deaths:

```
died in: RETREAT x99  APPROACH x62  OPERATE x37  EXPLORE x5
```

**Exploring fast is not what kills it.** Five deaths in 30 attempts happened while exploring. Half of
them happened inside the retreat rule I added two commits earlier to *stop* it dying — and the rule has
two properties that together make it worse than standing and fighting:

1. `intent_for` sets `fire_policy` to `FIRE_NONE` when the mode is RETREAT, so the player stops shooting
   at the exact moment something is shooting at it;
2. the executor's retreat backs away from the threat at running speed, which means into ground the world
   model has not swept, at the speed that gives the least warning.

The second half of the split matters too: 37 deaths in OPERATE, where the stance is `hold` and the player
stands still at a door pressing Use while something shoots it.

## The change

One thing: **a retreating player keeps shooting.** `fire_policy` stays `FIRE_ANY_ATTACKER` in RETREAT, so
the executor still fires at whatever crosses the crosshair while backing off. Nothing else moves — not the
retreat direction, not the speed, not OPERATE.

It is one line, and it is the cheapest test of the hypothesis that the deaths in RETREAT are caused by not
returning fire rather than by retreating.

## What should move, and by how much

- `deaths_by_mode["RETREAT"]` down. If the hypothesis is right this is where the movement is, and it
  should be large: 99 is half the deaths, and the change removes a self-inflicted handicap.
- `deaths_per_minute` down below the 2.20 guardrail, which the baseline failed at 2.25.
- Suite score: no prediction. At this level of performance the score is mostly measuring which side of a
  doorway the clock stopped on, which is why the keep rule will probably call it inconclusive even if the
  deaths halve. **The guardrail is the thing to read here, not the score.**
- The risk: firing while retreating wakes monsters that would otherwise have lost interest, and the
  player backs into a second group. That would show as deaths moving from RETREAT into APPROACH rather
  than disappearing.

## Why not bundle it with the OPERATE finding

Because that is what EXP-0002 did and the row could not attribute anything. Standing still at a door is a
separate cause with a separate fix, and it gets its own experiment.
