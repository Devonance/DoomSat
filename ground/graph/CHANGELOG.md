
## v1 (defaults)
Initial graph: the seven control heads and the goal head as designed by hand.

## v2 (claude-sonnet-5 (offline review of the 23:35 run))
The episode ended in a dead-loop: the last logged ticks are identical (ahead=blocked, turn=Hold, move=Hold, use=Use repeated), longest_hold_streak=84 and explored_cells=0 confirm the bot pinned itself against an obstacle that Use never opened, because turn only reacted to {aim} — once centered on the blocked waypoint it held forever. Fix: exposed {ahead} to turn so it swings Hard left when centered-but-blocked and use isn't working. Also exposed {ahead} to goal and sharpened Scout to trigger when ahead stays blocked, since goal was EXPLORE all 422 asks and the raw stuck flag (only 5 ticks) missed this slow-press-against-wall case. Left dodge/fire/weapon/thresholds unchanged to isolate this fix's effect.

## v3 (claude-sonnet-5)
Bot stalled, not died: 276 explored cells despite 37303 path_units and 174 turn flips (28% of ticks). last_moments shows why: at a blocked wall, move=Hold while turn alternates Hard right/Hard left in lockstep with aim flipping centered/far-right — swinging away just re-centers the same wall from the other side, an infinite loop; use fired 61x with no resolution (likely plain walls). Fixes: (1) moved the blocked+centered scan rule out of the symmetric Hard left/Hard right pair into Turn around alone, so a real 150° reversal breaks the loop instead of re-facing the same obstacle; (2) raised blocked_units 45->65 so "blocked" fires only near real obstacles, cutting spurious loops. Left fire/weapon/dodge unchanged — zero enemy-in-view ticks gave no signal.
