"""Figures of jev's decision graph for the README (Graphviz PNG/SVG, dot in the WSL distro) and for the PDF report
(native LaTeX, so the text is real text and the tables break across pages):

  docs/diagrams/decision_graph.{dot,png,svg}   the graph as a table: state words -> typed question -> when asked ->
                                               the code rule that consumes the answer (rover-demo style)
  docs/diagrams/decision_flow.{dot,png,svg}    one real decision end to end, with the numbers and probabilities logged
  docs/decision_graph_table.tex                the same table as a longtable (\\input by tools/md_to_tex.py)
  docs/decision_flow.tex                       the same worked decision as stacked boxes

    python tools/decision_figures.py
"""
import os
import subprocess
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
OUT = os.path.join(DOCS, "diagrams")
BG, CELL, TXT, DIM = "#0f1116", "#161a22", "#d8dde6", "#8b93a1"
GREY, ORANGE, BLUE, GREEN, PURPLE = "#4a5160", "#d9a441", "#4f8fd6", "#3fae6a", "#8f6fe0"
FONT = "DejaVu Sans Mono"


def cell(text, width=44):
    """Wrap text and left-justify each line (\\l) for a Graphviz box label."""
    lines = []
    for para in text.split("\n"):
        lines.extend(textwrap.wrap(para, width) or [""])
    return "\\l".join(l.replace('"', '\\"') for l in lines) + "\\l"


