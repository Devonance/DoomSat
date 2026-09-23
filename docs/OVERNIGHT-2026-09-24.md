# Overnight, 23 to 24 September 2026

Branch `overnight-0924`, from `charter-build-out`. Track **t3**: no number here is comparable with a t2
number, and §7 says why.

*(Draft while the night runs. Anything not measured says "not measured".)*

---

## 1. Headline

Not yet. E1M1 has not been flown tonight.

The oracle ladder answered the question it was built to answer on its first rung, and the answer moved
the night: **handed the whole level's true geometry and the exit's position, the pilot got 16% of the way
in 180 s, at 46 units a second against Doom's running 507, with 45% of its ticks pressed against geometry.**
Nothing about perception could have shown up behind that. Brief §5 case 1: the executor is the priority.

After three executor fixes the same rung reads, over six dev attempts, **0 of 6 finished and 0.24 of the
way on average** -- up from 0.16 on the seed that was checked before the fixes, but nowhere near the
brief's "well under 60 s". Three seeds of the same level scored 0.60, 0.11 and 0.11 with identical
information. The executor is not slow so much as unreliable.

---

## 2. Steps

| Step | State | Exit test | Commit |
| --- | --- | --- | --- |
| 0 Make the bench the flight robot | **done** | §4 | `63bdd81` |
| 1 Oracle ladder | **done** | diagnostic only, §3 | `6dc0689` |
| 1b Executor | **partial** | L0 inside 60 s: **not met** | `6dc0689` |
| 2 Seen geometry | **done** | §5 | `63bdd81` |
| 3 Explore by seeing, rubric | **done** | §5 | `bbc8d7a` |
| 4 Switch and exit recognition | **not started** | — | — |
| 5 E1M1 status flights | **not started** | — | — |

---

## 3. Oracle ladder

Dev maps only, code decider, 3 seeds each, 180 s. Diagnostic: flagged ORACLE in every record, refused by
`grade.py`, never in the ledger.

**L0 -- the whole level's true geometry, and where the exit is.**

| | finished | best progress | cells | walked | tic rate | deaths |
| --- | --- | --- | --- | --- | --- | --- |
| E1M1 s1 | no | 0.60 | 27 | 14,988 u | 44/s | 2 |
| E1M1 s2 | no | 0.11 | 23 | 11,423 u | 40/s | 0 |
| E1M1 s3 | no | 0.11 | 16 | 12,763 u | 40/s | 0 |
| E1M2 s1 | no | 0.06 | 21 | 9,995 u | 40/s | 1 |
| E1M2 s2 | no | 0.27 | 31 | 25,180 u | 45/s | 11 |
| E1M2 s3 | no | 0.27 | 30 | 15,633 u | 44/s | 3 |
| **mean** | **0 of 6** | **0.24** | 25 | 15,000 u | 42/s | 2.8 |

Read the first three rows together. Same level, same perfect map, same known exit, three seeds: 0.60,
0.11, 0.11, and between eleven and fifteen thousand units walked in every case. The pilot is not short of
information and it is not short of travel. It cannot reliably convert either into progress.

*(L1 and L2 to be filled from `research/out/ladder3-L1` and `-L2`.)*

**Which case, and why.** Case 1. L0 is the rung with nothing in its way -- the whole level, the exit's
position, no question of seeing -- and it did not finish. Until it does, an exploration number and a
perception number are both measurements of the executor with something else's name on them.

---

## 4. Step 0: the bench was not the robot that flies

`bench_attempt` called `observe()` once per decision and then ran about nineteen tics of `make_action`
with nothing updating `exec_obs`. The executor steers from `exec_obs`. So on the bench it steered nineteen
tics on a position half a second old while in flight it steers on a fresh one every tic. Not a slower
robot -- a different one.

| | Bench as written | Sensing every tic |
| --- | --- | --- |
| EXPLORE speed, Freedoom E1M1, same seed | 175 u/s | 95 u/s |
| Cells | 29 | 23 |

The bench now senses every tic. Only the decision latency is simulated.

**Tic cost, measured for the first time** (Freedoom E1M1, 1,578 tics, code decider):

