# Phases 2 to 6: what was built, and what the numbers say

Companion to `docs/CHARTER-STATUS.md`, which covers phases 0 and 1. Written 22 September 2026.

Phases 2 and 3 were built together and deliberately: the executor has nothing to follow without a world
model, and a world model with no executor is a map nobody walks. Phase 4 followed, phase 5's machinery
after it, and phase 6 exists as a runner that only a person starts.

---

## The find: one constant capped every number this project has ever taken

Charter 3.5 asked a question in passing — *"Confirm the forward delta is at running magnitude"* — and
`payload/speed_probe.py` answers it by measuring rather than reading the source:

```
delta   units/s   note
   14     140.8   what the payload has been using
   25     251.4   Doom's walking forwardmove
   50     507.5   Doom's running forwardmove
  100     507.5   (the engine caps at 50)
```

The payload had been moving at **28% of running speed**. Every speed, coverage, progress and spin figure
ever measured in this project had that ceiling over it, including the whole of the 22 September audit.
This is why `research/levels.yaml` is now on **track t2** and nothing from t1 is comparable.

---

## Phase 2: the onboard executor and the INTENT uplink

**Built.** `payload/executor.py`, `INTENT` in `Doom.fpp`, `--control intent` in both the pilot and the
bench runner.

The ground stops sending buttons for one tic and starts sending an intent with a time to live: a mode,
somewhere to go, a stance, what to shoot at, which weapon, whether to press Use on arrival. The executor
carries it out at 35 Hz and drops to safe behaviour when the intent lapses. The player no longer stands
still while a decision is in flight, which was `idle_fraction` 0.41 of the time.

Three things in there are deliberately not decisions: sidestepping a doorframe (not worth half a second
of latency), aiming at something already within a few degrees of the crosshair (no model improves on it),
and the watchdog (a freeze is a property of a sequence of tics, and the ground sees one sample of that
sequence every half second).

### What the executor bought, and what it cost

Measured on the dev set, same maps, same seeds, code decider on both sides:

| | old gait (t1) | executor (first t2 attempt) |
| --- | --- | --- |
| `speed_explore` | 66 units/s | ~180 units/s |
| deaths, 30 attempts | 34 | **142** |
| suite score | 0.039 | 0.050 (noise floor 0.042) |

**That is not a win.** It was faster and much deader, and the suite score hid the trade because a death
and a slow walk both come out as "did not finish". Two causes, both found by looking rather than guessing:

1. **The player never retreated.** With no danger head asked, `mode_for` fell through to `FIGHT` every
   time, so it charged everything it met at a run. There is now an exact rule (`engage_backstop`) and,
   in phase 4, a head above it.
2. **The obstacle guard did not scale with speed.** A fixed 72 units was five tics of warning at the old
   delta and two at the new one. It is now a time — 0.35 s of travel — with 72 units as a floor.

And a guardrail, so the trade cannot hide again: `deaths_per_minute_max` in `levels.yaml`, which the keep
rule enforces like any other.

### Exit test

- **Mean EXPLORE speed at 60% of running (304 units/s):** not met. The executor reaches about 180.
  The remaining gap is turning and obstacle avoidance, not the delta.
- **Zero freezes the watchdog has to catch in 50 episodes:** measured now — `freezes` is counted per
  attempt from the watchdog's own trips and reported per run by `research/grade.py`.
- **Decision age p95 on flight:** 638 ms on the last flight log, against an 800 ms budget, and that is a
  lower bound because the log predates `tel_age_ms`.

---

## Phase 3: the world model and target decisions

**Built.** `payload/world_model.py` (frontiers, an object table, A* with commitment), `ground/targeting.py`
(the `target` and `need` heads, the pick, the intent), and the candidate block in the telemetry.

This is the piece the charter was written around. The graded baseline said `revisit_fraction` **0.80** —
four fifths of the pilot's decisions taken on ground it had walked over twenty seconds earlier, 75,000
units of walking to stand in 57 distinct cells. Eight local sectors cannot express "go to that door six
hundred units away"; the best they can say is "it is a bit more open to the left".

So: the payload builds the candidate list, because the path distances need the map and the map is
onboard; the model scores each candidate on one rubric in one call; code picks, with commitment and the
unsure band, and turns the pick into an intent.

### The rubric asks for trade-offs, on purpose

The first draft of the target rubric was a level-by-level restatement of the code rule. That is the trap
the sector head fell into: sharpening the rubric drove agreement with ten lines of code from 79% to 89%,
because if the rule and the rubric read the same fields the same way the model can only reproduce the
rule, and the comparison measures nothing.

