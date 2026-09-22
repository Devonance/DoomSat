# DoomSat: Mission Charter and Build-Out Plan

Version 2, 22 September 2026. For Claude Code working in `github.com/Devonance/DoomSat`.

This replaces the "what to do next" parts of `audit-2026-09-22.md`. The fixes that audit drove stay in place; this document changes the goal they serve and the way every change from here on gets judged and logged.

How to read it:

- Sections 1 and 2 are the rules of the game. Experiments never tune them. Changing them starts a new comparison track.
- Section 3 is the target architecture.
- Section 4 says what in the repo stays, changes, or gets replaced.
- Section 5 is the build order. Every phase ends with a test that says it is done.
- Section 6 is the experiment ledger that every change goes through from now on.

> **Build status.** Phase 0 and Phase 1 are built; see `docs/CHARTER-STATUS.md` for what
> exists, what each exit test says today, and what is still open. Phases 2 to 6 are not
> started. Decisions taken against section 8 are recorded in section 2.3 and section 8
> and are marked **provisional** where Kevin has not confirmed them; each one is a single
> value in `research/levels.yaml` or `knowledge/doom_rules.yaml`, so reversing one is an
> edit and a re-measure, not a rewrite.

---

## 1. The mission

**Statement.** Jev flies the DoomSat payload through all of shareware Doom Episode 1 (E1M1 to E1M8) and finishes every level in under 3 minutes of game time.

- **Full stack, every time.** Every observation and every command passes through the flight stack: payload, F´, CCSDS, Yamcs, ground, Jev, then back up through Yamcs and F´ to the payload.
- **Every level is new.** It sees each level for the first time on every attempt. It knows how Doom works, not what any level looks like.
- **Rover behavior.** Onboard code keeps it safe and moving at control rate. The decision model on the ground chooses what to do next several times a second, deterministically, from a typed state. It is always searching for the exit, and it heals, picks up armor, fights, and opens doors along the way because those keep the search alive and fast.

**Done means all of these hold:**

1. **One continuous episode per attempt.** On the full pipeline in real time, a single run goes E1M1 to E1M8. Inventory carries between levels as in normal play, with a pistol start only at E1M1. Each level exits in under 180 s of game time. Normal exits only; the E1M3 secret exit and E1M9 are out of scope.
2. **Repeatable.** It succeeds in at least 4 of 5 episode attempts. Each attempt uses a fresh payload process (empty memory) and a different seed, at one fixed skill level.
3. **Honest.** Every honesty test in section 2.4 passes on every attempt. A failed honesty test voids the attempt.
4. **Jev decides.** At least 70% of intent changes come from Jev answers rather than the code fallback. This is measured as `jev_share` in section 7. The number is a proposal; set it once and freeze it.
5. **Deaths are counted and reported.** How a death is scored is settled in section 8.

**Not the mission:** 100% kills, secrets, speedrun records, or human-looking play. Kills and pickups matter only as far as they keep the run alive and fast.

---

## 2. The knowledge boundary

### 2.1 Three kinds of knowledge

| Kind | Examples | Allowed? | Where it lives |
| --- | --- | --- | --- |
| **Game rules** (known before play) | Enemy classes, their HP, attacks and danger; weapons, ammo types, useful ranges, splash risk; health, armor and ammo pickups; key colors and locked doors; what doors, lifts, switches and exit switches are; damaging floors; boss levels that need bosses killed to open the way | Yes | `knowledge/doom_rules.yaml`, versioned, with no level-specific content |
| **Episodic** (learned during this attempt) | Automap lines seen so far, cells walked, doors tried, keys held, enemies seen and killed, switches pressed, frontiers | Yes, within the current level attempt only | Onboard world model, wiped at every level start |
| **Level knowledge** (known before play) | Layouts, coordinates, where the exit, keys or items are; level names used to switch behavior; anything read from the WAD or from ViZDoom's whole-level APIs; anything carried over from an earlier attempt | Never | Nowhere |

### 2.2 What "no map in memory" means here

The rule, as written into this charter: no map survives from one attempt to the next, and nothing about a level is known before it is seen.

