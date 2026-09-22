# DoomSat: playing Doom through a real mission stack

Doom runs as a **payload** behind an **F´ (F Prime) flight computer**. Telemetry and image products go
down through **CCSDS frames** into **Yamcs** (via `fprime-yamcs`; the XTCE mission database is generated from
the F´ dictionary) and are displayed in the **Yamcs web UI**, **Open MCT** and a small mission dashboard. A
ground pilot plays the game by uplinking commands: **jev** (TypeSafe's System One model) classifies the situation
every half second and picks the direction, whether to walk, press Use, fire and which weapon; **Claude Sonnet 5**
(System Two) nudges exploration once a minute and, after each attempt, rewrites the questions jev plays with.
Code owns the loop and never reads the level file.

![Architecture](docs/diagrams/architecture.png)

## Data flow

Every message, its type and its rate, from the game to the models and back:

![Data flow](docs/diagrams/dataflow.png)

The dashboard (`tools/serve_dashboard.py`, everything on it comes from Yamcs) during a live jev run:

![Dashboard](docs/images/dashboard.png)

## What the player side is allowed to see

The rule for this demo: jev and code go in blind, like a person who knows how to play Doom but has never seen
the level. Nothing from the WAD reaches the payload or the models.

| Sense | What it stands in for | Source |
|---|---|---|
| Depth buffer (range camera) | where the walls are | ViZDoom depth buffer; calibrated: 7.16 map units per step, perpendicular distance |
| Object labels | recognising monsters, pickups, keys, barrels | ViZDoom labels buffer (only things in view) |
| In-game automap, *seen lines only* | the map a player sees on Tab | ZDoom automap in `NORMAL` mode: lines the player has looked at, in the engine's default categories (wall, floor step, ceiling change = door, locked door in its key colour, exit line); only the colours are changed so code can read them |
| HUD variables | health, armor, ammo, position, heading | ViZDoom game variables |

Not used: whole-map or "show objects" automap modes, the "show trigger lines" option, sector/line geometry
from the game state, monster counts, item lists, warp cheats. `tools/wad_stats.py` reads WADs but only as a
developer check for choosing levels and verifying results; the payload never imports it.

There is no route planner onboard. The payload (`payload/doom_payload.py`) stamps the automap into a world raster,
sweeps the floor it has seen with the range camera, remembers where it has walked, and reports eight directions
around the player (every 45 degrees): how far the way is open on the map, and whether the ground that way is
unexplored, new, or walked before. It also reports what is at arm's length ahead (a wall, a door, the exit switch,
a locked door, something the map does not show), where an exit line, a key or a pickup was seen, and whether the
player is stuck. Obstacles the automap does not draw (window bars, fake doors, barrels) are learned by pushing
against them once. jev picks the direction from those words every ~0.5 s; every number is bucketed before jev
sees it. The map of a level is kept across attempts, as a player remembers a layout; the game itself restarts.

## What is proven

- F´ dictionary -> XTCE -> Yamcs: 148 parameters / 54 commands load; every Doom channel decodes.
- Image products: each JPEG frame (320x240, ~8 KB) is split onboard into 960-byte `FrameChunk` telemetry
  records that bypass `Svc.TlmChan` sampling (straight into the com queue, APID 1) and ride the CCSDS TM frames;
  the ground reassembles ~10 fps with <1% loss and publishes them to the Yamcs bucket `doomframes`
  (`/DoomGround/DoomFrame` carries the URL for Open MCT and the dashboard).
- Uplink: CONTROL commands every ~0.5 s; the F´ command dispatcher, the Doom component and the payload all
  report them (events `OpCodeDispatched/Completed`, `GoalSet`, `LevelStarted`, `KeyPickedUp`).
- jev: 7 control heads per request, ~450 ms median including the Yamcs round trip; every decision row in
  `out/decisions.jsonl` carries the TypeSafe request id.
