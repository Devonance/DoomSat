
## v1 (defaults)
Initial graph: the seven control heads and the goal head as designed by hand.

## v2 (claude-sonnet-5)
Level unfinished: revisit_ratio 0.91 over only 27 bins, hotspots hit 20-51x, explored_cells just 144/180s. Three tied fixes: (1) move answered Hold 78% (236/301) vs Forward 63 — aligned_deg=35 too strict, so minor heading noise blocked Forward and the bot re-turned instead of walking. Loosened to 50. (2) goal_every=4 let EXPLORE/ADD_ARMOR swap every 4 ticks; ADD_ARMOR ate 44 ticks (15%) with zero armor gained, plausibly driving the loop. Raised to 8 for more commitment. (3) Tightened Add armor to require the pickup be close, so a distant/unreachable one stops pulling the bot off Explore. Turn_deg and aiming bands left untouched to isolate this movement/goal fix first.
- issue: move head Hold 78% (236/301) vs Forward 63 — aligned_deg=35 too strict, causing turn-then-stop loops instead of walking
- issue: revisit_ratio 0.91 across only 27 distinct bins, hotspots visited 20-51x — bot circling a tiny area, explored_cells only 144 in 180s
- issue: goal thrashing: ADD_ARMOR consumed 44 ticks (15%) with 0 armor gained, health steady at 100 — likely unreachable pickup fed the loop
- issue: turn_direction_flips=70/301 (~23%) suggests aim/heading oscillation, left untouched this pass to isolate the movement/goal fix
- issue: weapon head mean_confidence only 0.48 despite always answering Keep — question wording may be ambiguous, not addressed this pass

## v3 (code)
Steer criteria: unknown space counts as a place to go look, not as blocked (code change, not a review).
