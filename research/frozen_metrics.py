"""Frozen definitions of every number DoomSat compares runs on. Charter section 7.

This module is HARNESS: the experiment loop reads it and never edits it. Changing a definition here
invalidates every baseline ever measured, so it starts a new track (`track:` in research/levels.yaml)
and the whole dev set has to be re-measured.

It began as ground/metrics.py, which still imports from here so that the pilot, the replay gate, the
run report and the grader cannot drift apart. Two readings of the same log once differed by 12 percent
on the spin count purely because one skipped windows that crossed an episode boundary and the other did
not; that is the failure mode this file exists to prevent.

The walk metrics (spin, cells, path) are the ones the 22 September baselines in docs/audit-2026-09-22.md
were measured with, and are unchanged. Everything below the "charter metrics" line is new with the
charter and has no baseline yet.
"""
import math
from collections import Counter

# ---------------------------------------------------------------- the walk (unchanged since 22 Sep)
SPIN_WINDOW_TICKS = 8         # consecutive control decisions in one window
SPIN_ROTATION_DEG = 300.0     # total absolute heading change over the window, at or above this
SPIN_TRAVEL_UNITS = 64.0      # straight-line distance between the window's ends, strictly under this
CELL_UNITS = 128              # the grid the walk's coverage is counted on
UNSURE_BAND = (0.35, 0.65)    # an open band on a probability: "cannot tell"
SPIN_WINDOW_SECONDS = 4.0     # the wall-clock window; compare designs on this, not on ticks
SPIN_KEY = "spin_windows_%dtick_%ddeg_under%du" % (SPIN_WINDOW_TICKS, SPIN_ROTATION_DEG, SPIN_TRAVEL_UNITS)
SPIN_TIME_KEY = "spin_windows_%.0fs_%ddeg_under%du" % (SPIN_WINDOW_SECONDS, SPIN_ROTATION_DEG, SPIN_TRAVEL_UNITS)

# ---------------------------------------------------------------- charter metrics (section 7)
REVISIT_AGE_S = 20.0          # a cell counts as revisited when it was first walked this long ago
IDLE_UNITS_PER_S = 16.0       # a second with less travel than this is idle
LEVEL_BUDGET_S = 180.0        # charter 1: a level must exit inside this
COMPLETED_BASE = 1.0          # charter 6.4
INCOMPLETE_WEIGHT = 0.9


def samples(rows):
    """(episode, x, y, heading, t) per control row that carries a position, in order."""
    out = []
    for r in rows:
        raw = r.get("raw") or {}
        if raw.get("POS_X") is None or raw.get("ANGLE") is None:
            continue
        out.append((r.get("episode"), float(raw["POS_X"]), float(raw["POS_Y"]), float(raw["ANGLE"]),
                    float(r.get("t") or 0.0)))
    return out


def spin_windows(samples_):
    """Windows of SPIN_WINDOW_TICKS consecutive ticks that turned a lot and went nowhere.

    Windows crossing an episode boundary are skipped: the position jumps when the player respawns, which
    would otherwise read as a huge instant traversal or a huge instant turn.
    """
    n = 0
    for i in range(max(0, len(samples_) - SPIN_WINDOW_TICKS)):
        w = samples_[i:i + SPIN_WINDOW_TICKS + 1]
        if any(s[0] != w[0][0] for s in w):
            continue
        rot = sum(abs((w[j + 1][3] - w[j][3] + 180) % 360 - 180) for j in range(len(w) - 1))
        if rot >= SPIN_ROTATION_DEG and math.hypot(w[-1][1] - w[0][1], w[-1][2] - w[0][2]) < SPIN_TRAVEL_UNITS:
            n += 1
    return n