- Claude Sonnet 5 via the `claude` CLI as the after-action reviewer: one tool-free schema call per episode,
  returning the revised graph. The CLI runs with `DISABLE_NON_ESSENTIAL_MODEL_CALLS=1`, so no helper-model calls;
  `--system-two anthropic` uses the API directly.

Integration findings worth keeping:
1. F´ `string` telemetry is serialized length-prefixed, but `fprime-xtce` emits a fixed-size string type, so
   Yamcs rejects every packet carrying one (the string channel became an enum).
2. Opaque byte arrays need the `!binary` annotation (`fprime-xtce` PR #8, installed from the branch); the
   whole-struct form rejects array members, the array form works.
3. `FW_COM_BUFFER_MAX_SIZE` must be raised (512 -> 1000) through a `CONFIGURATION_OVERRIDES` config module
   (`flight/config`), not `settings.ini`'s `config_directory`.
4. `Svc.LinuxTimer` must tick faster than 1 Hz or the `ComAggregator` holds the last chunk of a frame until its
   timeout; the deployment runs a 20 Hz base clock.
5. Yamcs delivers F´ booleans as the strings "True"/"False"; a Yamcs bucket holds at most 1000 objects (image
   products are written into a ring of 20 names); the parameter WebSocket drops after a few minutes.
6. The ViZDoom depth buffer is perpendicular (z) distance at 7.16 units per step, its value 0 is the sky, and the
   crosshair is drawn into it; the automap draws the player arrow over the lines beneath it.

## Layout

| Path | What |
|---|---|
| `flight/Components/Doom/` | F´ component: commands, 44 telemetry channels, events, FrameChunk downlink (FPP + C++) |
| `flight/DoomSat/Top/`, `flight/config/` | topology/instances/rate groups, com-buffer override (copied into the WSL project) |
| `payload/doom_payload.py` | the game as an instrument: automap + range camera + labels, the onboard navigator, level progression |
| `payload/selfplay.py`, `payload/nav_probe.py` | code-only drivers of the navigator (no models) for fast iteration |
| `ground/pilot.py` | the loop: Yamcs subscriptions, frame reassembly, jev control step, after-action reviews, commands |
| `ground/decision_graph.py`, `ground/graph_config.py` | telemetry -> words, the seven control heads + goal head, the graph as data (versioned in `ground/graph/`) |
| `ground/after_action.py` | the episode report and the System Two review call |
| `ground/providers.py` | System One: TypeSafe (jev) or any OpenAI-compatible endpoint; System Two: Claude CLI, Anthropic API or OpenAI-compatible |
| `ground/yamcs/`, `ground/openmct/`, `ground/dashboard/` | Yamcs config + ground XTCE, Open MCT config, the mission dashboard page |
| `docs/` | diagrams (Graphviz sources + renders), report (`doomsat-report.md/.tex/.pdf`), images |
| `scripts/`, `tools/` | start/stop/build helpers (WSL), run report, screenshots/recording, developer probes |

## Running it

Prerequisites on this machine: WSL distro `ros2` with `/root/doom/doom-mission` (F´ v4.3.0 bootstrap +
`fprime-yamcs`), `/root/doom/payload-venv` (ViZDoom 1.3.0), the shareware `doom1.wad` in `/root/doom/wads`
(`tools/get_doom1.sh`; Freedoom is bundled with ViZDoom as a fallback: `WAD=freedoom2.wad MAP=MAP01`),
`ground/.venv` (yamcs-client), `external/openmct-yamcs` with an Open MCT build, the `claude` CLI, and the day's
TypeSafe key in `ground/.env` (`TYPESAFE_API_KEY=...`).

```
scripts/flight.sh start                    # WSL: payload (E1M1) + fprime-yamcs (Yamcs :8090) + DoomSat binary
scripts/flight.sh payload                  # restart only the game process (after editing the payload)
scripts/flight.sh check                    # telemetry, frame chunks, events, links
python tools/serve_dashboard.py            # mission dashboard on :8070 (proxies the Yamcs API)
scripts/start_openmct.sh                   # Open MCT on :9000
scripts/start_pilot.sh --duration 1800     # jev plays; Sonnet bumps every 60 s, 180 s budget per level attempt; logs in out/
scripts/start_pilot.sh --bump-every 0 --level-budget 0   # no bumps, no budget: jev + graph only
scripts/start_pilot.sh --no-after-action   # jev + code only, graph frozen at ground/graph/graph_current.json
python tools/run_report.py                 # what each layer did in the last run (levels, decisions, reviews)
node tools/dashboard_shot.mjs record out/recording 600   # 1080p recording of the dashboard (webm)
scripts/start_pilot.sh --system-one openai --openai-base-url http://localhost:1234/v1 --system-one-model <local>
```

After editing anything under `flight/`: `scripts/flight.sh build` (incremental) or `rebuild`, then
`scripts/flight.sh start`.

## Who decides what

| Layer | Runs | Decides |
|---|---|---|
| Flight code (F´ + payload) | 35 Hz / 20 Hz | safety (uplink loss -> hold), heading setpoint loop, the map, the route, the target (exit line > key > goal item > frontier > walls to try), door/switch attempts |
| System One: jev | every ~0.5 s, live | one narrow typed question per head over a structured state: `way` (which of the open directions), `advance` (Noul), `use` (Noul), `fire` (Noul), `dodge`, `turn` (aim at an enemy), `weapon`, and every 8th tick the `goal`; options carry what / not_for / examples criteria and code uses the option probabilities for hysteresis |
| System Two: Claude Sonnet 5 | every minute, and after an episode | every minute: reads the map product and the recent walk and pushes exploration in a direction (`EXPLORE_HINT`, optionally `SET_GOAL`); after an episode (death, level finished, or the 3-minute level budget spent -> `RESET_GAME`): reads the condensed after-action report and revises the decision graph jev plays with next |

Nothing slower than jev sits in the live loop. The graph is data (`ground/graph_config.py`); every revision is
validated by code (fixed option names, known placeholders, numeric ranges) and stored as
`ground/graph/graph_v<N>.json` with Sonnet's rationale in `ground/graph/CHANGELOG.md`.

## Status

See `docs/doomsat-report.md` for the run log and numbers of the latest campaign (shareware Doom E1M1 onward).
`python tools/run_report.py` prints the current run.

## Sources

Frameworks and services used, with the versions in this repository:

- NASA F´ flight software framework, v4.3.0: https://github.com/nasa/fprime
- fprime-yamcs (Yamcs bridge and launcher for F´) 0.2.1 and fprime-xtce (dictionary -> XTCE, PR #8 branch for `!binary`): https://github.com/fprime-community/fprime-yamcs, https://github.com/FarkasJoseph/fprime-xtce/tree/feature/binary-annotation-combined
- Yamcs mission control 5.12.8: https://github.com/yamcs/yamcs
- NASA Open MCT (built from master): https://github.com/nasa/openmct
- openmct-yamcs plugin: https://github.com/akhenry/openmct-yamcs
- TypeSafe jev (System One) and the Python SDK: https://docs.typesafe.ai/introduction, https://docs.typesafe.ai/sdk/python/api
- Claude Sonnet 5 through Claude Code (System Two): https://code.claude.com/docs
- ViZDoom 1.3.0 (Doom engine bindings; ZDoom automap/depth/labels buffers): https://vizdoom.farama.org, https://github.com/Farama-Foundation/ViZDoom
- Shareware Doom IWAD (`doom1.wad`, from the Debian `doom-wad-shareware` package) and Freedoom: https://freedoom.github.io
- yamcs-client (Python) 2.1: https://github.com/yamcs/python-yamcs-client
- System One demo that this decision graph descends from (its Doom demo reads the WAD; ours does not): https://github.com/sgoedecke/system-one
- Prior LLM-plays-Doom work for comparison: https://adriandewynter.substack.com/p/will-gpt-4-and-5-run-doom
- Graphviz (diagrams), Playwright + Chrome (screenshots, recording), tectonic (PDF report)
