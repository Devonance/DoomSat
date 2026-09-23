# EXP-0001 — barrier marks from a stuck push should expire in a minute, not an hour

Written before the change, per `research/PROGRAM.md` step 2.

- **track** t2
- **area** sensing
- **author** claude-code
- **tier** bench, dev set, seeds 1-5, paired against `research/out/t2-baseline-code`

## What the evidence says

Charter section 4 lists the disagreement between the map ray and the range camera as the one sensing
item to "fix at the source", with a hypothesis attached: *"two-sided lines (steps, ledges) are treated
as walls. Log the line class of every collapsed ray."*

`payload/ray_class_probe.py` does exactly that. On Freedoom E1M1, 1,499 tics:

```
1188 disagreements of 150 units or more (79%)
  the map ray was the shorter one 1178 times, the camera 10

what stopped the map ray when it came back short:
  barrier (learned by bumping)  1080   91.7%
  wall                            98    8.3%
  floor step                       0    0.0%
```

**The hypothesis is wrong.** Not one collapsed ray was stopped by a floor step. Nine in ten were stopped
by a barrier — a mark the payload wrote itself, in the raster, after bumping into something. The map ray
is not misreading the level; it is reading the pilot's own history of getting stuck.

(The probe drives with a crude walk-forward policy, so it gets stuck more than the real pilot and creates
more marks than a real run would. That inflates the *rate*, not the *ratio*, and the ratio is the finding.)

## The change

`Explorer.mark_barrier` is called with 3600 seconds when a stuck push is detected, which is permanent
inside a three-minute attempt. One bump against a door frame walls off a corridor for the rest of the
level, and `passable()` — which the planner and the candidate list now rest on — believes it.

Make that expiry a minute. One value: the `3600.0` in `Payload.observe`'s stuck branch becomes
`STUCK_BARRIER_S`, default 60.

## What should move, and by how much

- `progress` and `coverage_rate` up: routes that a single bump closed off come back.
- `revisit_fraction` down, for the same reason.
- `idle_fraction` and freezes no worse. The risk is the opposite of the current failure: forgetting a
  real obstacle too quickly and walking into it again, which would show as more stuck pushes and more
  watchdog trips.

The keep rule decides. The gain has to beat two standard errors of the t2 noise floor, with no guardrail
failing — in particular `deaths_per_minute`, which is the one this could plausibly hurt.

## Why it is not folded into the phase 2 work

It would have been convenient to change this while the executor landed. It is a separate cause with a
separate measurement, and bundling it would have made both unattributable. The baselines are running
against the code as committed; this goes through the ledger like everything else.
