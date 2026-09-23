# DoomSat overnight brief (night of 23 to 24 September 2026)

You are working alone tonight. Kevin is asleep and will not answer questions. Make decisions using this brief, write down each decision and its reason in the morning report, and keep going.

---

## 1. The goal

**Primary goal:** shareware Doom E1M1 (`doom1.wad`) finished in under 180 s of game time, flown through the full F´/Yamcs flight stack, with Jev making the choices and every honesty check passing.

That may not happen tonight. Every step below is worth finishing on its own, so work through them in order and commit after each one. A night that ends with steps 0 to 3 done, measured and pushed is a good night even if E1M1 is not beaten.

**Stop starting new work at 07:00 Pacific. Have the morning report written and pushed by 07:30.**

If every step is done before then, go to section 9 (the experiment loop).

---

## 2. Ground rules

Break none of these, whatever the numbers say.

1. **Honesty (charter section 2).**
   - The pilot knows how Doom works, never what a level looks like.
   - It remembers what it saw during this attempt only. That memory is wiped at every level start and every new attempt.
   - No level data reaches the pilot except through the sensor filter defined in step 2.
   - Never loosen an honesty test to make something pass.
2. **Test levels are status-only.** Shareware E1M1 to E1M8 are the test set.
   - You may fly shareware E1M1 **once at the end of each step** to report status, and 5 times in step 5.
   - Never use an E1M1 trace, an E1M1 overlay, or an E1M1 grader distance to choose or justify a change.
   - All tuning and every keep or discard decision happens on the Freedoom Phase 1 dev maps.
3. **Only Jev chooses between options.**
   - Code may describe the world: candidates, features in words, the map.
   - Code may execute and keep the player safe: path following, aiming, reflexes, watchdogs.
   - Code never picks between options, except safety reflexes and the one frozen fallback: keep the current target, else the nearest frontier.
4. **The harness is read-only**, except for the step 0 changes listed below.
   - Step 0 starts track **t3**: bump `version` and `track` in `research/levels.yaml` and note why.
   - Nothing from t2 is compared against t3.
5. **Experiments.**
   - One change per experiment, one ledger row per experiment.
   - The fast lane (6 attempts, judged on whether the failure mode is gone) is for clear bugs only.
   - Raw attempt logs go outside git, with path and sha1 in the ledger row.
6. **Git.**
   - Create branch `overnight-0924` from the head of `charter-build-out`.
   - Commit after each step with a message that says what changed and what moved. Push that branch.
   - Never touch `main`. Never force-push. Never rewrite history.
7. **Processes.** Record the PID of everything you start and kill only by PID. No broad `pkill` or name patterns; last time that killed two good runs.
8. **Token hygiene.**
   - Send run output to files, and read summaries with `grep`/`tail`. Never stream a long log into context.
   - Turn off System Two (Sonnet after-action reviews) for tonight; they cost tokens and add noise.
9. **No new magic-number executor constants to patch a symptom.** If a fix seems to need one, stop and write down the underlying cause instead.
10. **No claim without the number that shows it.** If something wasn't measured, say "not measured".

---

## 3. Definitions (frozen for tonight)

- **Finished:** the payload reports LEVEL FINISHED for that attempt. Nothing else counts.
- **Game time:** tics / 35.
- **jev_share:** decisions where Jev's answer chose the target, divided by decisions with 2 or more candidates. Report the rest by reason: unsure band, timeout, cache, backstop, give-up.
- **Seen coverage:** percent of the grader's reachable 128-unit cells that the pilot's world model marks as seen. Computed on the grader side only.
- **Best progress:** closest approach to the exit as a fraction of the start-to-exit path, grader side. This replaces final progress for track t3.
- **Budgets:** decision age p95 at or under 900 ms. Flight tic rate at or above 33 tics/s (log it every 30 s).

---

## 4. Step 0: make the bench the flight robot (about 1 hour)

**What's wrong.** `research/runner.py` `bench_attempt` calls `p.observe()` once per decision, then runs about 19 tics of `make_action` with no `observe()`. The executor steers from `exec_obs`, which only updates inside `observe()` (`doom_payload.py`, around line 1052). Flight calls `observe()` every tic.

Measured on Freedoom E1M1, code decider, same seed:

