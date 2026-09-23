# DoomSat handoff (22 September 2026, end of day)

For whoever picks this up next (a research pass is welcome): what was built, what works, what does not, why, and
what to try.

> ## Read this first: it is 24 September and the level has been finished
>
> **E1M1 was completed on 24 September 2026** on the full stack with jev deciding — 104.97 s of game time
> against a 180 s budget, no deaths, four monsters killed. The "What does not work yet" section below is
> therefore two days stale, and so is most of the stuck list. The current standing is:
>
> - [`docs/results/2026-09-24-overnight-report.md`](results/2026-09-24-overnight-report.md) — what changed
>   and what it moved, with every number.
> - [`docs/CHARTER-STATUS.md`](CHARTER-STATUS.md) — what of the charter is built and what is open.
> - [`docs/results/e1m1-finished-decision-log.md`](results/e1m1-finished-decision-log.md) — what jev was
>   offered and what it said, at the moments that decided the run.
> - [`docs/video/e1m1-finished.mp4`](video/e1m1-finished.mp4) — the run itself, as the ground saw it.
>
> **The one thing to carry forward from the two days in between:** the pilot could never target an exit it
> saw. `candidates()` asks `path_costs` for the distance to each goal and silently drops whatever the flood
> cannot reach, and an exit line is a one-sided wall. Every exploring number this project took before the
> 24th was taken by a pilot with no way out in its candidate list. If a lead below rests on "it cannot find
> the exit", that is why, and it is fixed.
>
> **What is still true and still open:** the walking has no net direction — 49% of it toward the exit and
> 51% away even on a rung handed the whole map — one completion in six flights is not repeatability, and
> nothing can yet recognise an exit switch on screen.

> **Superseded for "what to do next" by `docs/CHARTER.md`.** The charter sets the mission (all of shareware
> Episode 1, under 3 minutes a level, on the full stack), draws the knowledge boundary as testable rules, and
> puts every change from here on through an experiment ledger. `docs/CHARTER-STATUS.md` says what is built.
> The reasons in the sections below are still the reasons, and the research leads are still worth reading,
> but where a lead conflicts with the charter the charter wins. Two that now conflict outright:
>
> - **"Exploration memory across attempts"** (in the stuck list below) is forbidden: no map survives an
>   attempt. It was quietly the largest confound in the 22 September measurements.
> - **"A planner was the wrong tool"** is narrowed: the *first* planner was wrong because it turned sensing
>   errors into confident routes and flipped between equal-cost routes on every replan. Commitment solved
>   that for sector choice and the charter puts a planner back, with commitment, in phase 3.

