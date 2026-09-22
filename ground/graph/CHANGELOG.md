
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

## v6 (claude-sonnet-5)
Bot stayed in ~4 bins (revisit_ratio 0.96, 8 distinct bins/217 decisions), ahead=WALL 73% of ticks. Trace shows why: with ahead offering "open, new" ground, way picked "behind-right" toward a door only "close" (not adjacent), already used 4x. Old focus ranked any door above plain new ground; demoted so a door only outranks unexplored/new ground when at arm's length/point blank. Also fixed standing_order and way.focus, both truncated mid-sentence in prior config. Raised way_margin 0.2->0.35 since way flipped direction 5 of 8 consecutive ticks in the trace. Other heads unchanged, no issues observed.

## v7 (claude-sonnet-5)
Never finished: revisit_ratio 0.91, only 22 distinct bins, one cell visited 61x, longest_hold_streak=0 (way flipped nearly every tick). Two fixes: raised way_margin 0.35->0.55 for hysteresis against flip-flopping; reordered way focus to rank close doors above merely 'new' tight ground, since last_moments show it dropping a close door for a tight new offshoot (only 6 use calls all game). Also completed standing_order, truncated mid-word in the input. Tightened Add armor not_for to exclude repeatedly-circled unreachable pickups. Other params left unchanged.
- issue: standing_order was truncated mid-sentence in the submitted config; completed it.
- issue: way flipped direction almost every tick (longest_hold_streak=0), causing orbiting; raised way_margin.
- issue: way focus under-prioritized close doors vs new/tight ground, contributing to the 61x-revisited cell.

## v8 (claude-sonnet-5)
Two issues drove the failure: (1) standing_order was truncated mid-sentence ("...its ground tu") — completed it and added explicit dead-end guidance. (2) walk/last_moments show severe pacing-in-place: revisit_ratio 0.95, one bin hit 115/262 ticks, and `way` flapped almost every tick among ahead/ahead-left/ahead-right/behind-left while the same bars/barrier obstruction kept reappearing ahead. Raised way_margin 0.5→0.75 for hysteresis against this flapping, and added `way` instructions/not_for telling it to treat a recurring bars/locked-door sighting as a dead end and head away from it (even behind) instead of hopping to an adjacent direction. Other heads looked fine, so left untouched.

## v9 (claude-sonnet-5)
Three text fields were truncated mid-word in the given config (standing_order ended '...its ground tu', way.focus ended '...as the l', way.not_for ended '...adjacent to bars/a'), garbling jev's actual prompt. This matches the failure: in last_moments, jev picked way=behind even with an open door/new ground ahead, contradicting the (cut-off) rule to prefer doors/unexplored ground - producing revisit_ratio 0.9, only 24 distinct 128u bins over 8748 path_units, and no exit found in 180s. Rewrote those three fields as complete sentences and made 'behind = last resort only' explicit. Left thresholds/turn sizes/combat heads unchanged; only 1 tick had an enemy in view, so combat isn't implicated.
- issue: way.not_for, way.focus and standing_order were truncated mid-word, garbling jev's prompt
- issue: way head chose 'behind' despite open door/new ground ahead, contradicting its own truncated rules
- issue: revisit_ratio 0.9 with 24 distinct bins over 8748 path_units shows backtracking loops, not progress

## v10 (claude-sonnet-5)
Episode never escaped a tiny pocket: 88% revisit ratio, one bin visited 70x, path_units 7397 but only 276 explored_cells, and last_moments show the same ahead-blocked/left-long/right-tight state with 'way' bouncing between ahead-right, ahead-left and left every tick under both goals — a junction oscillation, not really a goal-choice problem. (1) way_margin 0.5→0.8 plus explicit instructions to hold a heading instead of alternating every tick when all options are already-walked. (2) goals_used split ~50/50 Add armor/Explore with zero progress while stuck at a point-blank wall — tightened Add armor's not_for to exclude pickups behind a point-blank wall. (3) goal_every 5→10 to cut reconsideration thrashing. Combat heads untouched — no enemy encounters this episode.

