# Charter status

What of `docs/CHARTER.md` is built, what each phase's exit test actually says, and what is open.

**Updated 24 September 2026.** The phase-by-phase detail below was written on the 22nd, at the end of the
phase 0 and 1 work, and is still accurate for those phases. What has happened since is summarised here and
in full in [the overnight report](results/2026-09-24-overnight-report.md).

## Where it stands

**E1M1 has been finished.** 24 September, on the full stack with jev deciding: 104.97 s of game time
against a 180 s budget, no deaths, four monsters killed, 35.0 tics a second, decision age p95 845 ms. It
was the 103rd attempt this project has made at that level; none of the previous 102 finished and the best
of them reached 0.85 of the way.

| Phase | State |
| --- | --- |
| 0 — charter and honesty | **built**, exit test passes; the suite is now 17 checks and 9 canaries |
| 1 — measurement harness | **built**, exit test passes; the bench was corrected on the 24th (see below) |
| 2 — onboard executor and INTENT uplink | **built**; the speed half of its exit test is met on flight (35.0 tics/s), the freeze half is not |
| 3 — world model and target decisions | **built**, and largely rewritten on the 24th: exact geometry gated on the automap, frontiers from sightlines, a nine-level target rubric |
| 4 — combat, resources, keys, transitions | **built** except the exit/switch vision head, which is half done: the IWAD templates are read and tested, the detector is not written |
| 5 — autoresearch loop | **built and used**: the ledger now carries twelve `HIST-` rows and one fast-lane keep |
| 6 — test campaign | not started, and only a person runs it |

## The track changed to t3 on 24 September

Nothing measured on t1 or t2 is comparable with anything measured now. Three harness changes did it, each
announced where it was made:

1. **The score is the closest approach, not the final position.** A pilot that got two thirds of the way
   and then wandered used to score the same as one that never left the first room.
2. **`sectors_info` is an allowed source, gated in `payload/seen_geometry.py`.** Honesty test 2 asks where
   the filter is rather than whether the switch is off; 2b reads the gate; a live guardrail fails any run
   holding a line the automap cannot account for; the canary the brief asked for fails the suite.
3. **The noise floor was re-measured.** The number `ledger.py` divides by had been measured on **t1**, so
   every keep and discard through the whole of t2 was judged against the spread of a robot with a
   different gait, a different decider and a forward delta of 14.

## The three things that were wrong, and are not now

- **The exit was dropped from the candidate list on every run this project has ever taken.**
  `candidates()` asks `path_costs` for the distance to each goal and discards whatever the flood cannot
  reach; an exit line is a one-sided wall, so its cell is not walkable, so it was never reached. On the
  oracle rung, which is handed the exit's exact position, the payload reported it in telemetry on all 334
  decisions of an attempt and it appeared in the candidate list on none of them.
- **The freeze tests could not see flailing.** A wedged player covers hundreds of units inside a box a few
  feet across, and every motion test read that as healthy. One attempt moved 175 units in 180 seconds with
  zero watchdog trips.
- **The bench was not the robot that flies.** It sensed once per decision and then ran nineteen tics on a
  stale position, while flight senses every tic. Every constant tuned on it before the 24th was tuned on
  something that does not fly.

## What is open

- **Repeatability.** One completion in six flights. That is an existence proof, not a result.
- **The walking still has no net direction**: 49% of it toward the exit and 51% away on the oracle rung,
  52% on the dev bench after every fix. The pilot goes half again as fast as it did and arrives in the
  same place.
- **`jev_share` fails its guardrail** at 0.29 to 0.45 against a floor of 0.70, and §9 of the overnight
  report argues the definition is in tension with the charter's own commitment rule. That is a question
  for Kevin, not a number to move.
- **Nothing can recognise an exit switch.** The templates are read; the detector is not written.
- **The bench segfaults on Freedoom E1M4 with geometry on**, reproducibly, and is not diagnosed.

---

## Phase 0

**Exit test: the honesty suite passes on a fresh tree, and the canary fails it.** It does.

```
python research/honesty.py --canary        # 6 checks, 6 planted leaks, 0 failed
python -m unittest discover -s tests       # 173 tests
```

Built:

