# DoomSat: playing Doom through a real mission stack

Freedoom runs as a **payload** behind an **F´ (F Prime) flight computer**; telemetry and image
products go down through **Yamcs** (via `fprime-yamcs`, whose XTCE mission database is generated
from the F´ dictionary) and are displayed in the **Yamcs web UI** and **Open MCT**; a ground pilot
plays the game by uplinking commands: **jev** (TypeSafe's System One model) answers the fast control
questions, **Claude Sonnet 5** (System Two) sets goals from the telemetry and the downlinked frame,
and code owns the loop.

```
 WSL (Ubuntu 24.04)                                            Windows
 ┌─────────────────────┐ TCP 4242 ┌──────────────────────┐        ┌─────────────────────────────┐
 │ payload/            │<-------->│ F´ DoomSat (v4.3.0)  │  TCP   │ Open MCT (:9000)            │
 │ doom_payload.py     │ status,  │  Components/Doom     │ 50000  │   openmct-yamcs plugin      │
 │ ViZDoom + Freedoom  │ frames   │  CdhCore/ComCcsds/.. │<------>│ Yamcs web (:8090)           │
 │ range camera, labels│ controls │  CCSDS TM/TC frames  │        │ ground/pilot.py             │
 │ self-built map      │          └──────────────────────┘        │   jev  <- TypeSafe API      │
 └─────────────────────┘             ^  fprime-yamcs bridge -> Yamcs 5.12 (WSL, bundled JRE)      │
                                     └──── commands (CONTROL, SET_GOAL, EXPLORE_HINT, ...) ─────┘
```

## What is proven (21 Sep 2026)

- F´ dictionary -> XTCE -> Yamcs: 148 parameters / 54 commands load; every Doom channel decodes.
- Image products: each JPEG frame (320x240, ~8 KB) is split onboard into 960-byte `FrameChunk`
  telemetry records that bypass `Svc.TlmChan` sampling (they go straight into the com queue,
  APID 1) and ride the CCSDS TM frames; the ground reassembles ~10 fps with <1% loss and stores
  them in the Yamcs bucket `doomframes` (`/DoomGround/DoomFrame` carries the URL for Open MCT).
- Uplink: CONTROL commands every ~300 ms; the F´ command dispatcher, the Doom component and the
  payload all report them (events `OpCodeDispatched/Completed`, `GoalSet`, `ExploreHint`).
- jev: 7 control heads per request, ~470 ms median including the Yamcs round trip.
- Claude Sonnet 5 via the local `claude` CLI: a level strategy at each episode start, then a re-plan only
  when code sees a reason (no new map cells for 20 s, a health drop, death, level done), never more than
  once per 30 s; 6-11 s per plan, ~$0.06 each. When it reads the frame, the CLI runs a ~1k-token Haiku
  helper call for its tool plumbing; the plan itself is Sonnet. `--system-two anthropic` (API key) is the
  Sonnet-only path, `--no-vision` avoids the helper on the CLI path.

Integration findings worth keeping:
1. F´ `string` telemetry is serialized length-prefixed, but `fprime-xtce` emits a fixed-size
   string type, so Yamcs rejects every packet carrying one (`TARGET_NAME` became an enum).
2. Opaque byte arrays need the `!binary` annotation (`fprime-xtce` PR #8, installed from the
   branch); the whole-struct form rejects array members, the array form works.
3. `FW_COM_BUFFER_MAX_SIZE` must be raised (512 -> 1000) through a `CONFIGURATION_OVERRIDES`
   config module (`flight/config`), not `settings.ini`'s `config_directory`.
4. `Svc.LinuxTimer` must tick faster than 1 Hz or the `ComAggregator` holds the last chunk of a
   frame until its timeout; the deployment runs a 20 Hz base clock.

## Layout

| Path | What |
|---|---|
| `flight/Components/Doom/` | F´ component: commands, telemetry, events, FrameChunk downlink (FPP + C++) |
| `flight/DoomSat/Top/`, `flight/config/` | topology/instances/rate groups, com-buffer override (copied into the WSL project) |
| `payload/doom_payload.py` | the game as an instrument: depth-buffer range camera, labels, self-built map, frontier exploration |
| `ground/pilot.py` | the loop: Yamcs subscriptions, frame reassembly, jev control step, Claude plan step, commands |
| `ground/decision_graph.py` | telemetry -> words, the seven control questions, answers -> CONTROL arguments |
| `ground/providers.py` | System One: TypeSafe (jev) or any OpenAI-compatible endpoint; System Two: Claude CLI, Anthropic API or OpenAI-compatible |
| `ground/yamcs/` | Yamcs config dir for `fprime-yamcs` plus the ground-side XTCE (`DoomGround`) |
| `ground/openmct/` | Open MCT example config pointed at the `fprime-project` instance |
| `scripts/` | `flight.sh start|stop|check|build|rebuild`, `start_openmct.sh`, `start_pilot.sh`, WSL helpers |
| `tools/` | stack screenshots + grid, one-shot patch scripts |

## Running it

Prerequisites already on this machine: WSL distro `ros2` with `/root/doom/doom-mission` (F´ v4.3.0
bootstrap + `fprime-yamcs`), `/root/doom/payload-venv` (ViZDoom 1.3.0), `ground/.venv` (yamcs-client),
`external/openmct-yamcs` with an Open MCT build, the `claude` CLI, and today's TypeSafe key in
`ground/.env` (`TYPESAFE_API_KEY=...`).

```
scripts/flight.sh start          # WSL: payload + fprime-yamcs (Yamcs :8090) + DoomSat binary
scripts/flight.sh check          # telemetry, frame chunks, events, links
scripts/start_openmct.sh         # Open MCT on :9000 (proxies to Yamcs)
scripts/start_pilot.sh --duration 300      # jev controls + Claude plans; logs in out/
scripts/start_pilot.sh --system-two none   # jev only (its goal head plans too)
scripts/start_pilot.sh --system-one openai --openai-base-url http://localhost:1234/v1 --system-one-model <local>
```

After editing anything under `flight/`: `scripts/flight.sh build` (incremental) or `rebuild`.

## Who decides what

| Layer | Runs | Decides |
|---|---|---|
| Flight code (F´ + payload) | 35 Hz / 20 Hz | safety (uplink loss -> hold), heading setpoint loop, range-camera map, frontier route, target choice |
| System One: jev | every ~0.5 s | the seven control heads (dodge, move, strafe, turn, fire, weapon, use) from words |
| System Two: Claude Sonnet 5 | once per episode + triggers | the goal (explore / fight / supplies / scout / hold) and an exploration hint from the frame |

## Honest play

The payload never reads the level file. It sees the depth buffer (calibrated as a range camera),
the labels buffer (visible enemies and pickups, remembered once seen), and its own HUD variables.
It builds an occupancy map from range sweeps and explores toward frontiers; the exit is found, not
known. Claude can bias exploration with a steer hint after looking at a frame. jev decides the
moment-to-moment controls from words only; every number is bucketed before it sees it.

## Status

Whole path works end to end. The open problem is gameplay quality: the frontier explorer still
wedges on pillars and dead ends (see `out/payload_map.png`, the map the payload built), so runs are
mostly jev turning and strafing to get free. Open MCT displays the Yamcs tree once its build matches
`openmct-yamcs` (build from master).
