
## v1 (defaults)
Initial graph: one narrow question per head, structured criteria, Nouls for yes-no heads.

## v2 (code)
Way head: unexplored (never seen) ground is the strongest pull (code change).

## v3 (claude-sonnet-5)
Episode never reached the exit: one 128u bin was revisited 90x, revisit_ratio 0.89, ahead was WALL on 120/229 ticks. last_moments show "way" flip-flopping left/right each tick at a blocked corner (left as unexplored, then right as new next tick), spinning in place instead of clearing the corner. Fixes: raised way_margin 0.15→0.35 for stronger hysteresis on near-tied left/right calls; added text telling "way" to keep the side just chosen instead of swinging back; increased Left/Right turn_deg (25→35°) and Hard variants (60→70°) so a turn away from a wall actually clears it. Other heads untouched — no enemies appeared, so no evidence they caused the failure.

## v4 (claude-sonnet-5)
Player looped near the start: 27 distinct bins in 217 decisions, revisit 0.88, ahead=WALL 96/217, last_moments show way flipping sides while ahead stayed 'blocked, wall at point blank'. The 'stick to last side' rule was re-picking a wall-hugging dead-end. Narrowed it to hold only while that side yields new ground, added not_for for a now-blocked/walked side, and cut way_margin 0.35->0.2 so hysteresis doesn't override this. Also ADD_ARMOR held 63/217 ticks under goal_every=8 while exploration stalled, suggesting fixation on unreachable armor; tightened Add armor to require direct reachability and shortened goal_every to 5. Lastly weapon confidence (0.34) was far below other heads; added player.equipped_weapon to inspect and clarified Keep's wording.

## v5 (claude-sonnet-5)
Two fixes, each tied to a data point. (1) standing_order was truncated mid-word ("...huggi"); completed it, added: if every direction is walked-before, turn around fully. Addresses severe looping: revisit_ratio 0.83, only 29 distinct bins over 175 decisions, top cells revisited 11-21x, exit never seen. (2) ahead_kind_ticks logged BARRIER 3 times, but advance/use/way never treated barriers as blocking, unlike wall/bars/barrel/monster. Plausibly linked to damage_taken_with_no_enemy_in_view=80 (almost all damage, vs 8 ticks with an enemy visible). Added barrier to advance/use false criteria and way's avoid list. Nudged way to prefer "never seen" ground over "new" to fight the loop. Other fields unchanged (turn_direction_flips=0, stuck_ticks=1 don't implicate them).