| | median | p95 | over 28.6 ms | tic rate |
| --- | --- | --- | --- | --- |
| sensing every tic, as found | 4.5 ms | 21.3 ms | 1.6% | 125/s |
| with geometry on, before any work | 6.3 ms | **178.9 ms** | 14.1% | 29/s |
| with geometry on, after | 6.1 ms | 29.1 ms | 5.4% | 98/s |

Three costs, all measured rather than guessed: `walkable()` was rebuilt from scratch by three callers at
one 9x9 max per cell; `known()` ran `np.nonzero` over the whole 3072-square raster; `path_costs` is the
single most expensive thing the payload does and its inner loop, not its algorithm, was the cost. The map
PNG was also being rendered through PIL once a second on a bench where nobody looks at it.

The payload now prints its real tic rate every 30 s, which is how the floor of 33/s can be checked at all.

**Exit test: not met yet.** The flight half (one flight on a dev map agreeing with the bench within 20%)
has not been run. Bench p95 is 29.1 ms against a 28.6 ms budget -- 2% over, on a machine that was also
running thirty-odd orphaned games (§8).

---

## 5. Steps 2 and 3: seen geometry, and what a door is

ZDoom draws a doorway, a stair tread, a window frame and a light recess in one colour. The old sensor read
that colour as "door": 1,336 of 2,899 candidates in one flight were doors and the measured door precision
was 0.04.

`payload/seen_geometry.py` takes the engine's exact lines and releases one only when the automap has drawn
half the points sampled along it. Freedoom E1M1 after 45 s: **160 of 1,050 lines released, 890 held back,
zero released lines the automap could not account for.**

| door sensor, measured against the level file | E1M1 | E1M2 | E1M3 |
| --- | --- | --- | --- |
| precision | 0.83 | 0.24 | 0.72 |
| recall | 0.81 | 0.59 | 0.78 |

(E1M2's 0.24 is mostly the probe's own ground truth: a remotely-triggered door carries its special on a
switch elsewhere, so there is no door linedef near the door to match against.)

Two things had to be got right that the brief's rule does not cover:

- **A closed door and a solid pillar are both sectors with no headroom.** That is how Doom builds a column
  in the middle of a room. The heights tell them apart: a door's flat is at the neighbouring floor
  because the ceiling came down; a pillar's is at the neighbouring ceiling because the floor went up. With
  both called doors, 71 of 250 rubbing reports in one oracle run were the player pressed against a pillar
  at seven units with Use pulsing into it.
- **A closed door has to block sight.** It is why the room behind one is unknown. The line comes out of
  the map the moment its ceiling moves.

Floor now comes from sightlines against seen walls at full range rather than the camera's 400 units, so a
room the player has looked into is filled in one go.

**Rubric (brief §7.3).** A door had its own level at the top, above every frontier -- and a door *is* a
frontier, so "untried door" beat "the corridor that leads onward" every time one was in the list. It now
carries the same features any way on does, with a `gate` word. "Further from the start" came out as a
level and stayed as a feature: a Doom level loops back, so a pilot that will not walk back the way it came
gets stuck at the far end of a dead end.

**Markers in the void.** One of the morning brief's open questions: some overlay markers sat outside any
room. Measured on the t3 baseline (geometry off, six dev maps, first six attempts), against the grader's
own reachable floor and allowing its usual eight-cell search:

| candidate kind | on floor | in the void | |
| --- | --- | --- | --- |
| item | 2,740 | 0 | 0% |
| door | 692 | 21 | 3% |
| frontier | 4,970 | 337 | **6%** |

They come from the camera sweep: it marks floor it can see, and it can see over a ledge, so a frontier
can be offered on ground no player can stand on. That is the thing the visibility fill replaces, and the
same measurement with geometry on is in §5 once it has been run.

**Exit tests: partially met.** "Zero no-route reports while walkable cells exist" is met after the cell
walkability fix in §6. Coverage per minute against the step 0 baseline is **not measured yet** -- the dev
bench with geometry on has not been run.

---

## 6. What the ladder made me fix

| Fix | Evidence it was wrong | Where |
| --- | --- | --- |
| Throttle was a step function on heading error alone | L0 at 46 u/s, 45% rubbing, with a perfect map | `payload/executor.py` |
| Aim point chosen by nearness to the path, not walkability | a chord 38 units off the path puts a 16-unit body 54 units off centre | `payload/world_model.py` |
| A cell called walkable by its centre point | L0: "no route" to all 12 frontiers with 16,848 walkable cells | `payload/doom_payload.py` |
| L0 could not see the exit it had been told about | `nearest_exit` searches 600 units; the rung became "walk to within sight of it" | `payload/oracle.py` |