Within an attempt the player has to remember what it has seen, the same way a rover keeps a map of terrain it has already traversed. Without that memory the pilot re-walks rooms. The old graph visited only 56 distinct 128-unit cells in 3,307 decisions. So the boundary sits between attempts, not inside one.

This rule has already been broken once by accident. The payload kept its map and barrier marks across `RESET_GAME`, so later runs started with `EXPLORED_CELLS` at 662. That is exactly the "saved map" this charter forbids, and it has to be impossible by construction (2.4).

**Built.** `Payload.new_episode` now builds a fresh `Explorer` on every episode, including a retry of the same level, and clears the door memory, the carried hint and the stuck history with it. The old "same map, keep the raster" branch is gone. Honesty test 3 checks this statically, and `research/preflight.py` checks `EXPLORED_CELLS == 1` on the live payload before a run is allowed to start.

### 2.3 Borderline calls: decided

| Item | Call | Where it lives |
| --- | --- | --- |
| Labels buffer (class names of things in view) | **Allowed, and recorded as idealized perception.** The payload's object recognition is perfect for things actually in view; nothing is known about things out of view. A trained classifier can replace it later without changing anything above it. *(Provisional: section 8.4.)* | `perception.labels_buffer` in `research/levels.yaml` |
| Exit lines colored on the automap (`am_interlevelcolor`) | **Allowed only in view.** An exit line counts as seen only while it has been within `perception.exit_line_max_units` (default 512) of the player and drawn on the automap this attempt. Beyond that it is forgotten, so the pilot cannot navigate a whole level toward an exit color it glimpsed once. Setting the value to 0 removes exit-line color entirely and forces recognition of the exit switch in view. *(Provisional: section 8.3 — Kevin to confirm 512 or 0.)* | `perception.exit_line_max_units` |
| Locked-door colors on the automap (`am_lockedcolor`) | **Allowed for doors already seen.** A player sees the colored door frame. | `perception.locked_door_color` |
| Secret walls drawn as plain walls | **Keep.** It hides information rather than adding it. | `am_secretwallcolor` in `payload/doom_payload.py` |
| Whole-level `objects_info` / `sectors_info` | **Forbidden.** Honesty test 2. | tested |
| Automap mode | **Must stay `AutomapMode.NORMAL`.** `WHOLE`, `OBJECTS`, `iddt` and `am_cheat` are forbidden. Honesty test 1. | tested |

### 2.4 Honesty tests

These run before and during every run, bench or flight. They are implemented in `research/honesty.py` (one checker, so the unit tests and the preflight cannot drift) and driven by `tests/test_honesty.py`.

1. `test_automap_normal`: the automap mode is NORMAL and no cheat CVAR or console command is set.
2. `test_no_whole_level_info`: objects and sectors info are disabled. No code outside the grader opens the WAD for anything except launching the game.
3. `test_memory_empty_at_level_start`: at tic 0 of every level, including level transitions, `EXPLORED_CELLS == 1` and the object table, barrier marks, door memory and frontier list are all empty.
4. `test_no_level_identifiers`: pilot, executor, graph, knowledge and state-builder code contain no level names (`E\dM\d`, `MAP\d\d`), coordinate tables or sector ids.
5. `test_seen_only`: every object-table entry has a `first_seen_tic` from the labels buffer. Every door or exit entry comes from an automap line that was drawn this attempt.
6. `test_grader_isolation`: the pilot process cannot import the grader and never reads its output directory.
7. **Canary:** a deliberately planted leak (automap WHOLE, or a pre-filled map) must fail the suite. If it doesn't, the suite is broken.

### 2.5 Tuning is a leak too

If the experiment loop tunes on E1M1 to E1M8 and also scores on E1M1 to E1M8, the graph learns those layouts through its parameters, even with no map stored. The 15 graph versions tuned on E1M1 alone on 22 September are the example.

- **Dev set (tune on):** levels outside shareware Episode 1.
  - Freedoom Phase 1 is free and uses Doom 1 compatible monsters and items. The repo already has a Freedoom run log.
  - If you own Ultimate Doom, add Doom the Way id Did Episode 1, which is Episode 1 style maps by other authors.