> **Update, later the same day.** An audit of the decision graph found fourteen issues, most of them in the code
> around jev rather than in jev's answers, and the graph has been rewritten against them. The heads are now one
> Score per open direction, one danger Score and the goal Choice; walking, doors, firing, the weapon, the aim,
> the sidestep and the mode machine are code. `validate` rejects a System Two revision it cannot accept instead
> of silently trimming it. The direction commitment is a world bearing. Doors have their own telemetry channels.
> **`docs/audit-2026-09-22.md` is the record**: issue by issue, with the replay numbers and with what it did not
> settle. The sections below are the state before that pass, kept because the reasons in them are still the
> reasons; where a lead has been taken, it is marked.
>
> **Two things to pick up first.**
>
> 1. **Restart the payload between comparison runs.** It keeps the level map *and its barrier marks* across
>    `RESET_GAME`; only `scripts/flight.sh payload` clears them. Every run that skipped this started on a
>    map the payload already believed was walled in (`EXPLORED_CELLS` 662 at the start, against 1 for a
>    fresh one) and looked far worse than it was. This confounded a whole afternoon of measurement.
> 2. **The remaining state churn is in the payload.** Two fifths of what looked like churn was the
>    egocentric labels sliding under the readings (fixed on the ground: sector words are held against the
>    ray's world bearing and a better reading has to be confirmed over `confirm_ticks`). Bin edges were
>    ~3%. What is left is the payload genuinely re-sensing the same world direction differently — **the map
>    ray and the range camera disagree by 150 units or more on 32% of ticks**, and `ahead` takes the worse
>    of the two. Sensing the eight sectors on fixed compass bearings in `payload/doom_payload.py`, rather
>    than at 45 degree offsets from the heading, would remove the rest at the source.
>
> Measure churn with `python tools/churn_check.py <log>` before and after; compare runs with
> `python tools/compare_runs.py`, which slices both into matched windows and reports a rank comparison
> rather than a single number.

## The goal

Play Doom through a real mission stack as a stress test and a demonstration of the System One / System Two split:

- the game is a payload behind a NASA F´ v4.3 flight computer; telemetry and image products go down as CCSDS
  frames into Yamcs 5.12 through `fprime-yamcs`, with the XTCE mission database generated from the F´ dictionary;
  commands go back up the same way; Yamcs web, Open MCT and a small dashboard display it;
- TypeSafe's jev (System One, a fast classifier, not an LLM) plays live: every ~0.5 s it classifies a structured
  state document and picks the direction, whether to walk, press Use, fire, which weapon;
- Claude Sonnet 5 (System Two) never touches the controls: it nudges exploration once a minute and rewrites jev's
  questions after every attempt from a condensed report;
- honesty rule: nothing from the level file reaches the payload or the models; the character senses like a
  player (eye-level range, visible objects, the in-game automap of lines already seen, HUD values);
- target: clear at least two levels of shareware Doom (E1M1, E1M2) blind, record it in 1080p, document it.

## What works (verified end to end)

- F´ dictionary -> XTCE -> Yamcs: all Doom channels decode (156 parameters, 54 commands after the last rebuild).
- Downlink: 320x240 JPEG frames split onboard into 960-byte `FrameChunk` telemetry records, straight into the com
  queue, over 1024-byte TM frames; reassembled on the ground at 10 fps with about one incomplete frame per thousand.
  The navigator's map PNG rides the same path every 5 s (high bit of the sequence number marks it).
- Uplink: one CONTROL command per jev decision, issued through Yamcs in ~45 ms; F´ events confirm dispatch and
  completion; the payload applies the turn as an onboard setpoint.
- jev: 6 to 8 typed heads per call, ~450 ms median including the Yamcs hop; every decision row carries the
  TypeSafe request id (`out/decisions*.jsonl`).
- Sonnet: a bump per minute (from an ASCII rendering of the map product and the recent walk, sent as
  `EXPLORE_HINT`) and an after-action graph revision per episode (graph v2..v9 today, each with a rationale tied
  to a number in the report). Tool-free schema calls, Sonnet only.
- Displays: Yamcs web, Open MCT (`openmct-yamcs`), and `ground/dashboard` fed only by the Yamcs API.
- Recording: `out/doomsat_dashboard_1080p.mp4` (the dashboard) and `out/doomsat_stack_1080p.mp4` (dashboard,
  Yamcs telemetry, Yamcs command history, Open MCT side by side).

## What does not work yet

*(As of 22 September. It finishes E1M1 now — see the box at the top.)*

The character does not finish E1M1. Best attempt today: it opened the first door (the "silver" one at the north end
of the north room), entered the big room, and died to the first monsters without a kill. Typical attempt: 200 to 300
jev decisions in the 3-minute budget, 100 to 250 new map cells, a few stuck ticks, a lot of re-walking of rooms it
has already seen.

## What made us stuck (the honest list)

1. **Sensing errors dressed up as navigation.** Most of the day went into finding that jev's inputs were lying:
   the depth buffer is perpendicular distance at 7.16 units per step (first calibrated as radial at 8.5, so every
   off-centre wall landed inside the room); depth 0 is the sky; the crosshair is drawn into the depth buffer; the
   automap draws the player arrow over the lines under it (walls flickered as the arrow rotated); barred windows
   and fake doors are impassable two-sided lines the automap never draws; a door-try mark once landed inside the
   character and made every direction read "blocked". jev answered every wrong input correctly.
2. **A planner was the wrong tool.** The first navigator (grid + Dijkstra over the automap, frontier targets)
   turned each sensing error into a confident wrong route, sealed its own cell several times, and flipped between
   equal-cost routes every replan. It was removed. The payload now only senses and remembers.
3. **The graph was written for an LLM, not a System One model.** Long compound prose criteria, no Nouls, no use of
   the option probabilities. Rewritten late in the day: one narrow question per head, structured criteria
   (what / not_for / examples), Nouls for yes/no heads, hysteresis from probabilities. The last cycles are the only
   ones where jev's answers match the world.
4. **Coarse directions.** Four 80-degree sectors missed a 64-unit corridor mouth at a room corner; eight
   directions with three rays each fixed that, but the words per direction (space, novelty, door on the way) were
   still being tuned when we stopped. A blocked direction read "new ground" until the last fix.
5. **Exploration memory across attempts** arrived late (each 3-minute attempt used to start with a blank map).
6. **Loop mechanics.** The pilot re-issued 180-degree turns every half second (spin); big turns now finish first.
   Compensating bearings for a commanded turn after it had already landed made jev turn straight back.
7. **Process plumbing.** Flight processes launched from a `wsl bash -c` call died with that call; a "restart" that
   did not happen looked like a checkpoint restore. Launches are now `setsid -f`.

## What to try next (research leads)

- **A vision decision model for "what is this surface".** *(Now the highest-value lead, for a new reason.)* The
  one thing the automap cannot give is what a wall *is*: plain wall, door, switch, exit sign, lift. Section 7 of
  the report sketches reducing the screen patch at arm's length to a few numbers and asking jev; a small vision
  model that classifies the patch directly (door / switch / exit sign / wall / monster / pickup) would replace
  both the switch hunting and the reliance on automap door colouring. Kevin mentioned a new "Laya" vision
  decision model as a candidate. The payload already knows which screen columns and depth belong to the surface
  at arm's length (`slow_sense` in `payload/doom_payload.py`). The audit pass gives this a sharper motivation:
  every field jev currently judges is an enum code computed, so a code rule can reproduce its answers. Evidence
  a rule cannot read is what makes the System One head worth its half second.
- **Exploration as a Score, not only a Choice.** *(Done — `ground/decision_graph.py`.)* Each open direction gets
  its own Score on a shared four-level rubric and code picks with hysteresis on a world bearing. Replay says the
  rubric as written is close to an exact function of four enum fields, so jev reproduces it faithfully and adds
  little: the next real gain is softer evidence in the state, not a different question shape. Numbers in
  `docs/audit-2026-09-22.md`.
- **Better door handling.** A door that does not open after N presses is treated as a wall for 2 minutes; locked
  doors need the key of their colour (the automap shows it); E1M2 needs the red key. None of this has been exercised
  past the first door.
- **Combat.** Aim and dodge heads now fire whenever an enemy is visible (last change of the day, untested in a
  fight). Ammunition is scarce (4 shells + 30 bullets at the start); pickups are reported with bearings but not
  steered toward unless the goal head asks for them.
- **Height.** The range camera is at eye level; drops and raised platforms are learned by bumping. A second depth
  band below the horizon would give "a drop ahead" and "a step up ahead" cheaply.
- **Let it run.** With map memory across attempts and Sonnet revising the graph, the loop improves on its own; a
  30-minute unattended run has not been tried since the last fixes.

## Where everything is

- Repo: https://github.com/Devonance/DoomSat (branch `main`); README has the run
  commands, the diagrams and the sources; `docs/doomsat-report.{md,tex,pdf}` is the report.
- Payload: `payload/doom_payload.py` (sensing, memory, level progression). Graph: `ground/graph_config.py`
  (defaults and the bounds code enforces) and `ground/graph/` (versions, changelog). Pilot: `ground/pilot.py`.
  State, heads, modes, selection and the reflex layer: `ground/decision_graph.py`. Frozen metric definitions:
  `ground/metrics.py`. The graph before the audit pass, all fifteen versions, is kept in
  `ground/graph_archive_way_choice_run/`.
- Tests: `python -m unittest discover -s tests` (72, no network, no game). Replay gate:
  `python tools/replay.py --pilots code,jev --passes 3`; boundary cases: `python tools/boundary_set.py`.
- Logs of every run today: `out/decisions*.jsonl` (one row per jev decision with the state words, answers,
  probabilities, request id, latency, telemetry snapshot; plus after-action and bump rows). `tools/run_report.py`
  summarises one.
- Developer-only tools (never used by the agent): `tools/wad_stats.py`, `tools/wad_map.py` (level geometry for
  choosing levels and checking results), the `payload/*_probe.py` calibration scripts, `payload/selfplay.py`
  (in-process code-only play at 4x real time).