| Mode | observe() calls | Speed | Cells |
| --- | --- | --- | --- |
| Bench as written | 111 over 2,108 tics | 175 u/s | 29 |
| observe() every tic | every tic | 95 u/s | 23 |

That is the flight-110-vs-bench-180 gap. Every constant tuned on the old bench was tuned on a robot that doesn't fly.

**Do:**

1. Make the bench call `observe()` every tic, exactly like the flight loop. Only the decision latency is simulated.
2. Measure per-tic cost with `observe()` every tic. The last measurement was median 9 to 10 ms, p95 48 to 70 ms, and about 14% of tics over 28.6 ms, without F´, JPEG or Yamcs running.
   - Move candidates, frontiers and planning off the tic path: compute them in a worker thread, or only when a decision is being prepared.
   - The tic loop must stay under 28.6 ms at p95.
3. Log the real tic rate in flight every 30 s.
4. Start track t3 (section 2, rule 4).
5. Re-baseline on t3:
   - code decider on all 6 dev maps x 3 seeds;
   - Jev decider on 3 dev maps x 3 seeds.
6. Record the eleven E1M1 5-seed experiments in the ledger as t2 history, with decision `history` rather than keep. The constants they set stay as they are, but they are unproven until they pass on dev maps on t3.

**Exit test:**

- One flight on a Freedoom dev map and a bench run on the same map and seed agree on EXPLORE speed within 20%.
- Tic loop p95 is under 28.6 ms in that flight.

---

## 5. Step 1: oracle ladder (about 1.5 hours, diagnostic only)

Oracle runs pass `--oracle`. They are marked ORACLE in every record, never scored, never written to the ledger, and never kept. The honesty suite must fail any non-ORACLE run that loaded oracle data. **Dev maps only.** No oracle run ever happens on a shareware level.

Build the oracle from `research/grader/wad.py`. Run each rung on Freedoom E1M1 and E1M2, 3 seeds on the bench, and fly L0 once on a dev map:

- **L0, full oracle:** true geometry plus the exit location. This tests the executor, the INTENT loop and path following.
- **L1, seen oracle:** true geometry for seen lines only, with the exit revealed once it is in view within 256 units. This tests exploration.
- **L2:** the current stack.

For each rung, report: finished or not, time to exit, best progress, seen coverage, walked distance, deaths, tic rate.

**Decide from the results:**

- **L0 doesn't finish within 60 s:** the executor is the priority. Fix it (step 1b) before steps 2 and 3, still one change per experiment on dev maps.
- **L0 finishes but L1 is far worse:** exploration is the priority (step 3).
- **L1 is fine but L2 is far worse:** perception is the priority (step 2).

Write down which case you were in and why.

---

## 6. Step 2: seen geometry (about 2 hours)

Replace the automap color classification with exact geometry, filtered to what has been seen.

1. **Where the data lives.** Enable `set_sectors_info_enabled(True)` in the sensor module only. It gives line endpoints, `is_blocking`, and sector floor and ceiling heights. There are no line specials, so the exit cannot leak through this.
2. **The seen filter.**
   - A line counts as seen once at least half of the points sampled along it have nonzero automap pixels.
   - Only seen lines, and heights of sectors that have a seen line, leave the sensor module.
   - Honesty test: every line in the world model has automap pixels. A canary that injects an unseen line must fail the suite.
3. **Seen area.**
   - Raycast from the player against seen blocking lines at full range, not the 400-unit depth limit.
   - A cell inside that visibility region is seen.
   - A room is explored once it has been seen; walking it isn't required.
4. **Walkability from heights.**
   - Floor rises of 24 units or less between neighboring sectors are climbable. Anything higher is a ledge.
   - Drops are one-way.
   - A sector whose ceiling is within 8 units of its floor, bounded by two-sided lines, is a closed door.
5. **Delete what this replaces:** the sweep's stop-at-STEP rule, the step detector, the barrier learner, the clearance workarounds, and the ceiling-change door suspects and their confirmation. Don't run both systems. Keep the executor's local avoidance from the depth camera.

**Exit test, on the dev bench (t3), compared with the step 0 baseline:**

- median seen coverage per minute at least 2 times the baseline;
- zero decisions with no candidates;
- zero "no route" reports while walkable cells exist;
- the canary fails the honesty suite as designed.

---

