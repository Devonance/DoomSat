# PROGRAM

Kevin owns this file. The experiment loop reads it and never edits it. If following it seems to require
changing it, stop and say so instead.

The goal and the rules of the game are `docs/CHARTER.md`. This file says only what an experiment may
touch, what it costs, and what decides whether it stays.

## What an experiment may change

| Area | Files |
| --- | --- |
| `graph` | `ground/graph_config.py`, `ground/graph/` |
| `executor` | the control half of `ground/decision_graph.py`, and the executor once it exists |
| `world-model` | the world model in `payload/doom_payload.py` |
| `sensing` | how the payload senses: rays, depth bands, the automap raster |
| `planner` | the path planner, once it exists |
| `knowledge` | the values in `knowledge/doom_rules.yaml` marked tunable (the `danger` ranks and everything under `behaviour`) |

## What it may never change

- `docs/CHARTER.md`, and this file.
- The harness: `research/frozen_metrics.py`, `research/grader/`, `research/levels.yaml`,
  `research/honesty.py`, `research/preflight.py`, `research/runner.py`, `research/grade.py`,
  `research/ledger.py`.
- Anything in `knowledge/doom_rules.yaml` that is a fact about the game rather than a preference:
  hit points, damage, ammunition capacities, pickup amounts, what a key or a lift is.
- `research/ledger.tsv` by hand. Only `research/ledger.py` appends to it.

Changing a harness file is allowed when it is *wrong*, but it is not an experiment: it starts a new track
(`track:` in `levels.yaml`), every earlier number stops being comparable, and the dev set has to be
re-measured. Say so out loud before doing it.

## Never

- Run the test set (shareware E1M1 to E1M8). It is scored by a person at a milestone. `runner.py` refuses
  without `--i-am-a-person` for exactly this reason.
- Read a per-level trace from the test set to decide what to change next. Charter 2.5.
- Tune a number on one level and keep it because that level got better. One level is one sample.
- Auto-apply a System Two revision. It enters as `author=system-two` and goes through the same rule.
- Compare a run against the first window of another run. Windows are not interchangeable; the first one
  was the old run's best of 27.
- Trust a bench number that flight contradicts. That is a harness bug and gets logged as one.

## Budget

- One experiment: the dev set (6 maps) at 3 seeds, one parent run and one child run. About 40 minutes of
  wall clock on the bench and well under a dollar of jev.
- An inconclusive result reruns once at 6 seeds. If it is still inconclusive, it is a discard: the effect
  is smaller than the thing measuring it.
- A flight check on a dev subset every 5 keeps, or daily.

## The keep rule

From `levels.yaml`, applied by `ledger.py`, not by judgement:

- every guardrail passes (honesty, decision age, jev share, no crashes, tokens);
- the paired mean score gain is more than 2 standard errors, where the standard error comes from the
  measured noise floor and not from the two runs being compared;
- the number of completed levels did not drop.

Otherwise discard and `git reset`. An override is allowed and is recorded in the row forever.

## The loop

1. Read this file, the last 20 ledger rows, and any open hypotheses in `research/exp/`.
2. Write `research/exp/EXP-####/hypothesis.md` **before** touching code: what changes, why, which metric
   should move, in which direction, and by roughly how much. One change per experiment.
3. Branch `research/<date>`.
4. `python research/preflight.py --run-dir <dir> --kill`
5. `python research/runner.py bench --set dev --seeds 1 2 3 --decider jev`
6. `python research/grade.py <dir>`
7. `python research/ledger.py --parent <parent dir> --new <dir> --hypothesis ... --change ...`
8. Keep or `git reset` as the row says. Write `verdict.md` with anything the numbers do not carry.

## Honesty

Every run starts with the honesty suite and the canary. A failed honesty test voids the attempt; it does
not produce a worse score, it produces no score. If the canary ever stops failing the suite, the suite is
broken and nothing measured since the last time it worked can be trusted.