## v11 (claude-sonnet-5)
Episode failed: revisit_ratio 0.86, one spot visited 21x, health stuck at 45 whole run — player looped chasing an unreachable RESTORE_HEALTH target. Fixes: (1) added not_for guard to Restore Health mirroring Add Armor's, so an unreachable/blocked/repeatedly-approached pickup falls back to Explore instead of looping forever. (2) raised way_margin 0.5→0.75 to resist the tick-by-tick left/right flip-flop seen in last_moments. (3) two instruction fields (standing_order, way.focus) were truncated mid-sentence in stored config (\"...since switch\", \"...pick o\") — completed them (commit to a heading, don't alternate; abandon unreachable goals). Combat unchanged — only 18 ticks had an enemy in view, exploration/goal-fixation was the dominant failure this episode.

## v12 (claude-sonnet-5)
Episode never left a tiny pocket: 23 distinct bins over 241 decisions, revisit_ratio 0.9, top cells hit 16-34x near a door. last_moments shows 'way' oscillating tick-to-tick between near-opposite directions once nearby ground was all walked, i.e. stuck flip-flopping in a dead end. Root cause: standing_order and way.focus strings were both truncated mid-sentence, so the anti-oscillation guidance never reached the model intact, and way_margin (0.5) was too weak to keep the prior direction winning. Fix: completed both strings with explicit 'hold direction 5-8 ticks' guidance, added a not_for clause naming the swinging pattern, raised way_margin to 1.0 for stronger hysteresis. Other heads untouched — no combat/damage this episode.

## v13 (claude-sonnet-5)
Episode looped: 0.88 revisit ratio over 25 bins, top tiles hit 15-33x, last_moments show ahead/left/right all walked with agent swinging between adjacent options. Root causes: (1) standing_order and way.focus were truncated mid-sentence in stored config, so intended anti-loop guidance never reached the model - rewrote both fully. (2) way's not_for over-restricted 'behind' as near-permanent last resort; once ahead/left/right all became walked, agent had no escape and paced between remaining options. Added exception: once all three are walked for several ticks, behind becomes deliberate retrace-to-branch choice. Raised way_margin 0.5->0.65 for more commitment. Other heads unchanged - no combat/damage/stuck evidence there.

## v14 (claude-sonnet-5)
Main failure wasn't combat (fire always no, enemy visible only 2 ticks) but exploration deadlock: 121/243 decisions sat in one 128u bin, revisit_ratio 0.93, only 17 distinct bins in 182s. last_moments show 'way' flip-flopping tick to tick and abandoning 'ahead' right after use=yes on a door. Raised way_margin 0.5→1.3 for stronger hysteresis, and added a standing_order clause to keep pushing ahead through a door for a few ticks after use=yes instead of switching away mid-swing. Also completed several fields that were silently truncated mid-sentence in the current config, which had cut off the exception clauses meant to stop direction alternation.
- issue: standing_order and way criteria text were truncated mid-sentence, cutting off exception clauses meant to stop flip-flopping
- issue: Severe deadlock: 121/243 ticks in one bin, revisit_ratio 0.93, way head oscillated near a door instead of committing
- issue: Pattern of abandoning a door just after use=yes, switching to behind-left the next tick instead of persisting

## v15 (claude-sonnet-5)
Episode showed severe navigational entrapment: revisit_ratio 0.94 across only 12 distinct bins in 187s, last_moments oscillating around a barred door. Root cause: standing_order, way.focus, and way.not_for were truncated mid-sentence in the prior config ("...just retrac", "...pick o", unfinished Exception clause) - an incomplete rule is worse than none. Completed all three: commit to one direction for several ticks; when all directions are walked, pick whichever wasn't just tried instead of bouncing. Raised way_margin 0.5->0.65 for more hysteresis (7 flips/18 asks). Tightened Restore Health: health stayed at 13 all episode while the goal fired 10/16 times, since "critical" alone triggered it with no pickup actually seen/reachable; now requires a real reachable pickup, else Explore.