- **Test set (score only):** shareware E1M1 to E1M8.
- **Who sees what:**
  - The experiment agent only ever sees aggregate test results.
  - A person may read test traces to find general bugs. Any fix must be justified and kept on the dev set, not on the test level that exposed it.

---

## 3. Architecture: the rover model

The split mirrors how rovers divide ground planning from onboard hazard avoidance and drive execution (Biesiadecki and Maimone 2006). Here the "ground planning" is compressed to under a second.

| Tier | Where | Rate | Decides | Rover analogy |
| --- | --- | --- | --- | --- |
| **Executor** | Onboard: payload, or an F´ component | Every tic (35 Hz) | Nothing strategic. It carries out the current intent: follow the path on the seen map, avoid obstacles, aim and fire at the commanded target, press Use at a commanded door or switch, strafe in combat, and go to safe mode when an intent expires. | Onboard hazard avoidance and drive execution |
| **Decider (Jev)** | Ground, through Yamcs | 2 to 4 decisions/s, pipelined | Which target to go for; fight, avoid or retreat; which enemy first; which weapon; whether to detour for health, armor or ammo; whether a door or switch is worth trying; what to do when stuck | Ground planning, compressed |
| **Reviewer (Sonnet)** | Ground | Per level attempt | Nothing live. It proposes experiments after each attempt. | Downlink review |
| **Research loop (Claude Code)** | Offline | Per experiment | Changes to code, graph and knowledge, through the ledger | Engineering team |

Every tier is deterministic given its input. Jev is the only model in the loop, and within a run its answers are made deterministic by caching (3.4).

### 3.1 Intent commands with a time-to-live

Replace the per-tick CONTROL command with INTENT:

```
INTENT {
  intent_id, based_on_tic,
  mode,                 # EXPLORE / APPROACH / OPERATE / FIGHT / RETREAT / RECOVER
  target,               # world x,y or object id
  stance,               # advance / advance_strafing / hold / retreat
  fire_policy,          # object id, "any_attacker", or none
  weapon,               # slot to hold, or keep
  use_at_target,        # bool
  ttl_ms
}
```

- The executor follows the newest intent whose `based_on_tic` is recent enough.
- When `ttl_ms` runs out, it drops into safe behavior: stop, face the nearest attacker, and fire only at point-blank attackers. The payload already has a 3 s uplink safe mode, so this generalizes it.
- The command goes into `Doom.fpp`, and the XTCE is regenerated through the fprime-xtce binary-annotation branch, the same way the `DOOR_*` channels were added.

The point is that the player never stops to wait for a decision. The best clean-map window so far moved at 76 units/s. Doom's running speed is several times that (measure it on the bench in phase 1). Right now the speed limit is the stop, turn, walk gait, not Jev.

### 3.2 The world model for this attempt

This lives onboard and is wiped at every level start.

- **Seen map:** automap lines plus walked cells. This already exists.
- **Frontiers:** the boundaries between seen open space and unseen space, clustered into candidate targets. This is frontier-based exploration (Yamauchi 1997).
- **Object table:** every thing seen through the labels buffer, with class, world position, last-seen tic and state (alive, dead, picked up). Also keys held, doors (color, tries, opened), switches (pressed) and the exit (seen or not).
- **Path planner:** A* over walked and seen-open cells, with commitment. Keep the current path unless a new one is better by a margin or the current one is blocked.
  - The HANDOFF removed the Dijkstra planner because it "flipped between equal-cost routes every replan". That is the same commitment problem already solved for sectors with world-frame memory. It isn't a reason to stop planning.

The eight egocentric sectors stay, demoted to local obstacle input for the executor.

### 3.3 What Jev decides

All heads go in one call per decision; extra parallel questions cost almost no latency (Valyu guide).

- Code builds each candidate list.
- Jev scores the candidates.
- Code picks, applying commitment and the unsure band.

