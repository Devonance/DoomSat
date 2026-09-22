# DoomSat handoff (22 September 2026, end of day)

For whoever picks this up next (a research pass is welcome): what was built, what works, what does not, why, and
what to try.

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

- **A vision decision model for "what is this surface".** The one thing the automap cannot give is what a wall
  *is*: plain wall, door, switch, exit sign, lift. Section 7 of the report sketches reducing the screen patch at
  arm's length to a few numbers and asking jev; a small vision model that classifies the patch directly (door /
  switch / exit sign / wall / monster / pickup) would replace both the switch hunting and the reliance on automap
  door colouring. Kevin mentioned a new "Laya" vision decision model as a candidate. The payload already knows
  which screen columns and depth belong to the surface at arm's length (`slow_sense` in `payload/doom_payload.py`).
- **Exploration as a Score, not only a Choice.** Ask jev to score each of the eight directions ("how promising is
  this direction for finding the exit") and let code pick the argmax with hysteresis; composite scoring is the
  documented System One pattern and may beat the single Choice with eight options.
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

- Repo: https://github.com/Devonance/claude-jev-fprime-yamcs-openmct-doom (branch `main`); README has the run
  commands, the diagrams and the sources; `docs/doomsat-report.{md,tex,pdf}` is the report.
- Payload: `payload/doom_payload.py` (sensing, memory, level progression). Graph: `ground/graph_config.py`
  (defaults) and `ground/graph/` (versions, changelog). Pilot: `ground/pilot.py`. Words: `ground/decision_graph.py`.
- Logs of every run today: `out/decisions*.jsonl` (one row per jev decision with the state words, answers,
  probabilities, request id, latency, telemetry snapshot; plus after-action and bump rows). `tools/run_report.py`
  summarises one.
- Developer-only tools (never used by the agent): `tools/wad_stats.py`, `tools/wad_map.py` (level geometry for
  choosing levels and checking results), the `payload/*_probe.py` calibration scripts, `payload/selfplay.py`
  (in-process code-only play at 4x real time).
