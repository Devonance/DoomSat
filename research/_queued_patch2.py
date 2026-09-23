"""The second queued batch: seen coverage, brief section 3. Applied once the ladder is off the machine.

    percent of the grader's reachable 128-unit cells that the pilot's world model marks as seen

Only the grader can finish that sum, because only the grader may know which cells are reachable. The
pilot hands over what it believes it has seen and nothing else.
"""
import io
import sys

RUNNER_A = ('research/runner.py',
            '    geom_stats = p.geom.stats() if getattr(p, "geom", None) is not None else None',
            '    geom_stats = p.geom.stats() if getattr(p, "geom", None) is not None else None\n'
            '    # Brief section 3. The pilot says which 32-unit cells it believes it has seen; the\n'
            '    # grader owns the denominator, because reachability is a fact about the level file.\n'
            '    seen_cells = sorted(p.explorer.free) if p.explorer is not None else []')

RUNNER_B = ('research/runner.py',
            '            "tic_rate": round(tic / max(1e-6, time.time() - t_wall), 1),\n'
            '            "tic_cost": tic_cost,',
            '            "tic_rate": round(tic / max(1e-6, time.time() - t_wall), 1),\n'
            '            "tic_cost": tic_cost, "seen_cells": seen_cells,')

SCORE_A = ('research/grader/score.py',
           '        "progress": round(prog, 4),\n        "progress_best": round(prog_best, 4),',
           '        "progress": round(prog, 4),\n        "progress_best": round(prog_best, 4),\n'
           '        "seen_coverage": seen_coverage(field, attempt.get("seen_cells")),')

SCORE_B = ('research/grader/score.py',
           'def field_for(wad_path, map_name):',
           'def seen_coverage(field, seen_cells, grid=128):\n'
           '    """Share of the level\'s reachable floor the pilot believes it has seen.\n'
           '\n'
           '    Brief section 3, and it lives here because only the grader may know which cells are\n'
           '    reachable. The pilot counts on a 32-unit grid and the charter counts coverage on 128, so\n'
           '    its cells are folded up to the coarser one before the two sets are compared.\n'
           '    """\n'
           '    if not seen_cells:\n'
           '        return None\n'
           '    reachable = field.reachable_cells(grid)\n'
           '    if not reachable:\n'
           '        return None\n'
           '    seen = {(int(math.floor((cx + 0.5) * 32 / grid)), int(math.floor((cy + 0.5) * 32 / grid)))\n'
           '            for cx, cy in seen_cells}\n'
           '    return round(len(seen & reachable) / len(reachable), 4)\n'
           '\n'
           '\n'
           'def field_for(wad_path, map_name):')

WAD = ('research/grader/wad.py',
       '    def at(self, x, y, search=8):',
       '    def reachable_cells(self, grid=128):\n'
       '        """Every `grid`-unit cell the exit can be reached from: the denominator of seen coverage.\n'
       '\n'
       '        A cell counts when any of the field\'s own 16-unit cells inside it has a finite distance to\n'
       '        the exit. That is the grader\'s own definition of reachable, coarsened, so the number means\n'
       '        "of the level a player could have walked, how much did the pilot see".\n'
       '        """\n'
       '        out = set()\n'
       '        span = grid // CELL\n'
       '        for i, d in enumerate(self.dist):\n'
       '            if d == float("inf"):\n'
       '                continue\n'
       '            cx, cy = i % self.w, i // self.w\n'
       '            wx = self.origin[0] + (cx + 0.5) * CELL\n'
       '            wy = self.origin[1] + (cy + 0.5) * CELL\n'
       '            out.add((int(math.floor(wx / grid)), int(math.floor(wy / grid))))\n'
       '        return out\n'
       '\n'
       '    def at(self, x, y, search=8):')

GRADE = ('research/grade.py',
         '        "mean_progress_best": round(statistics.fmean([r["progress_best"] for r in usable]), 4) if usable else None,',
         '        "mean_progress_best": round(statistics.fmean([r["progress_best"] for r in usable]), 4) if usable else None,\n'
         '        "seen_coverage": (round(statistics.fmean([r["seen_coverage"] for r in graded\n'
         '                                                 if r.get("seen_coverage") is not None]), 4)\n'
         '                          if any(r.get("seen_coverage") is not None for r in graded) else None),')

EDITS = [RUNNER_A, RUNNER_B, SCORE_A, SCORE_B, WAD, GRADE]


def main():
    bad = 0
    for path, old, new in EDITS:
        text = io.open(path, encoding="utf-8").read()
        if new in text:
            print("  %s: already applied" % path)
            continue
        if old not in text:
            print("  MISSING %s: %r" % (path, old.splitlines()[0][:70]))
            bad += 1
            continue
        io.open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))
        print("  %s: patched" % path)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
