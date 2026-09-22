
## v1 (defaults)
Initial graph: the seven control heads and the goal head as designed by hand.

## v2 (claude-sonnet-5 (offline review of the 23:35 run))
The episode ended in a dead-loop: the last logged ticks are identical (ahead=blocked, turn=Hold, move=Hold, use=Use repeated), longest_hold_streak=84 and explored_cells=0 confirm the bot pinned itself against an obstacle that Use never opened, because turn only reacted to {aim} — once centered on the blocked waypoint it held forever. Fix: exposed {ahead} to turn so it swings Hard left when centered-but-blocked and use isn't working. Also exposed {ahead} to goal and sharpened Scout to trigger when ahead stays blocked, since goal was EXPLORE all 422 asks and the raw stuck flag (only 5 ticks) missed this slow-press-against-wall case. Left dodge/fire/weapon/thresholds unchanged to isolate this fix's effect.
