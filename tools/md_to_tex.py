"""Convert the report Markdown (docs/doomsat-report.md) to LaTeX and build the PDF with tectonic.

    python tools/md_to_tex.py            # writes docs/doomsat-report.tex and docs/doomsat-report.pdf

Tables become longtables (they break across pages) with ragged-right columns whose widths follow the content and
thin rules between rows. Images become floats capped at a fraction of the page height, with the alt text as caption;
floats never cross a section boundary. Two figures are rebuilt natively in LaTeX rather than included as images:
the decision graph table (docs/decision_graph_table.tex) and the worked decision (docs/decision_flow.tex), both
written by tools/decision_figures.py.
"""
import re
import subprocess
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
SRC = DOCS / "doomsat-report.md"
TEX = DOCS / "doomsat-report.tex"

# images replaced by native LaTeX (path in the markdown -> file to \input)
NATIVE = {"diagrams/decision_graph.png": "decision_graph_table.tex", "diagrams/decision_flow.png": "decision_flow.tex"}

PREAMBLE = r"""\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{booktabs}
\usepackage{array}
\usepackage{colortbl}
\usepackage{longtable}
\usepackage{xcolor}
\usepackage{graphicx}
\usepackage{float}
\usepackage{placeins}
\usepackage{caption}
\usepackage{enumitem}
\usepackage{amsmath}
\usepackage{xurl}
\usepackage{hyperref}
\newcommand{\rowrule}{\arrayrulecolor{black!25}\midrule\arrayrulecolor{black}}
\renewcommand{\arraystretch}{1.15}
\newcolumntype{L}[1]{>{\raggedright\arraybackslash}p{#1}}
\hypersetup{colorlinks=true,linkcolor=blue!50!black,urlcolor=blue!50!black,breaklinks=true}
\captionsetup{font=small,labelfont=bf,skip=4pt}
\setlist{nosep}
\setlength{\parskip}{4pt}
\setlength{\parindent}{0pt}
\setlength{\emergencystretch}{2em}
\definecolor{claude}{HTML}{7A55CC}
\definecolor{jev}{HTML}{2E9E63}
\definecolor{code}{HTML}{3A7BC0}
"""