| Head | Type | What it judges | What code does with it |
| --- | --- | --- | --- |
| `target` | Score per candidate (code prunes to 8 or fewer) | Frontiers, untried doors, unpressed switches, items worth a detour, keys, the exit. Features: path distance, novelty, door color vs keys held, item type vs current need, danger near it. | Picks with commitment, plans the path, sends INTENT |
| `engage` | Choice: fight / fight while moving / avoid / retreat | Enemy classes and counts (danger comes from the knowledge file), health, armor, ammo per weapon, distances | Sets stance and fire policy |
| `threat` | Score per visible enemy | Class danger, distance, whether it is attacking | Sets the fire-policy target |
| `weapon` | Choice among owned weapons that have ammo | Enemy class, distance and count; splash risk | Rule backstop: never a rocket at point blank |
| `need` | Score each for health, armor and ammo urgency | Current values vs knowledge thresholds, threats ahead | Re-weights target candidates |
| `stuck` | Choice: back off and re-plan / try Use / mark blocked / switch frontier | The stuck context | Executes the choice |

Rule carried over from the audit: if an answer can be computed exactly from a few enum fields, it belongs in code. The replay showed Jev agreeing with a ten-line rule 89% of the time once the rubric became a function of four fields.

Jev earns its latency when it combines many soft features that no clean rule captures. Example: "three imps and a sergeant between me and the only frontier, 38 health, 12 shells, armor behind me." Fight, detour or retreat? That is the kind of question to ask it.

### 3.4 Dense decisions without randomness

- **Pipeline depth 2.** Start a new call every ~250 ms with the latest state. Each answer carries its `based_on_tic`, and the executor ignores answers older than the newest one it has applied. The launch rate limit of 1,200 requests/minute allows this.
- **Commitment and the unsure band** (already built) keep dense decisions from turning into dithering.
- **Determinism:**
  - Fixed seeds.
  - The state is quantized and decisions are cached by state hash within a run, so an identical state always gets an identical action even if Jev would flip. The audit measured 2 flips in 141 states at a 0.20 gap.
  - The exact state, questions and answers of every call are logged (this already exists).
- **Decision age:** measure from the tic an observation was taken to the tic its command first takes effect. Report p50 and p95.

### 3.5 What the current payload cannot do yet

- **Weapons.** `BUTTONS` only has `SELECT_WEAPON2` and `SELECT_WEAPON3`, so the player can never select the fist or chainsaw (1), chaingun (4) or rocket launcher (5). E1M8's bosses are Barons of Hell (Doom Wiki). A Baron has 1,000 HP, which is a long fight on pistol and shotgun. Add slots 1, 4 and 5.
- **Running.** Confirm the forward delta is at running magnitude. If it isn't, add SPEED.
- **Level transitions.** Handle the intermission screen, the next level loading, inventory carryover, and the memory wipe at every new level.
- **Boss rule.** Add a generic rule to the knowledge file: if boss-class enemies are present and no exit has been found after exploring the frontiers, killing them becomes a candidate goal. *(Built as data: `behaviour.boss_rule` in `knowledge/doom_rules.yaml`; the code that reads it lands in phase 4.)*

---

## 4. What exists vs the goal

| Component | Verdict | Why |
| --- | --- | --- |
| F´ / CCSDS / Yamcs / Open MCT pipeline | Keep | It is the mission |
| `DOOR_*` channels; `NEW_*` as novelty only | Keep | Correct and tested end to end |
| World-frame sector smoothing and confirmation | Keep, move to executor input | Good local sensing, but myopic as a navigator |
| 8-sector Score graph as the navigator | Replace with target scoring (3.3) | It can't express "go to that door 600 units away" |
| Modes (EXPLORE, APPROACH, OPERATE, FIGHT, RECOVER, DONE) | Keep as executor modes and add a watchdog | All three freezes were bugs in sequences of ticks |
| Reflex that refuses to walk into known walls | Keep, with the stuck-detector fix | It deadlocked stuck detection once |
| Map ray vs camera disagreement (150+ units apart on 32% of ticks) | Fix at the source | Hypothesis, not yet checked: two-sided lines (steps, ledges) are treated as walls. Log the line class of every collapsed ray. |
| Barrier marks | Add expiry | Late in the run every sector read blocked |
| Map persisting across `RESET_GAME` | Wipe on reset and at every level start, plus honesty test 3 | Charter rule 2.2. **Done.** |
| Exit-line coloring | Decided (2.3): in view only, `perception.exit_line_max_units` | Reads the line's special type |
| `goal` head | Remove; replaced by `need` and target scoring | Nothing downstream used it |
| `replay.py`, `promote_graph.py`, `compare_runs.py`, `churn_check.py` | Keep, fold into the harness and ledger | Already the right tools |
| Sonnet after-action auto-apply | Route into the ledger as candidate experiments | One ruler for every change |
| 110 tests | Keep; add honesty and sequence tests | **Honesty and harness tests added.** |
| Button set | Extend (3.5) | E1M8 |
| CONTROL command every tick | Replace with INTENT plus TTL (3.1) | Gait and latency |

