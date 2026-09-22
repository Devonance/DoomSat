"""Convert the report Markdown (docs/doomsat-report.md) to LaTeX with the same preamble style as the rover report,
then build the PDF with tectonic.

    python tools/md_to_tex.py            # writes docs/doomsat-report.tex and docs/doomsat-report.pdf
"""
import re
import subprocess
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
SRC = DOCS / "doomsat-report.md"
TEX = DOCS / "doomsat-report.tex"

PREAMBLE = r"""\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{booktabs}
\usepackage{array}
\usepackage{colortbl}
\usepackage{longtable}
\usepackage{tabularx}
\newcommand{\rowrule}{\arrayrulecolor{black!22}\midrule\arrayrulecolor{black}}
\renewcommand{\arraystretch}{1.18}
\usepackage{enumitem}
\usepackage{hyperref}
\usepackage{xcolor}
\usepackage{graphicx}
\usepackage{amsmath}
\hypersetup{colorlinks=true,linkcolor=blue!50!black,urlcolor=blue!50!black,breaklinks=true}
\setlist{nosep}
\setlength{\parskip}{4pt}
\setlength{\parindent}{0pt}
\definecolor{claude}{HTML}{7A55CC}
\definecolor{jev}{HTML}{2E9E63}
\definecolor{code}{HTML}{3A7BC0}
"""


def esc(s):
    """Escape LaTeX specials in plain text (after inline markup has been converted)."""
    s = s.replace("\\", r"\textbackslash{}")
    for a, b in (("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")):
        s = s.replace(a, b)
    s = s.replace("->", r"$\rightarrow$").replace("<-", r"$\leftarrow$")
    s = s.replace("´", r"\'{}").replace("×", r"$\times$").replace("°", r"$^\circ$").replace("–", "--").replace("—", "---")
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


def table(lines):
    rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in lines if not re.match(r"^\s*\|?\s*-{2,}", l)]
    n = len(rows[0])
    widths = {2: "p{0.28\\textwidth} p{0.66\\textwidth}", 3: "p{0.18\\textwidth} p{0.34\\textwidth} p{0.42\\textwidth}",
              4: "p{0.16\\textwidth} p{0.14\\textwidth} p{0.34\\textwidth} p{0.28\\textwidth}"}
    spec = widths.get(n, " ".join([f"p{{{0.94 / n:.2f}\\textwidth}}"] * n))
    out = ["\\begin{center}\\small", "\\begin{tabular}{" + spec + "}", "\\toprule",
           " & ".join(r"\textbf{" + inline(c) + "}" for c in rows[0]) + r" \\", "\\midrule"]
    for r in rows[1:]:
        r = (r + [""] * n)[:n]
        out.append(" & ".join(inline(c) for c in r) + r" \\ \rowrule")
    out[-1] = out[-1].replace(r" \rowrule", "")
    out += ["\\bottomrule", "\\end{tabular}", "\\end{center}"]
    return "\n".join(out)


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
            flush(); out.append("\\section*{" + inline(l[3:].strip()) + "}")
        elif l.startswith("### "):
            flush(); out.append("\\subsection*{" + inline(l[4:].strip()) + "}")
        elif l.startswith("!["):
            flush()
            m = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", l)
            out.append("\\begin{center}\\includegraphics[width=\\textwidth]{" + m.group(2) + "}\\end{center}")
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
    out.append("\\end{document}")
    return "\n".join(out)


if __name__ == "__main__":
    TEX.write_text(convert(SRC.read_text(encoding="utf-8")), encoding="utf-8")
    print("wrote", TEX)
    r = subprocess.run(["tectonic", "-o", str(DOCS), str(TEX)], capture_output=True, text=True)
    print(r.stdout[-1500:], r.stderr[-1500:])
    sys.exit(r.returncode)