def esc(s):
    """Escape LaTeX specials in plain text (after inline markup has been converted)."""
    s = s.replace("\\", r"\textbackslash{}")
    for a, b in (("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
                 ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"), ("<", r"\textless{}"), (">", r"\textgreater{}")):
        s = s.replace(a, b)
    s = s.replace(r"-\textgreater{}", r"$\rightarrow$").replace(r"\textless{}-", r"$\leftarrow$")
    s = s.replace("´", r"\'{}").replace("×", r"$\times$").replace("°", r"$^\circ$").replace("–", "--").replace("—", "---")
    s = s.replace("≥", r"$\geq$").replace("≤", r"$\leq$").replace("→", r"$\rightarrow$")
    return s


def inline(s):
    """Inline markdown -> LaTeX: code, bold, italics, links; everything else escaped."""
    out, i = [], 0
    pattern = re.compile(r"`([^`]+)`|\*\*([^*]+)\*\*|\*([^*]+)\*|\[([^\]]+)\]\(([^)]+)\)|(https?://[^\s)]+)")
    for m in pattern.finditer(s):
        out.append(esc(s[i:m.start()]))
        if m.group(1) is not None:
            out.append(r"\texttt{" + esc(m.group(1)) + "}")
        elif m.group(2) is not None:
            out.append(r"\textbf{" + inline(m.group(2)) + "}")
        elif m.group(3) is not None:
            out.append(r"\emph{" + inline(m.group(3)) + "}")
        elif m.group(4) is not None:
            out.append(r"\href{" + m.group(5) + "}{" + inline(m.group(4)) + "}")
        else:
            out.append(r"\url{" + m.group(6) + "}")
        i = m.end()
    out.append(esc(s[i:]))
    return "".join(out)


def col_widths(rows):
    """Column widths (fractions of \\textwidth) from the content: the longest cell per column, floored so that a
    column never starves, scaled to fit with the column separators."""
    n = len(rows[0])
    longest = [max(len(r[c]) for r in rows) for c in range(n)]
    # square-root weights: long columns get more room but cannot starve the short ones ("Type", "Rate")
    weights = [max(14.0, min(l, 90.0)) ** 0.5 for l in longest]
    total = 0.98 - 0.026 * n                                 # 2 * tabcolsep per column, roughly
    return [total * w / sum(weights) for w in weights]


def table(lines):
    rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in lines if not re.match(r"^\s*\|?\s*-{2,}", l)]
    n = len(rows[0])
    rows = [(r + [""] * n)[:n] for r in rows]
    widths = col_widths(rows)
    spec = " ".join(f"L{{{w:.3f}\\textwidth}}" for w in widths)
    size = "\\small" if n <= 4 else "\\footnotesize"
    head = " & ".join(r"\textbf{" + inline(c) + "}" for c in rows[0]) + r" \\"
    out = ["\\begingroup" + size, "\\begin{longtable}{" + spec + "}",
           "\\toprule", head, "\\midrule", "\\endfirsthead",
           "\\toprule", head, "\\midrule", "\\endhead",
           "\\bottomrule", "\\endfoot"]
    body = [" & ".join(inline(c) for c in r) + r" \\" for r in rows[1:]]
    out.append(" \\rowrule\n".join(body))
    out += ["\\end{longtable}", "\\endgroup"]
    return "\n".join(out)


def figure(alt, path):
    if path in NATIVE:
        return "\\input{" + NATIVE[path] + "}"
    # per-image height caps: the two diagrams need most of a page to be legible; the end-of-day map is a small square
    caps = {"dataflow.png": "0.9", "architecture.png": "0.75", "final_map.png": "0.33"}
    height = caps.get(path.rsplit("/", 1)[-1], "0.5") + "\\textheight"
    return ("\\begin{figure}[htbp]\\centering\n\\includegraphics[width=\\linewidth,height=" + height +
            ",keepaspectratio]{" + path + "}\n\\caption{" + inline(alt) + "}\n\\end{figure}")


def convert(md):
    lines = md.splitlines()
    out = [PREAMBLE]
    title = lines[0].lstrip("# ").strip()
    byline = lines[2].strip() if len(lines) > 2 else ""
    out.append("\\title{" + inline(title) + "}")
    out.append("\\author{" + inline(byline).replace(". Built with", r"\\\small Built with") + "}")
    out.append("\\date{}\n\\begin{document}\n\\maketitle\n")
    i = 3
    para = []

    def flush():
        if para:
            out.append(inline(" ".join(para)) + "\n")
            para.clear()

    while i < len(lines):
        l = lines[i]
        if l.startswith("## "):
            flush(); out.append("\\FloatBarrier\n\\section*{" + inline(l[3:].strip()) + "}")
        elif l.startswith("### "):
            flush(); out.append("\\subsection*{" + inline(l[4:].strip()) + "}")
        elif l.startswith("!["):
            flush()
            m = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", l)
            out.append(figure(m.group(1), m.group(2)))
        elif l.startswith("|"):
            flush()
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(lines[i]); i += 1
            out.append(table(block)); continue
        elif re.match(r"^\s*[-*] ", l) or re.match(r"^\s*\d+\. ", l):
            flush()
            ordered = bool(re.match(r"^\s*\d+\. ", l))
            out.append("\\begin{enumerate}" if ordered else "\\begin{itemize}")
            while i < len(lines) and (re.match(r"^\s*[-*] ", lines[i]) or re.match(r"^\s*\d+\. ", lines[i]) or (lines[i].startswith("  ") and lines[i].strip())):
                item = re.sub(r"^\s*([-*]|\d+\.) ", "", lines[i])
                i += 1
                while i < len(lines) and lines[i].startswith("  ") and lines[i].strip() and not re.match(r"^\s*([-*]|\d+\.) ", lines[i]):
                    item += " " + lines[i].strip(); i += 1
                out.append("  \\item " + inline(item))
            out.append("\\end{enumerate}" if ordered else "\\end{itemize}")
            continue
        elif not l.strip():
            flush()
        else:
            para.append(l.strip())
        i += 1
    flush()
    out.append("\\FloatBarrier\n\\end{document}")
    return "\n".join(out)


if __name__ == "__main__":
    TEX.write_text(convert(SRC.read_text(encoding="utf-8")), encoding="utf-8")
    print("wrote", TEX)
    r = subprocess.run(["tectonic", "-o", ".", TEX.name], capture_output=True, text=True, cwd=str(DOCS))
    print(r.stdout[-1500:], r.stderr[-2500:])
    sys.exit(r.returncode)
