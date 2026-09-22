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
    ("1. way (the navigator)",
     "eight directions around the player, 45 deg apart, each in words: space (blocked / tight / open / long) and "
     "ground (unexplored / new / partly walked / walked before / a door on the way at N units); what is at arm's "
     "length ahead; where the exit and a key were seen; the goal word",
     "Choice over the directions that are not blocked (2 to 8 options); every option carries what / not_for / "
     "examples criteria plus its own 'now'",
     "every tick (~0.5 s), one request with all heads",
     "turn setpoint by direction: 0 / 45 / 90 / 135 / 180 deg (right = negative); the previous way is kept unless "
     "P(new) >= P(previous) + way_margin (hysteresis on the probabilities); 'behind' with open ground behind = one "
     "step back instead of a U-turn; a turn of 45 deg or more is issued alone and finishes before the next ask"),
    ("2. advance",
     "the same state document; 'ahead' carries space, ground and what is at arm's length",
     "Noul: walk forward this tick?",
     "every tick",
     "move = 1 if P(yes) >= 0.5; suppressed while an enemy is in view and the aim is off by more than aligned_deg (35)"),
    ("3. use",
     "at arm's length ahead: door / exit switch / locked door (with the key colour) / wall / nothing; stuck flag",
     "Noul: press Use now?",
     "only when a door, the exit or a locked door is at arm's length, or the player is stuck",
     "use = 1 if P(yes) >= 0.5; the payload marks a door that stays shut after its presses as a barrier for 120 s"),
    ("4. fire",
     "nearest enemy: bearing in words (in the crosshair / left / right / behind), distance band, health, ammo",
     "Noul: shoot now?",
     "every tick",
     "fire = 1 if P(yes) >= 0.5 and the enemy is within fire_range (450 u) and crosshair_deg (8); never without ammo"),
    ("5. dodge",
     "nearest enemy bearing and distance band; which sides are open",
     "Choice: Carry on / Dodge left / Dodge right / Dodge back (only the open sides are offered)",
     "whenever an enemy is in view",
     "strafe = -1 / +1, or move = -1 for 'Dodge back'; danger_dist (180 u) gates the question's 'close' word"),
    ("6. turn (the aim)",
     "nearest enemy bearing in words",
     "Choice: Hard left / Left / Fine left / Hold / Fine right / Right / Hard right / Turn around",
     "whenever an enemy is in view",
     "overrides the way's turn with the aim table (turn_deg: 60 / 25 / 8 / 0 / -8 / -25 / -60 / 150 deg); a person "
     "does not keep exploring under fire"),
    ("7. weapon",
     "weapon in hand, shells, bullets, enemy distance band",
     "Choice: Keep / Pistol / Shotgun",
     "every tick",
     "weapon field of CONTROL; 'Keep' sends no switch"),
    ("8. goal",
     "health and armor bands, ammo, kills, enemies in view, cells walked, exit seen, pickups seen with bearings",
     "Choice: Explore / Kill enemies / Restore health / Stock ammo / Add armor",
     "every goal_every ticks (8) or when the picture changes",
     "SET_GOAL command; the goal word enters the next state documents and the payload's pickup targeting"),
    ("System Two: bump (Claude Sonnet 5)",
     "seconds into the attempt, cells gained, position, most visited spots, the map product as text",
     "not jev: a JSON-schema reply with bearing, hold time and an optional goal",
     "every 60 s",
     "EXPLORE_HINT(bearing, ttl): the payload steers 'ahead' toward the bearing while it lasts; jev still answers "
     "every head"),
    ("System Two: after-action (Claude Sonnet 5)",
     "the episode report: outcome, health, damage, cells, distance, stuck ticks, answer distributions per head, "
     "the walk, the last eight decisions in words, plus the current graph",
     "not jev: a revised graph (criteria text, thresholds, way_margin, goal_every) with a rationale",
     "after every episode: death, level done, or the 180 s budget",
     "code validates (fixed option names, known placeholders, clamped thresholds), stores graph_v<N>.json, and "
     "jev plays the next attempt with it"),
]

FOOTER = ("Measured on 22 Sep 2026: 5,872 jev decisions through the stack, about 450-520 ms per call with 5-8 heads, "
          "about 45 ms to issue the command; Sonnet: a bump per minute and 14 graph versions in the day.")

# one real decision: request req_01a0c8b54b2c73dd8ec79b57a6f3a1b6, graph v14, episode 7, 22 Sep 2026 10:41:59 UTC
FLOW = [
    ("Yamcs parameters (12 Hz), this tick", GREY, [
        "CLEAR ahead 116, ahead-left 48, left 28, behind-left 20, behind 24, behind-right 248, right 212, ahead-right 120 (units)",
        "NEW ahead 0, ahead-left 100, left 0, behind-left 0, behind 0, behind-right 14, right 50, ahead-right 33",
        "AHEAD_KIND NOTHING, EXIT_DIST 0, STUCK false, ENEMY_COUNT 0, HEALTH 100, ARMOR 0, KILLS 0",
        "POS 1347,-2725, ANGLE 216, EXPLORED_CELLS 544, LEVEL 1, KEYS 0"]),
    ("telemetry -> words (bands, novelty, direction names); no number reaches jev", None, None),
    ("State document (code, no model)", GREY, [
        "ahead: open, walked before, nothing near",
        "ahead-left: tight, new",
        "left / behind-left / behind: blocked, walked before",
        "behind-right: long (a passage or a big room), walked before",
        "right: open, partly walked; ahead-right: open, partly walked",
        "exit: not seen; enemy: none in view; health: full; armor: none; goal word: Explore"]),
    ("HTTPS POST /v1/systemone: the state plus 5 typed questions with their criteria", None, None),
    ("jev, one request, 469 ms (req_01a0c8b54b2c73dd8ec79b57a6f3a1b6)", ORANGE, [
        "way (Choice over the 5 open directions): ahead-left 0.82, ahead 0.14, right 0.03, ahead-right 0.01, behind-right 0.00",
        "advance (Noul): yes 0.75",
        "fire (Noul): no 0.98",
        "weapon (Choice): Keep 0.82, Shotgun 0.18, Pistol 0.00",
        "goal (Choice, this was a goal tick): Add armor 0.86, Explore 0.14"]),
    ("choices with probabilities, Noul probabilities", None, None),
    ("Code rules", GREEN, [
        "way: the previous way 'ahead' holds 0.14; the new one 0.82 >= 0.14 + way_margin, so switch; ahead-left = +45 deg",
        "a turn of 45 deg or more is issued alone: move = 0 this tick, walking resumes when the turn has landed",
        "fire 0.98 no -> fire = 0; use was not asked (nothing at arm's length) -> use = 0",
        "weapon Keep -> no switch",
        "goal Add armor -> SET_GOAL(ADD_ARMOR) on the goal tick; the word 'Add armor' enters the next documents"]),
    ("one command per decision", None, None),
    ("CONTROL(move=0, strafe=0, turn=+45, fire=0, use=0, weapon=no change)", BLUE, [
        "Yamcs HTTP -> CCSDS TC -> UDP -> F´ CmdDispatcher -> Doom component -> payload turn setpoint (6 deg per tic)",
        "issued in 50 ms; F´ events: OpCodeDispatched, OpCodeCompleted"]),
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
         f'         label="DOOMSAT . ONE DECISION END TO END (episode 7, graph v14, 22 Sep 2026 10:41:59 UTC)\\l"];',
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
    out.append(r"\caption{One real decision end to end (episode 7, graph v14, 22 September 2026 10:41:59 UTC): the "
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