def spin_seconds(samples_):
    """The same test over a fixed window of SPIN_WINDOW_SECONDS, not a fixed number of ticks.

    The tick version is kept because every earlier baseline was measured with it, but it is not safe for
    comparing designs: a pilot that waits out its turns takes fewer decisions per second, so a window of
    eight of its ticks covers more wall-clock time than eight of another pilot's, and turning in place for
    a second trips the test by construction. Compare designs on this one.
    """
    n = 0
    for i in range(len(samples_)):
        t0 = samples_[i][4]
        w = [x for x in samples_[i:] if x[0] == samples_[i][0] and x[4] - t0 <= SPIN_WINDOW_SECONDS]
        if len(w) < 3 or w[-1][4] - t0 < SPIN_WINDOW_SECONDS * 0.5:
            continue
        rot = sum(abs((w[j + 1][3] - w[j][3] + 180) % 360 - 180) for j in range(len(w) - 1))
        if rot >= SPIN_ROTATION_DEG and math.hypot(w[-1][1] - w[0][1], w[-1][2] - w[0][2]) < SPIN_TRAVEL_UNITS:
            n += 1
    return n


def spin_rate(samples_):
    """Spin windows per second of play: the number to compare two designs on."""
    if len(samples_) < 2:
        return 0.0
    return spin_seconds(samples_) / max(1e-6, elapsed(samples_))


def elapsed(samples_):
    """Seconds of play, skipping the gaps at episode boundaries and any stall over 5 s."""
    return sum(b[4] - a[4] for a, b in zip(samples_, samples_[1:]) if a[0] == b[0] and 0 < b[4] - a[4] < 5)


def cells(samples_):
    """How often each CELL_UNITS cell of the level was stood in."""
    return Counter((round(x / CELL_UNITS) * CELL_UNITS, round(y / CELL_UNITS) * CELL_UNITS)
                   for _, x, y, _, _ in samples_)


def unsure(p):
    """True when a probability falls in the open band where the answer means "cannot tell"."""
    return p is not None and UNSURE_BAND[0] < p < UNSURE_BAND[1]


def path_units(samples_):
    """Manhattan distance walked, skipping episode boundaries."""
    total = 0.0
    for a, b in zip(samples_, samples_[1:]):
        if a[0] == b[0]:
            total += abs(a[1] - b[1]) + abs(a[2] - b[2])
    return total


def straight_units(samples_):
    """Straight-line distance walked. Used for speed, where the Manhattan figure would overstate a diagonal."""
    return sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(samples_, samples_[1:]) if a[0] == b[0])


# ---------------------------------------------------------------- charter section 7
def percentile(values, p):
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    k = min(len(v) - 1, max(0, int(round((len(v) - 1) * p))))
    return v[k]


def attempt_score(completed, level_time, progress_, budget=LEVEL_BUDGET_S):
    """Charter 6.4, amended 23 September (track t3). Completed in time scores 1 to 2; otherwise partial
    credit for how far it got.

    `progress_` is now the CLOSEST APPROACH, not where the attempt stopped. Charter 6.4 scored the end
    position on the reasoning that walking away from the exit should cost, and that turned out to measure
    the wrong thing: a pilot that reaches two thirds of the way and then wanders scores the same as one
    that never left the first room, so every experiment about finding the way was being graded on what
    happened afterwards. Where it got to is what "did it find the way out" means; what it did next is
    `progress` minus `progress_best`, reported beside it, and it is a different question.

    Changing this invalidates every t2 number. That is why it is a track change and not an experiment.
    """
    if completed and level_time is not None and level_time <= budget:
        return COMPLETED_BASE + (budget - level_time) / budget
    return INCOMPLETE_WEIGHT * max(0.0, min(1.0, progress_ or 0.0))


def progress(start_distance, remaining_distance):
    """1 at the exit, 0 at the start, and never outside [0, 1] even if the pilot walked away from it."""
    if not start_distance or start_distance <= 0 or remaining_distance is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 - remaining_distance / start_distance))


def decisions_per_s(rows):
    s = samples(rows)
    return len(rows) / max(1e-6, elapsed(s)) if len(s) >= 2 else 0.0


def decision_age_ms(rows):
    """Observation to first effect, per decision.

    Three delays add up: how old the telemetry already was when the pilot read it (`tel_age_ms`), how long
    the model took (`latency_ms`), and how long the command took to reach the payload (`cmd_ms`). A row
    without `tel_age_ms` is from before the pilot logged it and is counted without that term, which
    understates it; `decision_age_complete` says how many rows were whole.
    """
    return [float(r.get("tel_age_ms") or 0.0) + float(r.get("latency_ms") or 0.0) + float(r.get("cmd_ms") or 0.0)
            for r in rows if r.get("kind") == "control"]