---

## 5. Build-out plan

Each phase ends with an exit test. Don't start the next phase until it passes. Phase 5 runs continuously from the end of phase 1 on.

### Phase 0: Charter and honesty — **built**

- Commit this document as `docs/CHARTER.md`.
- Write `knowledge/doom_rules.yaml` from published game data. Values only, no level content.
- Implement the honesty tests (2.4), including the canary.
- Wipe the world model on reset and at every level start.
- Make the borderline calls in 2.3 and record them in the charter.
- Write `research/levels.yaml` with the dev and test lists.

**Exit:** the honesty suite passes on a fresh run, and the canary fails it.

### Phase 1: Measurement harness — **built**

- **Grader** in `research/grader/`, as a separate process.
  - It may read the WAD to compute the path distance from start to exit. That is only used to score progress on unfinished levels.
  - It writes per-attempt JSON.
  - The pilot cannot import it (honesty test 6).
- **Preflight:**
  - Kill orphaned pilots and ViZDoom instances.
  - Start a fresh payload and assert `EXPLORED_CELLS == 1`.
  - Lock the run directory.
  - Record the commit, graph, knowledge and Jev model versions.
- **Two run modes:**
  - **Bench:** ViZDoom in sync mode, no F´. For each decision the game advances by a latency sampled from the last flight run, so the game sees the same delay. Runs many episodes in parallel.
  - **Flight:** the full pipeline in real time.
  - Only flight results count toward the charter. Bench exists to iterate fast.
- **Frozen metrics:** one module (section 7) used by every tool.
- **Noise floor:** run the current pilot 5 times per dev level on the bench and record the per-level score SD. That number sets the keep threshold in section 6.

**Exit:** one command turns any commit into a ledger row, on bench or flight, and the noise floor is recorded.

### Phase 2: Onboard executor and INTENT uplink

- Add the INTENT command and regenerate the XTCE.
- Build the executor: path following, local avoidance, aim and fire, Use at target, strafing, safe mode on TTL.
- Always run.
- Add weapon slots 1, 4 and 5.
- Add watchdog invariants:
  - no displacement for N s in any mode forces RECOVER;
  - every sector blocked for N s forces RECOVER and expires barrier marks.
- Fix the map-ray collapse at its source.

**Exit, on the bench with the code-rule decider:**

- mean EXPLORE speed of at least 60% of measured running speed;
- zero freezes the watchdog has to catch in 50 episodes;
- decision age p95 recorded on flight.

### Phase 3: World model and target decisions

- Frontiers, the object table, and the planner with commitment.
- The Jev `target` and `need` heads.
- Code baselines for the same heads, so the replay gate can compare them.
- Label the 102-case boundary set.

**Exit:** on the dev set bench, coverage per minute beats phase 2 by more than the noise floor, and Jev vs code is compared against the labeled answers.

### Phase 4: Combat, resources, keys, bosses, transitions

- The `engage`, `threat` and `weapon` heads.
- Key and door logic, switches, and the boss rule.
- Intermission handling and multi-level episodes on the dev set.

**Exit:** on the dev set bench, at least 80% of levels complete in under 180 s. Then the same check on flight for a dev subset.

### Phase 5: Autoresearch loop

Runs as described in section 6. It starts after phase 1 and continues through phase 4.

### Phase 6: Test campaign

- Flight, E1M1 to E1M8, 5 episode attempts, fresh payload each time.
- Report against section 1.
- The test set is run by a person at milestones, never by the loop.