## 7. Step 3: explore by seeing, and fix the rubric (about 1.5 hours)

1. **Frontiers:** the boundary between seen free space and unseen space, clustered, including two-sided seen lines that lead into unseen sectors.
2. **Features for Jev, in words:**
   - estimated unknown area behind the frontier;
   - path cost;
   - gate: none, door, or locked door with its color, and whether that key is held;
   - threats near it;
   - items near it;
   - times tried;
   - further from the start (a feature only).
3. **Rubric changes:**
   - A door is an opening with a gate, scored on what's behind it like any frontier. Remove "an untried door" as its own top level.
   - "Further from the start" is a feature Jev weighs, never a level that rules targets out. It traps the player at far dead ends, and levels loop back. Revert the rubric level added in commit `cb7a4c3`.
   - `rule_score` stays deliberately simpler than the rubric (the behavioral test in `tests/test_targeting.py` keeps guarding this).
4. **Look-around:** on entering a newly seen region, do a quick 360 degree look. This is a sensing routine owned by code.

**Exit test, on the dev bench (t3):**

- median seen coverage of at least 60% of reachable cells in 180 s;
- jev_share of at least 0.70;
- deaths per minute at or under the step 0 baseline.

---

## 8. Step 4: switch and exit recognition (about 1.5 hours)

This is game knowledge, not level knowledge.

1. **Templates.**
   - At load, read the switch textures (`SW1*`, `SW2*`) and the `EXITSIGN` texture from the IWAD's `TEXTURE1`, `PNAMES` and patch lumps.
   - Update honesty test 2: texture, patch and sprite lumps are allowed; map lumps stay forbidden outside the grader.
2. **Detector.**
   - Start with the simplest thing that works: use the depth buffer to find wall columns, rescale by distance, then match against the templates.
   - Measure precision and recall on dev maps, using grader ground truth from dev maps only.
3. **Behavior.**
   - A detected switch becomes a `switch` candidate; `exit_seen` gets a bearing and range.
   - The executor goes to it, faces it and presses Use.

**Exit test, on dev maps:**

- recall of at least 70% for switches in view within 256 units;
- fewer than 1 false positive per minute.

---

## 9. Step 5: E1M1 status flights, then the experiment loop

1. When steps 0 to 4 are done (or blocked and written up), fly shareware E1M1 **5 times** with Jev deciding. For each flight, report:
   - finished or not;
   - time;
   - best progress;
   - seen coverage;
   - deaths;
   - jev_share;
   - decision age p95;
   - tic rate.
2. **If any flight finishes under 180 s:**
   - Save the demo artifacts: the overlay, the decision log with Jev's probabilities at doors, fights and the exit, and the frames.
   - Fly 5 more for repeatability.
   - Do not start tuning on E1M2 or later shareware levels; generalization work happens on the Freedoom dev maps.
3. **If time remains before 07:00,** run the experiment loop on dev maps:
   - Pick the biggest gap the oracle ladder or the latest numbers point at.
   - Write the hypothesis first.
   - Make one change.
   - Run a paired bench on the same seeds.
   - Apply the keep rule from `research/PROGRAM.md`.
   - Ledger row.
   - Repeat.

---

## 10. When stuck

- **Two failed attempts at the same problem:** write it up in the report with the evidence. Commit what exists behind a flag that is off by default. Move to the next step if it doesn't depend on this one.
- **An honesty test fails and can't be fixed without loosening it:** stop that step and write it up.
- **The flight stack won't start after 2 tries:** continue with bench-only work and report exactly what failed.
- **The bench and flight disagree by more than 20% after step 0:** that's a harness bug. Fix it before tuning anything.
- Never delete files outside the repo. Never change `docs/CHARTER.md` rules.

---

## 11. Morning report

Write `docs/OVERNIGHT-2026-09-24.md`: one page plus tables, plain language, no long narratives. Push it.

1. **Headline:** E1M1 status from the best flight (finished, time, best progress, deaths, jev_share).
2. **Steps table:** for each step, done, partial or blocked; the exit test result; key numbers before and after; commit hash.
3. **Oracle ladder table,** and which case (section 5) you acted on.
4. **Ledger rows added tonight.**
5. **Top 3 blockers,** each with its evidence.
6. **What you'd do next,** in order.
7. **Decisions you made without Kevin,** each with its reason.