def decision_age_complete(rows):
    ctl = [r for r in rows if r.get("kind") == "control"]
    return sum(1 for r in ctl if r.get("tel_age_ms") is not None) / max(1, len(ctl))


def intent_changes(rows):
    """Rows where what the pilot was trying to do changed: a different mode, or a different direction."""
    out, prev = [], None
    for r in rows:
        if r.get("kind") != "control":
            continue
        now = (r.get("mode"), r.get("pick"))
        if prev is not None and now != prev:
            out.append(r)
        prev = now
    return out


def jev_share(rows):
    """Charter 7: intent changes caused by a model answer, over all intent changes.

    A change counts as the model's when the model was asked and code did not overrule it: no unsure-band
    fallback, no hold, no code-only mode. That is deliberately strict -- a change the code would have made
    anyway does not become the model's because the model was also asked.
    """
    changes = intent_changes(rows)
    if not changes:
        return None
    def by_model(r):
        sel = r.get("select") or {}
        return bool(r.get("answers")) and not sel.get("fallback") and not sel.get("held")
    return sum(1 for r in changes if by_model(r)) / len(changes)


def decision_reasons(rows):
    """Why a decision was not the model's, broken down. Charter 7 measures `jev_share`; this says what
    the other share is made of, because the four causes call for four different fixes.

      asked and used     the model answered and code did not overrule it: this is `jev_share`
      unsure band        the two best candidates were within `unsure_gap`, so the exact rule settled it
      held               commitment: already walking somewhere and the new pick did not beat the margin
      unavailable        the model could not be reached in time and the rule stood in for it
      cached             an identical state, answered from the within-run cache (charter 3.4)
      no answers         nothing was asked, or nothing came back: there were no candidates to score
      gave up            the committed target stopped getting closer and was abandoned by rule

    Counted over every control decision rather than over intent changes, because "how often was the model
    in charge" and "how often did the answer change anything" are different questions and conflating them
    is how a fallback rate hides behind a share.
    """
    out = Counter()
    for r in rows:
        if r.get("kind") != "control":
            continue
        sel = r.get("select") or {}
        fb = sel.get("fallback")
        if r.get("unavailable") or (r.get("model") or "").startswith("code (fallback)"):
            out["unavailable"] += 1
        elif not r.get("answers"):
            out["no answers"] += 1
        elif fb == "no answers":
            out["no answers"] += 1
        elif fb:
            out["unsure band"] += 1
        elif sel.get("held"):
            out["held"] += 1
        elif sel.get("gave_up"):
            out["gave up"] += 1
        elif r.get("cached"):
            out["cached"] += 1
        else:
            out["asked and used"] += 1
    total = sum(out.values())
    return {k: round(v / total, 4) for k, v in out.most_common()} if total else {}


def fallback_rate(rows):
    """Decisions settled by the unsure band or a rule rather than by the answer."""
    judged = [r for r in rows if r.get("kind") == "control" and (r.get("select") or {})]
    if not judged:
        return None
    return sum(1 for r in judged if (r["select"] or {}).get("fallback")) / len(judged)


def _mode_samples(rows, mode):
    out = []
    for r in rows:
        raw = r.get("raw") or {}
        if r.get("mode") == mode and raw.get("POS_X") is not None and raw.get("ANGLE") is not None:
            out.append((r.get("episode"), float(raw["POS_X"]), float(raw["POS_Y"]), float(raw["ANGLE"]),
                        float(r.get("t") or 0.0)))
    return out