The throttle is the one worth reading twice. Full speed inside 45 degrees, six tenths outside it, and no
idea how wide the corridor was -- which is right in a hall and drives into the wall in a doorway.
`ALIGN_FULL` had already been tried at 70 and measured worse. A better constant was never going to fix it
because the missing term is not a constant: closing a heading error takes `|rel| / turn rate` tics, the
sideways drift over those tics is about `speed x tics x sin(rel) / 2`, and the room to drift into is what
the range camera reports. Solve for speed. `ALIGN_FULL` is gone.

| Freedoom E1M1, oracle L0, one seed | before | after |
| --- | --- | --- |
| best progress | 0.16 | **0.45** |
| EXPLORE speed | 46 u/s | **164 u/s** |
| ticks rubbing | 45% | **22%** |
| cells | 22 | 28 |

---

## 7. Track t3, and the harness changes that start it

Two, both named in the brief, both announced here because they invalidate every t2 number:

1. **The score is the closest approach, not the final position.** t2 scored where an attempt stopped, so a
   pilot that got two thirds of the way and then wandered scored the same as one that never left the first
   room. Every exploration experiment was being graded on what happened afterwards. What it did next is
   reported beside it as `progress_given_back`. The t3 code baseline shows the gap plainly: mean closest
   approach 0.224, mean final progress 0.050.
2. **`sectors_info` is an allowed source, gated in the sensor.** Honesty test 2 now asks where the filter
   is rather than whether the switch is off; 2b reads the gate; a new live guardrail fails any run with an
   admitted line the automap cannot account for. The brief's canary -- the gate removed -- fails the suite.
   17 checks, 0 failing, all six original canaries still caught.

---

## 8. Blockers

1. **The executor cannot follow a path it has been given.** The rub loop: pressed against geometry, the
   correction leans 40 degrees off the heading, which moves the player off the path, which puts the next
   waypoint behind a wall, which keeps it leaning. L0 log: `rel=0 ahead=wall@7 fwd=7 fl=7 fr=412
   plan_left=37` -- heading dead on the aim point, wall at arm's length, 37 waypoints to go.
2. **`advance_strafing` never advances.** Measured directly: with any enemy inside `FIGHT_KEEP_UNITS` the
   stance commands zero forward movement on 60 tics out of 60, indefinitely. The brief's words for that
   are "never stand still under fire".
3. **Thirty-six orphaned ViZDoom processes** were alive on this machine, the oldest seven hours old, all
   competing for the cores every measurement was taken on. ViZDoom ignores SIGTERM -- measured, by sending
   it to thirty-five of them and finding thirty-five still running. `research/reap.py` sends SIGKILL, by
   pid. Wall-clock and tic-rate numbers taken before that was found are on a busier machine than they
   claim.

---

## 9. Decisions taken without Kevin

| Decision | Reason |
| --- | --- |
| Built steps 2 and 3 before running the ladder | They were already written when the brief arrived; the ladder still decided what came *next*, and it said the executor. |
| Oracle reads `research/grader/wad.py` off its path rather than importing it | The grader package refuses to load in a pilot process (honesty test 6) and the bench runner is one. Loading the file directly keeps one WAD reader instead of two. |
| Ledgered t2 history rows deferred | Step 0.6. Lower value than the executor with the night's hours; the constants those experiments set are unproven on t3 either way, which is the point of the item. |
| System Two off by command line, not by changing the default | Brief rule 8 is for tonight; the default is a repo-wide choice and not mine to make silently. |
| Drops are not one-way | The grader models a >24-unit rise as blocking both ways, so the pilot and the ruler agree. Making the planner directional is a change to A* and belongs in its own experiment. |
| `MAX_DOOR_CANDIDATES` 1 -> 2 | The one-slot version was set from closest-approach numbers on a shareware level, which the brief rules out as justification. Two is the cap that stops doors filling a list of eight. |

---

## 10. What I would do next, in order

*(to be finished)*