The rubric now weighs things no single field settles — what is standing near the target against the
health and ammunition there is to spend on it, how far it is *relative to the other options*, whether a
detour answers a need that is real now. `rule_score` is deliberately blind to all of that: exit, key,
untried door, nearest unexplored edge, and nothing else. `tests/test_targeting.py` guards the separation
behaviourally, by varying a field the rubric asks about and asserting the rule does not move.

The state the model sees is **words, never numbers and never coordinates**. The world position rides in
the INTENT, where code uses it to aim. A test walks every field of the state and fails on a number.

---

## Phase 4: combat, resources, keys, bosses

**Built**, with one gap.

- `engage` — a Choice over fight where I stand / fight while moving / break off and go round / retreat.
  This is the charter's own example of a question worth asking, and it is asked only when something has
  actually been met.
- `weapon` — a Choice among what is loaded, with the splash rule as a backstop.
- `need` — a Score per need, from the thresholds in the knowledge file.
- Keys and locked doors: a locked door is not offered as a candidate until its key is held.
- The boss rule, as engine behaviour rather than level knowledge: with the frontiers exhausted and no
  exit seen, a boss-class monster becomes somewhere to go.
- Level transitions: inventory carries, and the world model is wiped at every level start.

**The gap: switches.** A switch that is not a door is indistinguishable from a wall on the automap, so
the world model cannot offer one as a candidate. This is the same gap the handoff identified as the
highest-value lead — a vision head that says what a surface *is* — and it is the one place where a head
would be reading evidence no exact rule can get at. It is not faked: `WorldModel.switches` exists and
stays empty rather than being filled with guesses.

---

## Phase 5: the autoresearch loop

**Built.** `research/experiment.py` is the single command: preflight, run the dev set, grade, append the
row the keep rule decided.

It refuses to start without `research/exp/<id>/hypothesis.md` already on disk. That is charter 6.3 step 2
and it is the one rule in the loop that cannot be automated away — a hypothesis written after the numbers
are in is not a hypothesis, it is a story about them. It never writes the ledger row itself.

The first experiment is written and waiting: `research/exp/EXP-0001/hypothesis.md`.

---

## Phase 6: the test campaign

**The runner is built; a person runs it.** `research/campaign.py` does five attempts on the full stack,
E1M1 to E1M8, a fresh payload each time, and reports against the five conditions in charter section 1
rather than claiming them.

`--i-am-a-person` appears exactly once, where a human can see it. The test set is what every ledger row
is trying to earn the right to predict, and a loop that can run it will tune on it eventually, whatever
anyone intended.

**It has not been run, and it would not pass.** The pilot does not yet finish a level on the dev set, let
alone eight in a row on the test set. Running it now would produce a report saying so at the cost of two
hours; it is worth running when a dev-set level completes.

---

## The one thing the evidence overturned

Charter section 4 lists the disagreement between the map ray and the range camera as the sensing item to
"fix at the source", with a hypothesis: *two-sided lines (steps, ledges) are treated as walls*.

`payload/ray_class_probe.py` logs the class that stopped every collapsed ray, which is what the charter
asked for. On 1,499 tics of the dev set:

```
1188 disagreements of 150 units or more (79%)
  the map ray was the shorter one 1178 times, the camera 10

barrier (learned by bumping)  1080   91.7%
wall                            98    8.3%
floor step                       0    0.0%
```

**Not one collapsed ray was stopped by a step.** Nine in ten were stopped by a mark the payload wrote
itself after bumping into something — and `mark_barrier` is called with 3600 seconds, which is permanent
inside a three-minute attempt. The map ray is not misreading the level; it is reading the pilot's own
history of getting stuck.

That is EXP-0001, and it goes through the ledger rather than into a commit message.

---

## Two open decisions about the ruler, both Kevin's

Each changes what the score means, so each starts a new track and costs a re-measure of the dev set.
They are listed together because they should be decided together, and before more ledger rows accumulate
under the current definition.

**1. Score unfinished levels on the closest approach, not the final position.**
Charter 6.4 scores `progress` where the attempt ended, deliberately, so that walking away from the exit
costs. For a pilot that holds a target that is right. For one that thrashes it quantises almost everything
to zero: every seed of one dev level scored 0.000 on final position while the same attempts reached
between 18% and 25% at their closest. EXP-0002 was decided by that number — every process metric moved
the right way and the score moved the wrong way by less than one standard error.

**2. Halve the progress credit on an attempt that died.**
As written, a death and a slow walk score the same, `0.9 x progress`. That is why deaths could go from 34
to 142 on the dev set while the suite score moved by 0.011. The `deaths_per_minute` guardrail covers it
for now — a change that trades survival for speed is discarded whatever the score does — but the score
itself still cannot see it.

Neither is applied. Both are one line in `research/frozen_metrics.attempt_score`.