---

## 6. The experiment ledger

This is modeled on Karpathy's autoresearch. A human-written `program.md` sets the rules. A read-only harness defines the metric. The agent edits a limited surface. Every run gets the same budget. Each change is kept or reverted and logged to `results.tsv` ([repo](https://github.com/karpathy/autoresearch), [summary](https://kingy.ai/news/autoresearch-karpathys-minimal-agent-loop-for-autonomous-llm-experimentation/)).

Three things differ for DoomSat:

- the metric is noisy, so it needs repeats and paired seeds;
- there are guardrails beyond the score (honesty, latency, Jev's share of decisions);
- changes land in several areas, not one file.

### 6.1 Files

| Path | Who edits | Purpose |
| --- | --- | --- |
| `research/PROGRAM.md` | Kevin only (read-only for the agent) | Points to the charter; lists the mutable surface, budget, keep rule and forbidden actions |
| Harness: grader, metrics module, honesty tests, `levels.yaml`, preflight, runners | Read-only for the agent | The ruler. Changing it starts a new track. |
| Mutable surface: executor parameters, state builder, heads and rubrics, graph config, knowledge values, planner, sensing | Agent | What experiments change |
| `research/ledger.tsv` | Written only by the harness script | One row per experiment, append-only, tracked in git |
| `research/exp/EXP-####/` | Agent and harness | `hypothesis.md` (written before any code), `diff.patch`, config snapshot, per-level per-seed results JSON, `verdict.md` |

### 6.2 Ledger columns

`exp_id, date, track, parent_commit, commit, author (kevin / claude-code / system-two), area (executor / world-model / graph / knowledge / sensing / planner), hypothesis, change, tier (bench / flight), levels, seeds, score_parent, score_new, delta, noise_se, paired_wins, paired_losses, guardrails, decision (keep / discard / inconclusive / crash), jev_usd, sonnet_usd, wall_min, notes`

Example row:

```
EXP-0007  2026-09-24  t1  a1b2c3d  e4f5a6b  claude-code  executor  "moving while deciding raises EXPLORE speed without raising deaths"  "executor keeps following the last path while an intent is in flight"  bench  dev6  s1-s3  1.12  1.31  +0.19  0.05  14  4  pass  keep  0.41  0  38  "speed 71->198 u/s, deaths unchanged"
```

### 6.3 The loop

1. Read `PROGRAM.md`, the last 20 ledger rows and any open hypotheses.
2. Write `hypothesis.md` before touching code: what changes, why, which metric should move and in which direction. One change per experiment.
3. Commit on `research/<date>`.
4. Run the bench on the dev set with the same levels and seeds as the parent.
5. Apply the keep rule:
   - **Keep** only if all guardrails pass, the paired mean score gain is more than 2 noise SEs, and the completed-level count did not drop.
   - **Discard** otherwise, with `git reset`.
   - **Inconclusive:** rerun once with twice the seeds, then decide.
6. The script appends the ledger row. The agent never writes it by hand.
7. Every 5 keeps (or daily), run a flight check on a dev subset. If bench and flight disagree, log it as a harness bug.
8. Sonnet's after-action proposals enter as hypotheses with `author=system-two` and follow the same rule. Nothing auto-applies.

### 6.4 Score and guardrails

Per level attempt:

- **Completed within 180 s:** `1 + (180 - t) / 180`, a score between 1 and 2.
- **Not completed:** `0.9 * progress`, where `progress = 1 - remaining_path_to_exit / start_path_to_exit`. Only the grader can compute this.
- **Deaths:** progress counts at the moment of death, and the death is also recorded in its own column.
- **Suite score:** the mean over levels and seeds.

Guardrails. Failing any one means discard, whatever the score:

- the honesty suite passes;
- decision age p95 at or under budget (proposed 800 ms on flight);
- `jev_share` of at least 70%;
- no crashes;
- tokens per decision not up more than 25% without a score gain.

---

## 7. Frozen metric definitions

All of these live in one module, `research/frozen_metrics.py`. Changing a definition starts a new track.

| Metric | Definition |
| --- | --- |
| `level_time` | Game seconds from level start to exit |
| `completed` | Normal exit reached in under 180 s |
| `progress` | Grader path distance, section 6.4 |
| `deaths` | Per level attempt |
| `decision_age_p50/p95` | Observation tic to first effect tic, in ms |
| `jev_share` | Intent changes caused by a Jev answer, divided by all intent changes |
| `fallback_rate` | Decisions settled by the unsure band or a rule |
| `decisions_per_s` | Jev answers applied per second |
| `speed_explore` | Mean units/s while in EXPLORE |
| `coverage_rate` | New 128-unit cells per game minute |
| `revisit_fraction` | Share of time spent in cells walked more than 20 s earlier |
| `spin_rate` | 4 s windows with 300+ degrees of rotation and under 64 units of travel, per minute |
| `idle_fraction` | Share of time with under 16 units of travel per second |
| `watchdog_trips` | Count, by invariant |
| `tokens_per_decision`, `usd_per_level` | Cost |

---

## 8. Decisions for Kevin

Each has a default in force so the build could proceed. **Provisional** means the default is
live in the config and Kevin can change it with one edit plus a re-measure; nothing is built
around the assumption.

1. **Deaths:** does a death fail the episode, or retry the level with the inventory it started with?
   **In force:** retry, count it, and require zero deaths in the final campaign — the charter's own
   recommendation. `scoring.on_death: retry_level` in `research/levels.yaml`.
2. **Skill level:** pick one and freeze it for the track.
   **In force:** skill 3, "Hurt me plenty" — the default difficulty, and the one a claim about
   "finishing Doom" is normally read against. The repo had been running skill 2.
   `run.skill: 3` in `research/levels.yaml`. *(Provisional: this makes the mission harder than
   every measurement taken so far; say the word and it drops to 2.)*
3. **Exit-line coloring** on the automap: allowed only when in view, or removed (2.3)?
   **In force:** in view only, within 512 units. `perception.exit_line_max_units: 512`.
   *(Provisional — the honest alternative is 0, which forces recognizing the exit switch on screen
   and makes the phase-3 vision head load-bearing.)*
4. **Labels buffer** as idealized perception: permanent, or replaced by a classifier later?
   **In force:** allowed and recorded as idealized, with the intent to replace it.
   `perception.labels_buffer: idealized`.
5. **Dev set:** Freedoom Phase 1 only, or add Doom the Way id Did if you own Ultimate Doom?
   **In force:** Freedoom Phase 1 only (`freedoom1.wad`, E1M1 to E1M6 as `dev6`). Doom the Way id
   Did is listed in `research/levels.yaml` under `dev_optional`, disabled, ready to switch on.
6. **Jev share threshold:** is 70% the right bar for "Jev finished the game"?
   **In force:** 70%, as proposed. `guardrails.jev_share_min: 0.70`.

---

## References

- Karpathy, autoresearch: https://github.com/karpathy/autoresearch ; overview: https://kingy.ai/news/autoresearch-karpathys-minimal-agent-loop-for-autonomous-llm-experimentation/
- Doom Wiki, Knee-Deep in the Dead (levels; E1M8 bosses are Barons of Hell): https://doomwiki.org/wiki/Knee-Deep_in_the_Dead
- Doom Wiki, Doom the Way id Did Episode 1: https://doomwiki.org/wiki/Knee-Deep_in_the_Dead_(Doom_the_Way_id_Did)
- Freedoom: https://freedoom.github.io
- Yamauchi, "A frontier-based approach for autonomous exploration," IEEE CIRA 1997
- Biesiadecki and Maimone, "The Mars Exploration Rover surface mobility flight software: driving ambition," IEEE Aerospace Conference 2006
- Otemuyiwa, "How to Use Jev" (fan-out, confidence-gated routing, rate limits), Valyu AI, 17 Sep 2026: https://dev.to/valyuai/how-to-use-jev-a-practical-guide-to-typesafes-system-one-model-g5e
- DoomSat repo files cited: `payload/doom_payload.py` (`BUTTONS`, `AutomapMode.NORMAL` at L406, `AM_CVARS`), `docs/HANDOFF.md`, `audit-2026-09-22.md`
