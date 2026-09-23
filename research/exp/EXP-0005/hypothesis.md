# EXP-0005 — run on ground already walked, walk into ground not yet seen

Written before the change, per `research/PROGRAM.md` step 2.

- **track** t2
- **area** executor
- **author** claude-code
- **parent** whichever run is current when this is measured; pinned, and named in the row
- **tier** bench, dev set, seeds 1-5

## What the evidence says

The mode split on the M1 baseline, 30 attempts, 203 deaths:

```
died in: RETREAT x99  APPROACH x62  OPERATE x37  EXPLORE x5
```

APPROACH is the second largest cause, and APPROACH is exactly the mode where the player is crossing
ground toward a target it has chosen — frequently ground the world model has not swept, because the
target is usually a frontier and a frontier is by definition the edge of the unknown.

The speed probe says the player now moves at Doom's running speed, 507 units/s, which is 14.5 map units
a tic. The obstacle guard gives 0.35 s of warning, and that is warning about *geometry*: it sees a wall
coming. It sees nothing about what is standing behind the wall, because nothing has looked there yet.

A human plays this way without being told to: run down a corridor you cleared five minutes ago, slow at
the doorway you have not opened.

## The change

One thing: **speed is chosen by what the player already knows about the ground ahead.**

- full running speed when the cells ahead are in `Explorer.visited` -- ground already walked;
- walking speed (about 60%) when the ground ahead is swept but not walked;
- walking speed when an enemy is in view at all, whatever the ground.

The executor already has everything this needs: the world model's `free` and `visited` sets, and the
enemy list it uses for aiming. No new telemetry, no new head.

## What should move, and by how much

- `deaths_by_mode["APPROACH"]` down. This is the target and it is 62 of 203.
- `speed_explore` down somewhat, and that is the price. The question the row answers is whether the
  deaths bought back more than the speed cost.
- `coverage_rate` roughly flat: the player spends most of its time on ground it has walked, which is
  where it still runs.
- The risk is that it walks everywhere, because the world model sweeps so little that "already walked"
  is almost never true. If `speed_explore` falls by more than about a third, that is what happened, and
  the fix is the sweep rather than the speed rule.

## Why this is code's decision and not a head's

`research/PROGRAM.md`: executor safety is tuned on code-decider runs, because it is not a judgement. How
fast to move over ground you have already crossed is a reflex, and putting it behind half a second of
model latency would be the same mistake as asking a model which way to sidestep a doorframe.
