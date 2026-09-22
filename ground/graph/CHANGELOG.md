# Decision graph changelog

Every version System Two wrote, with its rationale. Version 1 restarts the numbering: the graph before it --
one Choice over eight near-identical options, plus `advance`, `use`, `fire`, `dodge`, `turn` and `weapon` --
is kept in `ground/graph_archive_way_choice_run/` with its own changelog, and the reasons it was replaced are
in `docs/audit-2026-09-22.md`.

A revision that breaks a bound code enforces is now **rejected** with the reason and sent back for one more
try, so a rationale in this file can no longer describe an edit that never landed.

## v1 (defaults)
Initial graph: one Score per open sector, one danger Score, one goal Choice; every exact rule in code.

## v2 (claude-sonnet-5)
Fixed the hard constraint: sector_margin(0.55)+commit_bonus(0.35)=0.9, under the 1.0 cap.

Two AAR-driven changes:
1. Sector rubric's "dead end" tier now checks `sectors.{dir}.tried_recently` (previously unused field). revisit_ratio=0.86, one tile visited 68x, 60 spin_windows, and median_top_two_gap only 0.09 (80/185 picks fell to "unsure") show scores weren't distinguishing recently-tried ground from fresh ground, causing directionless spin.
2. select.tried_penalty raised 1.0->1.8 to reinforce that on the selection side, targeting the same revisit/spin numbers.

Goal and danger heads left unchanged: goal confidence 0.83 with sane answers, danger asked only once with a clean read (ticks_with_enemy_in_view=1) — no signal to revise yet.
