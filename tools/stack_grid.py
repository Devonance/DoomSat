"""Compose the tech-stack overview: one grid of the windows the demo runs through.

    python tools/stack_grid.py out/stack out/stack_grid.png

Tiles (missing ones are skipped): Doom frame (payload), pilot console (jev + Claude decisions),
flight-side check (F Prime + payload), Yamcs links / parameters / commands / events, Open MCT.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

src = Path(sys.argv[1] if len(sys.argv) > 1 else "out/stack")
dst = Path(sys.argv[2] if len(sys.argv) > 2 else "out/stack_grid.png")
root = Path(__file__).resolve().parent.parent
TILE_W, TILE_H, CAP = 800, 450, 34
FONT = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 15)
CAP_FONT = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 18) if Path("C:/Windows/Fonts/segoeuib.ttf").exists() else FONT


def text_tile(lines, title, bg=(18, 18, 22), fg=(220, 220, 220)):
    img = Image.new("RGB", (TILE_W, TILE_H), bg)
    d = ImageDraw.Draw(img)
    y = 8
    for line in lines[-24:]:
        d.text((10, y), line[:118], font=FONT, fill=fg)
        y += 18
    return img


def image_tile(path):
    img = Image.open(path).convert("RGB")
    img.thumbnail((TILE_W, TILE_H), Image.LANCZOS)
    canvas = Image.new("RGB", (TILE_W, TILE_H), (10, 10, 12))
    canvas.paste(img, ((TILE_W - img.width) // 2, (TILE_H - img.height) // 2))
    return canvas


tiles = []
frame = root / "out" / "frames" / "latest.jpg"
if frame.exists():
    tiles.append(("1. Payload: Freedoom frame as downlinked (F´ FrameChunk records -> Yamcs -> reassembled)", image_tile(frame)))
log = root / "out" / "pilot_run.log"
if log.exists():
    lines = [l.rstrip() for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    tiles.append(("2. Ground pilot: jev (System One) control heads + Claude Sonnet 5 (System Two) plans", text_tile(lines, "pilot")))
dec = root / "out" / "decisions.jsonl"
if dec.exists():
    rows = [json.loads(l) for l in dec.read_text(encoding="utf-8").splitlines() if l.strip()]
    ctrl = [r for r in rows if r.get("kind") == "control"]
    plans = [r for r in rows if r.get("kind") == "plan"]
    lines = [f"jev decisions: {len(ctrl)}   Claude plans: {len(plans)}"]
    if ctrl:
        lat = sorted(r["latency_ms"] for r in ctrl)
        lines.append(f"jev latency ms: median {lat[len(lat)//2]}  p95 {lat[int(len(lat)*0.95)-1]}  (includes Yamcs round trip)")
    lines.append("")
    for r in ctrl[-8:]:
        lines.append(f"[{r['model']}] hp={r['health']} goal={r['goal']} " + " ".join(f"{k}={v}" for k, v in r["answers"].items() if k in ("dodge", "move", "strafe", "turn", "fire", "weapon", "use")))
        lines.append("      conf " + " ".join(f"{k}:{v}" for k, v in r["confidence"].items() if k in ("move", "turn", "fire", "use")))
    for r in plans[-3:]:
        lines.append(f"[{r.get('model')}] {r.get('goal')} steer={r.get('steer_hint')} ({r.get('latency_ms')} ms): {str(r.get('rationale'))[:100]}")
    tiles.append(("3. Decision log: typed answers from jev, plans from Claude (out/decisions.jsonl)", text_tile(lines, "decisions", bg=(14, 22, 18))))
check = src / "flight_check.txt"
if check.exists():
    tiles.append(("4. Flight side (WSL): F´ DoomSat binary + payload + fprime-yamcs bridge", text_tile(check.read_text(encoding="utf-8", errors="replace").splitlines(), "flight", bg=(20, 16, 24))))
for name, cap in [("yamcs_links", "5. Yamcs: CCSDS TM/TC links (frames in, commands out)"),
                  ("yamcs_params", "6. Yamcs: F´ dictionary as XTCE parameters (doom.*)"),
                  ("yamcs_health", "7. Yamcs: parameter detail (HEALTH)"),
                  ("yamcs_commands", "8. Yamcs: command history (CONTROL / SET_GOAL uplinks)"),
                  ("yamcs_fprime_events", "9. Yamcs: F´ events page (fprime-yamcs extension)"),
                  ("yamcs_events", "9. Yamcs: events"),
                  ("openmct", "10. Open MCT (openmct-yamcs) on the same Yamcs instance")]:
    p = src / f"{name}.png"
    if p.exists() and not any(c.startswith(cap[:2]) for c, _ in tiles):
        tiles.append((cap, image_tile(p)))

cols = 3
rows = (len(tiles) + cols - 1) // cols
W, H = cols * TILE_W + (cols + 1) * 12, rows * (TILE_H + CAP) + (rows + 1) * 12 + 50
grid = Image.new("RGB", (W, H), (30, 30, 34))
d = ImageDraw.Draw(grid)
d.text((14, 12), "DoomSat: Freedoom through F´ -> Yamcs -> Open MCT, piloted by jev (System One) and Claude Sonnet 5 (System Two)", font=CAP_FONT, fill=(240, 240, 240))
for i, (cap, img) in enumerate(tiles):
    r, c = divmod(i, cols)
    x, y = 12 + c * (TILE_W + 12), 50 + 12 + r * (TILE_H + CAP + 12)
    d.rectangle((x, y, x + TILE_W, y + CAP), fill=(52, 52, 58))
    d.text((x + 8, y + 7), cap, font=CAP_FONT, fill=(255, 255, 255))
    grid.paste(img, (x, y + CAP))
grid.save(dst)
print("saved", dst, grid.size, len(tiles), "tiles")