def speed_explore(rows):
    """Mean units per second while exploring. The charter's phase 2 exit test is a fraction of this.

    `elapsed` skips gaps over five seconds, which is right -- an episode boundary is not travel -- but
    when a mode's samples are mostly separated by such gaps the denominator collapses to the 1e-6 floor
    while the numerator keeps the whole distance. That is how the oracle ladder came back with a speed of
    401,352,305 units a second. A window shorter than one tic is not a window, and this says so instead
    of dividing by it.
    """
    s = _mode_samples(rows, "EXPLORE")
    if len(s) < 2:
        return 0.0
    seconds = elapsed(s)
    return straight_units(s) / seconds if seconds >= 1.0 / 35.0 else 0.0


def coverage_rate(rows):
    """New CELL_UNITS cells per minute of play."""
    s = samples(rows)
    minutes = elapsed(s) / 60.0
    return len(cells(s)) / minutes if minutes > 0 else 0.0


def revisit_fraction(rows):
    """Share of decisions taken in a cell first walked more than REVISIT_AGE_S ago."""
    s = samples(rows)
    if not s:
        return 0.0
    first, revisits = {}, 0
    for ep, x, y, _a, t in s:
        c = (ep, round(x / CELL_UNITS) * CELL_UNITS, round(y / CELL_UNITS) * CELL_UNITS)
        if c in first and t - first[c] > REVISIT_AGE_S:
            revisits += 1
        first.setdefault(c, t)
    return revisits / len(s)


def idle_fraction(rows):
    """Share of one-second windows in which the player moved less than IDLE_UNITS_PER_S."""
    s = samples(rows)
    if len(s) < 2:
        return 0.0
    idle = total = 0
    i = 0
    while i < len(s):
        t0, ep = s[i][4], s[i][0]
        w = [x for x in s[i:] if x[0] == ep and x[4] - t0 < 1.0]
        if len(w) < 2 or w[-1][4] - t0 < 0.5:
            i += max(1, len(w))
            continue
        total += 1
        if math.hypot(w[-1][1] - w[0][1], w[-1][2] - w[0][2]) < IDLE_UNITS_PER_S:
            idle += 1
        i += len(w)
    return idle / max(1, total)


def watchdog_trips(rows):
    """How many times an invariant had to pull the pilot out, by reason."""
    out, prev = Counter(), None
    for r in rows:
        if r.get("kind") != "control":
            continue
        mode = r.get("mode")
        if mode == "RECOVER" and prev != "RECOVER":
            out[(r.get("select") or {}).get("recover_reason") or "recover"] += 1
        prev = mode
    return dict(out)


def tokens_per_decision(rows):
    tok = [(r.get("usage") or {}).get("input_tokens", 0) for r in rows if r.get("usage")]
    return sum(tok) / len(tok) if tok else 0.0


def deaths(rows):
    """Episode restarts that were not a level being finished."""
    return sum(1 for r in rows if r.get("kind") == "episode" and r.get("reason") == "died")


def deaths_per_minute(n_deaths, game_seconds):
    """Deaths against time played.

    Added when the onboard executor raised EXPLORE speed from 66 to about 180 units per second and the
    dev set went from 34 deaths in 30 attempts to 142. Going faster is only an improvement if it does not
    cost more than it buys, and a suite score can hide the trade because a death and a slow walk both end
    up as "did not finish". This is the number that does not hide it.
    """
    minutes = (game_seconds or 0.0) / 60.0
    return (n_deaths / minutes) if minutes > 0 else 0.0


def mode_share(rows):
    """Share of decisions spent in each mode. Context for every other number."""
    ctl = [r for r in rows if r.get("kind") == "control"]
    c = Counter(r.get("mode") or "?" for r in ctl)
    return {k: round(v / len(ctl), 4) for k, v in c.most_common()} if ctl else {}


def deaths_by_mode(rows):
    """Which mode the player was in when it died.

    A suite score cannot tell "died exploring" from "died fighting", and the two call for opposite
    changes: the first is an executor safety problem and belongs to code, the second is a fight-or-avoid
    judgement and belongs to the model. Reading a jev-versus-code row without this split is how a loss on
    navigation gets mistaken for a loss on combat.
    """
    out, last = Counter(), None
    for r in rows:
        if r.get("kind") == "control":
            last = r.get("mode") or "?"
        elif r.get("kind") == "episode" and r.get("reason") == "died":
            out[last or "?"] += 1
    return dict(out)
