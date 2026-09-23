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
    ("1. target (the navigator)",
     "one candidate place to go, in words: what it is (unexplored edge / a door / the level exit / a key / "
     "a pickup), how far along the floor, how far COMPARED WITH the other candidates, its direction, how "
     "much unseen ground lies behind it, how far that runs, how wide the way on is, what is standing near "
     "it, whether it has been tried, whether it leads away from where the level began, and what gate is in "
     "the way (none / a door / a locked door and whether its key is held). No coordinates and no numbers "
     "reach jev: the world position rides in the INTENT, where code uses it to aim",
     "Score on a nine-level rubric, worst first: not reachable / a bad trade / nothing behind it / worth "
     "it nearer / a fair next step / worth a detour / the obvious move / the way on / the way out",
     "once per candidate, up to eight, on every decision (about twice a second) whenever more than one "
     "place is on offer. One candidate is not a choice and is not asked",
     "code ranks the scores, then holds what it is already walking to unless another beats it by a margin "
     "-- a frontier RECEDES as you explore, so commitment matches a neighbourhood and not an exact cell. "
     "Below unsure_gap (0.05 rubric levels) or below unsure_conf the answer is not used, and the ONE "
     "fallback the brief allows applies: keep the current target, else take the nearest way on"),
    ("2. need",
     "health, armor and ammunition against the thresholds in knowledge/doom_rules.yaml, as urgency words",
     "Score each of health / armor / ammo: urgent / wanted / nice to have / none",
     "every goal_every decisions",
     "code re-weights which pickups are offered as candidates at all: a detour is only worth making for "
     "something the player actually needs now"),
    ("3. engage",
     "what is in view and how dangerous the knowledge file says that class is, how many, how far, against "
     "health, armor and what is loaded -- and what else there is to be doing",
     "Choice: Fight where I stand / Fight while moving / Break off and go round / Retreat",
     "whenever something is in view, in any mode",
     "code sets the INTENT's mode and stance from it. The backstop when it is not asked is deliberately "
     "NEUTRAL (break off and keep moving): a baseline that picks fights is the most dangerous player in "
     "its own comparison, and a row built on one measures the code's recklessness, not the model's "
     "judgement"),
    ("4. weapon",
     "the enemy class, distance and count against the weapons owned that have ammunition",
     "Choice among the owned weapons: Fist / Pistol / Shotgun / Chaingun / RocketLauncher",
     "with the engage head",
     "the slot rides in the INTENT and the executor selects it. A rule backstop overrides one case the "
     "model should not be trusted with: never a rocket at point blank"),
    ("Code: the payload's world model (onboard, 35 Hz)",
     "exact level geometry from the engine, GATED: a line reaches the pilot only once the automap has "
     "drawn half the points sampled along it. Sightlines against those lines say which floor has been "
     "seen; floor heights say which rises can be climbed, which are ledges, and which sectors are shut "
     "doors rather than solid pillars",
     "not jev: measurement and bookkeeping",
     "every tic; the candidate list is rebuilt a few times a second",
     "frontiers (the edge of the seen), doors, the exit if one has been looked at, and pickups, each with "
     "its path distance -- pruned to the eight the ground scores. A live guardrail fails any run holding a "
     "line the automap cannot account for"),
    ("Code: the onboard executor (charter 3.1)",
     "the payload's own fast sensing every tic: position, heading, what the range camera reports ahead and "
     "on each shoulder, what is at arm's length, what is in view",
     "not jev: it carries out the INTENT it was last given, and drops to safe behaviour when the time to "
     "live runs out",
     "every tic, 35 Hz, between decisions",
     "follows the planned path, re-acquiring it when the player has come off; throttles by how much room "
     "there is to turn in rather than by a fixed angle; sidesteps what the camera sees; aims and fires; "
     "pulses Use at a door; takes a panorama on new ground. The ground never sends buttons"),
    ("Code: the watchdog",
     "where the player has been over the last four seconds",
     "not jev: invariants checked at control rate",
     "every tic",
     "trips when the player covers no ground, and ALSO when it covers plenty and gets nowhere -- a wedged "
     "player flails, and flailing is motion, so a test that only measures distance reads it as healthy. "
     "The recovery retreats to a cell the player has already stood in, which is walkable by demonstration "
     "rather than by inference"),
    ("System Two (Claude Sonnet 5)",
     "the episode report and the current graph",
     "not jev: a revised graph with a rationale, which code validates and may reject",
     "after an episode, when it is enabled",
     "it was OFF for the run that finished E1M1 and for every measurement beside it, so nothing here is "
     "owed to it"),
]