- `knowledge/doom_rules.yaml` — monsters (hit points, attack, danger rank), weapons and their ammunition,
  ammunition capacities, pickups, keys, what a door and a lift and a switch and a damaging floor are, and
  the boss rule. Published game data only. A test greps it for level names and coordinates, and two more
  tests check that every monster and every pickup the payload's labels buffer can name is described here —
  otherwise the decider meets something it has no facts about.
- `research/honesty.py` — the seven checks of charter 2.4 in one module, used by both the unit suite and
  the preflight, plus six planted leaks (`CANARIES`) that must fail it. The checks read the source rather
  than a running process on purpose: the payload that kept its map across `RESET_GAME` passed every
  runtime assertion anyone had thought to write, because nobody thought to assert on the second episode.
- **The world model is rebuilt every episode**, including a retry of the same level. This is the charter's
  rule 2.2 and it reverses a deliberate earlier choice; the reasoning for that choice ("a player remembers
  a layout") was reasonable and the effect was not, because every run after the first started on a level
  the payload already believed was walled in.
- **Exit-line colour is recognised only in view**, within `EXIT_LINE_MAX_UNITS` (512), and then remembered.
  0 removes exit colouring entirely.
- `research/levels.yaml` — the dev and test sets, and every charter decision as a single value.

## Phase 1

**Exit test: one command turns any commit into a ledger row, on bench or flight, and the noise floor is
recorded.** It does, in two commands rather than one — the grader must not run inside a pilot process, so
grading is a child process (`runner.py --grade` does it for you), and the ledger row is deliberately a
separate step because it needs a parent run to compare against.

```
python research/preflight.py --run-dir research/out/<id> --kill
python research/runner.py bench --set dev --seeds 1 2 3 --decider jev --grade
python research/ledger.py --parent <parent dir> --new <dir> --hypothesis "..." --change "..."
```

Built:

- **The grader** (`research/grader/`), in its own process, refusing to import when `DOOMSAT_ROLE=pilot`.
  It reads the WAD to answer one question — how far along the floor was the player from the exit — and
  charter 6.4 turns that into partial credit for a level that was not finished.
- **Two tiers, one decision function.** `dg.decide()` is called by the flight pilot and by the bench
  runner, so a bench number is about the pilot and not about the harness. The bench advances the game by a
  latency drawn from a real flight log, and runs about seven times real time.
- **`research/frozen_metrics.py`** is now the one metrics module. `ground/metrics.py` is a shim that loads
  the same file, so the existing tools are unchanged; a test asserts they are the same file and not a copy.
- **`research/preflight.py`**, **`research/ledger.py`**, **`research/PROGRAM.md`**.

### What the grader gets wrong, on purpose and by accident

The score rests on a walkability model, and a model is a guess about an engine. Four things had to be
modelled before the number meant anything, each found by the model reporting a level as having no route to
its own exit:

1. **the player is a cylinder, not a point.** Blocking whole 32-unit cells sealed every corridor narrower
   than 64 units. Cells are 16 units now and a cell is blocked when its centre is within 16 units of a wall.
2. **a closed door sector.** Only the line you press carries the door special; the line on the far side of
   the same sector is a plain two-sided line into a sector whose ceiling is on its floor, and measuring its
   opening while the door is shut says "no gap".
3. **sectors that move.** A lift is called by a line on the floor beside it; the line between the lift and
   the floor is plain, with a drop of far more than a step. A static height test walls the level off at
   every lift.
4. **the void between rooms is nothing, not floor.** Without this the flood walks through the empty space
   outside the walls and reports a sealed level as nearly finished. The first attempt used crossing parity
   over one-sided lines, which is the textbook answer and is wrong often enough on real geometry to matter;
   it is now an exterior flood, which assumes nothing about the geometry.

What it still gets wrong, and says so rather than hiding:

- **a locked door does not block.** The grader will report a pilot standing at a locked door with no key as
  nearly finished. `progress` is partial credit, not a claim that the rest is achievable; `completed` is
  the only thing that says a level was beaten.
- **teleports are not followed.** Maps that need one are flagged, and their progress understates a route
  that goes through one.
- **E1M3 and E1M8 have no route in the model** and are excluded from any progress average
  (`maps_without_a_usable_progress_score` in every summary). They can still be scored on `completed`.
  Fixing them means a general improvement to the walkability model, justified on its own terms — not a
  change made until those two maps go green. They are test-set maps, and tuning the ruler by staring at
  them is the leak charter 2.5 is about. `research/grader/explain.py` is the tool for whoever takes it on.

Checked with `python research/grader/survey.py <wad>`: **6 of 6 dev maps** and **6 of 8 test maps** have a
usable progress score.

### The noise floor, and the problem it exposes

Measured as the charter asks: the current pilot, 5 repeats of each of the 6 dev levels, 180 s each, nothing
changed between them. `research/out/noise-floor-code/`, recorded in `research/noise_floor.json`, which is
what `ledger.py` divides by.

```
suite score 0.0391 over 30 attempts (sd 0.0733), 0 completed, 34 deaths
per-level score sd: E1M1 0.142  E1M2 0.000  E1M3 0.000  E1M4 0.015  E1M5 0.042  E1M6 0.043
noise floor: mean 0.0404
```

**The noise floor (0.040) is the same size as the suite score (0.039).** Nothing can be kept on suite score
until the pilot gets somewhere: the keep rule asks for a paired gain of two standard errors, and at this
level of performance almost every attempt scores zero, so the measurement is nearly all floor. That is not
a fault in the keep rule. It is the keep rule correctly reporting that the current pilot has no signal to
improve on, which is the same thing `revisit_fraction` 0.80 says from the other direction.

Two consequences worth acting on:

- **Two levels have a standard deviation of exactly zero**, because every repeat scored exactly 0.000.
  A zero denominator would make any change look significant, which is why `ledger.py` divides by the mean
  of the per-level spreads rather than by each level's own.
- **`progress` measured at the end of the attempt has almost no resolution here, and `progress_best` has
  plenty.** Every seed of E1M2 scored 0.000 on where it ended; the same attempts reached between 18% and
  25% of the way at their closest. Charter 6.4 specifies the end position, deliberately, so that walking
  away from the exit costs — and that is the right rule for a pilot that can hold a target. For a pilot
  that thrashes, it quantises almost everything to zero.
  **Recommendation, not applied:** score unfinished levels on the closest approach rather than the final
  position, at least until phase 3 gives the pilot a target to hold. It is a one-line change in
  `frozen_metrics.attempt_score`, it is a change to the ruler, and so it starts a new track and needs the
  dev set re-measured. Kevin's call, and it should be made before the first experiment rather than after,
  because every row written under the current definition becomes incomparable when it changes.

---

## The baseline, measured against the charter for the first time

The best flight run of 22 September — E1M1, 900 seconds, clean payload, graph frozen, jev commanding —
graded by the new ruler. `research/out/baseline-flight-20260922-e1m1-900s/`:

| Metric | Value | What it says |
| --- | --- | --- |
| `score` | **0.000** | charter 6.4: it ended no closer to the exit than it started |
| `progress` / `progress_best` | 0.00 / **0.20** | it got a fifth of the way there at best, then came back |
| `revisit_fraction` | **0.80** | four fifths of its decisions were taken on ground it had already walked over 20 s earlier |
| `path_units` / `cells` | 75,195 / 57 | 75,000 units of walking to stand in 57 distinct cells |
| `coverage_rate` | 3.8 cells/min | |
| `idle_fraction` | 0.41 | two fifths of the time it is not getting anywhere |
| `speed_explore` | 66 units/s | against a running speed that phase 2 has to measure |
| `jev_share` | **0.54** | below the charter's 0.70 guardrail: the code fallback makes nearly half the intent changes |
| `fallback_rate` | 0.43 | |
| `decision_age_p95` | 638 ms | inside the 800 ms budget, **but this is a lower bound** |
| `watchdog_trips` | 21 RECOVER | in 900 seconds |
| `tokens_per_decision` | 2,226 | |

Three things to read carefully:

- **`decision_age_p95` is understated.** `decision_age_complete` is 0.0 for this run: it predates the pilot
  logging how stale the telemetry already was when a decision started, so 638 ms is the model call plus the
  command hop and nothing else. The pilot logs `tel_age_ms` now, so the next flight run will have all three
  terms.
- **`revisit_fraction` 0.80 is the headline**, and it is exactly what charter phase 3 exists to fix. The
  pilot is not stuck and it is not slow; it walks 75,000 units and keeps arriving where it has already been,
  because an eight-sector local score cannot express "go to that door 600 units away". The audit in
  September improved the walk a great deal on its own terms; this is the measurement that says the
  remaining problem is not the walk.
- **`score` 0.000 with `progress_best` 0.20** is the charter's scoring working as designed. Ending where
  you started scores nothing, and the gap between the two columns is the thrashing.

For contrast, a 40-second bench attempt on the dev set with jev in the loop reads `jev_share` 0.62,
`idle_fraction` 0.45, `speed_explore` 84 units/s, 243 ms median decision age — the same picture, which is
the first (weak) evidence that the bench and flight tiers agree.

## Open, for Kevin

These are live defaults, each one value in `research/levels.yaml`. Changing one is an edit and a
re-measure, not a rewrite.

| Decision | In force | Note |
| --- | --- | --- |
| Skill level (8.2) | **3, "Hurt me plenty"** | The repo had been running skill 2, so this makes the mission harder than every measurement taken so far. Say the word and it drops back. |
| Exit-line colour (8.3) | **in view, within 512 units** | The honest alternative is 0, which forces recognising the exit switch on screen and makes the phase-3 vision head load-bearing. |
| Deaths (8.1) | **retry the level, count it, zero allowed in the campaign** | The charter's own recommendation. |
| Labels buffer (8.4) | **allowed, recorded as idealized** | To be replaced by a classifier later. |
| Dev set (8.5) | **Freedoom Phase 1 only** | Doom the Way id Did is in `levels.yaml` under `dev_optional`, disabled, ready if you own Ultimate Doom. |
| jev share (8.6) | **0.70** | Currently failing at 0.62, which is a finding and not a reason to move the bar. |

Two more that the charter settles on paper but the code contradicts, found while wiring the harness up.
Neither is changed, because each would invalidate every baseline including the noise floor above, and
both are the same kind of call as the skill level:

- **There is no pistol start.** Charter 1.1 says "a pistol start only at E1M1"; `Payload.new_episode`
  hands out a shotgun, 4 shells and 30 bullets at the start of every attempt that is not carrying an
  inventory forward. That is both easier than a pistol start (a shotgun) and harder (30 bullets rather
  than 50). One line in `payload/doom_payload.py`.
- **The flight stack and the bench were playing at different difficulties.** `scripts/wsl_run_flight.sh`
  never passed `--skill`, so the flight payload took the payload's own default of 2 while the bench ran
  at the 3 in `levels.yaml`. Nothing would have failed; the two tiers would simply have been measuring
  different games, and charter 6.3 step 7 would have read the disagreement as a pilot result. **This one
  is fixed** — the launcher now passes `--skill ${SKILL:-3}` and a test pins it to `levels.yaml` — but it
  is listed here because it means no flight number taken before today is comparable with a bench number.

## Next

**First, settle the scoring definition** (the `progress_best` recommendation above). Every ledger row
written before that decision becomes incomparable after it, so it costs nothing now and costs the whole
ledger later.

Then phase 2, in the order the charter sets: the INTENT command and its TTL, the onboard executor, running,
weapon slots 1, 4 and 5, and the watchdog invariants. Its exit test is measured on the bench with the code
decider in the loop, so that a gait result cannot be mistaken for a model result.

Two things are worth doing inside phase 2 rather than after it, because they are cheap and everything
downstream rests on them:

- **The map ray and the range camera still disagree by 150 units or more on 32% of ticks**, and `ahead`
  takes the worse of the two. The charter's hypothesis is that two-sided lines (steps, ledges) are being
  treated as walls; the way to find out is to log the line class of every collapsed ray.
- **34 deaths in 30 dev attempts at skill 3.** That is a little over one per attempt, and under the charter's
  retry rule each one costs the clock without moving the player. It may be the skill decision (8.2), it may
  be that the pilot has no retreat, and it is cheap to tell the two apart: run the same 30 attempts at
  skill 2 and compare. That *is* a legitimate first use of the ledger, because it is a question about the
  harness rather than about the pilot.

What is deliberately **not** run yet: a jev baseline on the dev set. With the noise floor as large as the
score, a code-versus-jev comparison would be inconclusive by construction, and it would cost around ten
million input tokens to learn that. It becomes worth running the moment phase 2 gives the score some
resolution.