def tex(s):
    """Escape LaTeX specials in plain text."""
    s = s.replace("\\", r"\textbackslash{}")
    for a, b in (("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
                 ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"), ("<", r"\textless{}"), (">", r"\textgreater{}")):
        s = s.replace(a, b)
    s = s.replace(r"-\textgreater{}", r"$\rightarrow$").replace(">=", r"$\geq$").replace("´", r"\'{}")
    return s


ROWS = [
    ("1. sector (the navigator)",
     "that one sector's words: space (blocked / tight / open / long), ground (never explored / new / partly "
     "walked / walked before / unknown), door (none or a distance band), and whether the exit, a key, the "
     "ground hint or a pickup lies there. Every bearing in the state is binned into the same eight labels",
     "Score on a shared four-level rubric: dead end / leads on but old / worth a look / the way on",
     "once per open direction, every tick (~0.5 s), in EXPLORE and APPROACH; a blocked direction and one "
     "with missing telemetry are not offered",
     "code ranks the scores, adds the goal's weight and subtracts a level from a direction just held "
     "without getting anywhere, then keeps the committed WORLD BEARING unless another sector beats it by "
     "sector_margin (capped below one rubric level, so a whole level always wins); a top-two gap under "
     "unsure_gap (0.10, calibrated from replay) goes to the named frontier fallback"),
    ("2. danger",
     "the nearest enemy in the sector vocabulary with a distance band, how many are in view, health and "
     "ammunition bands, and which sides are open",
     "Score on four levels: no danger / a fight to win / under fire / get out",
     "whenever an enemy is in view, in any mode",
     "at or above danger_sidestep (1.5) code strafes into the open side, preferring a long passage; at or "
     "above danger_retreat (2.5) it backs off. Firing, the weapon and the aim are not asked: they are exact "
     "rules over numbers code already has"),
    ("3. goal",
     "health, armor, ammunition, the enemy, and where the exit, a key and each pickup were seen -- all in "
     "the same eight direction labels; the standing order rides on this question, not in the state",
     "Choice: Explore / Scout / Kill enemies / Restore health / Stock ammo / Add armor",
     "every goal_every ticks (10)",
     "SET_GOAL, and a real effect on the next decisions: goal_bonus levels are added to the sector holding "
     "that goal's pickup, and SCOUT weights never-explored ground"),
    ("Code: the mode machine",
     "stuck, what is at arm's length, whether an enemy is in view, whether the level is finished",
     "not jev: an explicit state machine, every transition an exact rule",
     "every tick, before jev is asked",
     "EXPLORE / APPROACH ask jev; OPERATE (press Use, give up after door_tries), RECOVER (back out until "
     "64 units moved) and DONE are pure code, so those ticks make no model call at all"),
    ("Code: the reflex layer",
     "the same state, plus the turn still in flight",
     "not jev: invariants that hold under every mode",
     "on every command, last",
     "never fire at zero ammo; never walk into a known wall (unless it is a door to walk up to); never "
     "re-command a turn still swinging; clamp the turn to max_turn_deg"),
    ("System Two: bump (Claude Sonnet 5)",
     "seconds into the attempt, cells gained, position, most visited spots, the map product as text",
     "not jev: a JSON-schema reply with bearing, hold time and an optional goal",
     "every 60 s",
     "EXPLORE_HINT(bearing, ttl): the payload steers 'ahead' toward the bearing while it lasts, and the "
     "sector it falls in reads hint_here yes; jev still scores every open direction"),
    ("System Two: after-action (Claude Sonnet 5)",
     "the episode report, built from the heads the episode actually asked: outcome, health, damage, cells, "
     "distance, spin windows, the score distribution per head, what the selection did (held, fallbacks, "
     "gaps), the modes, the last eight decisions, plus the current graph and the bounds code enforces",
     "not jev: a revised graph (question wording, rubric levels, thresholds, selection numbers) with a "
     "rationale",
     "after every episode: death, level done, or the 180 s budget",
     "code validates and REJECTS anything out of bounds -- overlong text, a number out of range, an "
     "unknown head or option, a criterion naming a state field that does not exist -- and hands the reason "
     "back for one more try, then stores graph_v<N>.json"),
]

FOOTER = ("Three heads, all judgments with no exact rule behind them; everything else is code. Replaying 120 logged "
          "states on 22 Sep 2026: 2,263 median input tokens per call, 461 ms median, and jev's own ranking "
          "reproducible between identical passes on every state where the top two sat 0.10 rubric levels apart "
          "or more (0 of 51), against 30% flipping below that.")

# one real decision, replayed live against graph v1: request req_01a0ca7e70fd7c8289c901853c0bd2d7,
# jev-1.13.0, 330 ms, 2452 input tokens (runs/2026-09-22/worked_decision.json)
FLOW = [
    ("Yamcs parameters (12 Hz), this tick", GREY, [
        "CLEAR ahead 143, ahead-left 192, left 348, behind-left 400, behind 400, behind-right 400, right 284, ahead-right 328 (units)",
        "NEW ahead 100, ahead-left 255, left 100, behind-left 100, behind 100, behind-right 88, right 100, ahead-right 238",
        "DOOR all 0 except ahead-right (a door on that ray); AHEAD_KIND NOTHING, EXIT_DIST 0, STUCK false, ENEMY_COUNT 0",
        "POS 1056,-3034, ANGLE 90, EXPLORED_CELLS 19, LEVEL 1, KEYS 0"]),
    ("telemetry -> words: bands, novelty, one door field, one direction vocabulary; no number reaches jev", None, None),
    ("State document (code, no model). Only `sectors` is sent: nothing else is inspected this tick", GREY, [
        "ahead: space open, ground new",
        "ahead-left: space open, ground never explored",
        "left / behind-left / behind / behind-right / right: space long, ground new",
        "ahead-right: space long, ground unknown, door mid-range",
        "every sector also carries exit_here, key_here, item_here, hint_here, tried_recently (all no here)"]),
    ("HTTPS POST /v1/systemone: the state plus one Score question per open direction, same rubric", None, None),
    ("jev, one request, 330 ms, 2452 input tokens (req_01a0ca7e70fd7c8289c901853c0bd2d7)", ORANGE, [
        "s_ahead-left  2.98 (confidence 0.98)   <- the only never-explored direction",
        "s_behind 2.06, s_left 2.04, s_behind-right 2.04, s_behind-left 2.03",
        "s_right 2.02, s_ahead 2.01, s_ahead-right 1.97",
        "the goal head was not asked this tick (every 10th); the danger head only when an enemy is in view"]),
    ("eight scores on a four-level rubric, and a confidence each", None, None),
    ("Code rules", GREEN, [
        "top two 2.98 vs 2.06: a gap of 0.92 levels, well clear of unsure_gap (0.20), so jev's ranking stands",
        "no commitment yet this episode, so no hysteresis to apply; commit the WORLD bearing 90+45 = 135 degrees",
        "ahead-left is not straight on: turn 45 degrees and do not walk this tick",
        "reflex: ammunition is zero so fire stays off; the turn is inside max_turn_deg; no turn is in flight"]),
    ("one command per decision", None, None),
    ("CONTROL(move=0, strafe=0, turn=+45, fire=0, use=0, weapon=FIST meaning keep)", BLUE, [
        "Yamcs HTTP -> CCSDS TC -> UDP -> F Prime CmdDispatcher -> Doom component -> payload turn setpoint (6 deg per tic)",
        "the next tick will not be judged until that turn has landed, so the sectors are never read mid-swing"]),
]

def decision_graph_dot():
    g = [f'digraph G {{',
         f'  graph [bgcolor="{BG}", fontname="{FONT}", fontcolor="{TXT}", labelloc=t, labeljust=l, nodesep=0.35, ranksep=0.25, pad=0.4,',
         f'         label="DOOMSAT . DECISION GRAPH . one narrow typed question per head, over words that code made from telemetry; every answer is consumed by a rule\\l'
         f'{FOOTER}\\l"];',
         f'  node [shape=box, style="rounded,filled", fillcolor="{CELL}", fontname="{FONT}", fontsize=11, fontcolor="{TXT}", penwidth=1.4, margin="0.18,0.12"];',
         f'  edge [color="{GREY}", arrowhead=none, penwidth=1.0];']
    heads = [("STATE (what code turns into words)", GREY), ("JEV . TYPED QUESTION", ORANGE), ("WHEN ASKED", BLUE), ("RULE THAT CONSUMES THE ANSWER", GREEN)]
    g.append('  { rank=same; ' + '; '.join(f'h{i} [shape=plaintext, fillcolor="{BG}", fontcolor="{c}", label="{t}"]' for i, (t, c) in enumerate(heads)) + ' }')
    g.append('  h0 -> h1 -> h2 -> h3 [style=invis];')
    prev = "h0"
    for r, row in enumerate(ROWS):
        name, state, q, when, rule = row
        system_two = name.startswith("System Two")
        cols = [(f"{name}\\l\\l{cell(state, 46)}", PURPLE if system_two else GREY),
                (cell(q, 40), PURPLE if system_two else ORANGE), (cell(when, 26), BLUE), (cell(rule, 54), GREEN)]
        ids = []
        for c, (label, colour) in enumerate(cols):
            nid = f"r{r}c{c}"
            ids.append(nid)
            g.append(f'  {nid} [label="{label}", color="{colour}"];')
        g.append('  { rank=same; ' + '; '.join(ids) + ' }')
        g.append('  ' + ' -> '.join(ids) + ';')
        g.append(f'  {prev} -> {ids[0]} [style=invis];')
        prev = ids[0]
    g.append('}')
    return "\n".join(g)


def decision_flow_dot():
    g = ['digraph F {',
         f'  graph [bgcolor="{BG}", rankdir=TB, fontname="{FONT}", fontcolor="{TXT}", labelloc=t, labeljust=l, nodesep=0.3, ranksep=0.35, pad=0.4,',
         f'         label="DOOMSAT . ONE DECISION END TO END (graph v1, jev-1.13.0, 22 Sep 2026)\\l"];',
         f'  node [shape=box, style="rounded,filled", fillcolor="{CELL}", fontname="{FONT}", fontsize=11, fontcolor="{TXT}", penwidth=1.4, margin="0.2,0.12"];',
         f'  edge [color="{DIM}", fontname="{FONT}", fontsize=10, fontcolor="{DIM}", penwidth=1.2];']
    boxes = [(t, c, body) for t, c, body in FLOW if body]
    labels = [t for t, c, body in FLOW if not body]
    for i, (title, colour, body) in enumerate(boxes):
        g.append(f'  b{i} [label="{cell(title + chr(10) + chr(10).join(body), 62)}", color="{colour}"];')
    for i, lab in enumerate(labels):
        g.append(f'  b{i} -> b{i + 1} [label=" {lab}"];')
    g.append('}')
    return "\n".join(g)


def decision_graph_tex():
    head = r"\textbf{Head and the words it sees} & \textbf{Typed question} & \textbf{When asked} & \textbf{Rule that consumes the answer} \\"
    out = [r"\begingroup\footnotesize",
           r"\begin{longtable}{L{0.27\textwidth} L{0.21\textwidth} L{0.11\textwidth} L{0.29\textwidth}}",
           r"\caption{jev's decision graph: what code turns into words, the typed question, when it is asked, and the "
           r"rule that consumes the answer. " + tex(FOOTER) + r"}\\",
           r"\toprule", head, r"\midrule", r"\endfirsthead",
           r"\toprule", head, r"\midrule", r"\endhead", r"\bottomrule", r"\endfoot"]
    body = []
    for name, state, q, when, rule in ROWS:
        body.append(r"\textbf{" + tex(name) + r"}\newline " + tex(state) + " & " + tex(q) + " & " + tex(when) + " & " + tex(rule) + r" \\")
    out.append(" \\rowrule\n".join(body))
    out += [r"\end{longtable}", r"\endgroup"]
    return "\n".join(out)


def decision_flow_tex():
    out = [r"\begin{figure}[htbp]\centering\small\setlength{\parskip}{1pt}\setlength{\fboxsep}{5pt}\setlength{\fboxrule}{0.7pt}"]
    for title, colour, body in FLOW:
        if body:
            inner = r"\textbf{" + tex(title) + r"}\par " + r"\par ".join(r"\texttt{" + tex(l) + "}" for l in body)
            out.append(r"\fcolorbox{black!50}{black!4}{\begin{minipage}{\dimexpr\linewidth-2\fboxsep-2\fboxrule}\raggedright " + inner + r"\end{minipage}}")
        else:
            out.append(r"\par\vspace{1pt}$\downarrow$\enspace\emph{" + tex(title) + r"}\par\vspace{1pt}")
    out.append(r"\caption{One real decision end to end (graph v1, jev-1.13.0, 22 September 2026): the "
               r"numbers Yamcs delivered, the words code made from them, jev's probabilities, the code rules and the "
               r"command that went up.}")
    out.append(r"\end{figure}")
    return "\n".join(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, text in (("decision_graph", decision_graph_dot()), ("decision_flow", decision_flow_dot())):
        with open(os.path.join(OUT, name + ".dot"), "w", encoding="utf-8") as f:
            f.write(text)
    for name, text in (("decision_graph_table.tex", decision_graph_tex()), ("decision_flow.tex", decision_flow_tex())):
        with open(os.path.join(DOCS, name), "w", encoding="utf-8") as f:
            f.write(text + "\n")
    wsl_dir = "/mnt/c" + os.path.abspath(OUT).replace("\\", "/")[2:]
    names = ("decision_graph", "decision_flow", "dataflow", "architecture")
    cmd = " && ".join(f"dot -T{fmt} -Gdpi={dpi} {n}.dot -o {n}.{fmt}" for n in names for fmt, dpi in (("png", 200), ("svg", 96)))
    subprocess.run(["wsl", "-d", "ros2", "bash", "-c", f"cd '{wsl_dir}' && {cmd}"], check=True)
    print("wrote", OUT, "and the tex fragments in", DOCS)


if __name__ == "__main__":
    main()