FOOTER = ("Four heads, all judgements with no exact rule behind them; everything else is code. One call carries "
          "them all: on the decision that found the exit on 24 Sep 2026 -- jev-1.13.0, 354 ms, 5,232 input "
          "tokens -- eight target scores, the engage choice and the weapon choice came back together, and the "
          "decision age from observation to command was 481 ms against a 900 ms budget.")

# One real decision, from the flight that finished E1M1 on 24 September 2026: the tic the exit first
# entered the candidate list. jev-1.13.0, request req_01a0cdc29a2674a9abccb11b0b42b85d, 354 ms, 5,232
# input tokens and 227 out (research/out/flight-e1m1-5/attempt-E1M1-1.json, tic 3244).
FLOW = [
    ("Payload telemetry through F Prime, CCSDS and Yamcs -- tic 3244, 92.7 s into the level", GREY, [
        "health 33, armor 0, shotgun loaded; one Zombieman in view at mid-range",
        "eight candidate places, each with a world position, a path distance, how much unseen ground lies "
        "behind it, how wide the way on is and what is standing near it",
        "one of them is the level exit: the automap drew that line 166 units away, the first time this "
        "attempt has seen it",
        "the position and the distances are for CODE to aim and plan with; none of them reach the model"]),
    ("telemetry -> words: bands, comparisons and categories, one vocabulary. No coordinate, no number", None, None),
    ("State document (code, no model)", GREY, [
        "here: mode explore, health critical, armor none, ammunition ready, keys none, stuck no",
        "needs: health urgent, ammo none, armor wanted",
        "combat: a straggler, Zombieman, one, mid-range",
        "t0 -- what the level exit, how_far close, relative_distance nearer than most, direction "
        "behind-left, unseen_ground_behind_it none, tried_before no, threat none",
        "t3 -- what unexplored edge, the_way_on_is a doorway, unknown_runs a fair way, gate none, "
        "further_from_the_start about as far out, threat none"]),
    ("HTTPS POST /v1/systemone: one call, eight target questions plus engage plus weapon", None, None),
    ("jev-1.13.0, one request, 354 ms, 5,232 input tokens (req_01a0cdc29a2674a9abccb11b0b42b85d)", ORANGE, [
        "target  t0 7.02 (the exit, confidence 0.56)  t3 5.60  t1 5.49  t2 5.34  t7 4.89  t5 4.64  "
        "t6 3.74  t4 1.03",
        "engage  Retreat (confidence 0.82)",
        "weapon  Shotgun (confidence 0.81)",
        "the need head is asked every goal_every decisions, and was not asked on this one"]),
    ("eight scores on a nine-level rubric, two choices, a confidence each", None, None),
    ("Code rules", GREEN, [
        "top two 7.02 against 5.60: a gap of 1.42 rubric levels, well clear of unsure_gap, so jev's "
        "ranking stands and the exit is the target",
        "commitment: the margin to beat is 1.2 levels and nothing beats the exit, so it is committed to",
        "engage Retreat -> mode RETREAT, stance retreat: back away from the Zombieman while going for it",
        "use_at_target is set, because the thing being walked to is something you open"]),
    ("one INTENT per decision, with a time to live", None, None),
    ("INTENT(mode=RETREAT, target=2928,-4720, stance=retreat, fire=any attacker, use_at_target, ttl=1500ms)",
     BLUE, [
        "Yamcs HTTP -> CCSDS TC -> UDP -> F Prime CmdDispatcher -> Doom component -> the onboard executor",
        "telemetry was 83 ms old, jev took 354 ms, the command took 44 ms: 481 ms from observation to "
        "effect, against a 900 ms budget",
        "the executor carries this out at 35 Hz for up to 1.5 s without asking anything -- the player "
        "does not stand still waiting for the next answer",
        "12.3 seconds later the level ended"]),
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
