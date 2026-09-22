"""Compose the per-second screenshots from tools/stack_record.mjs into one 1920x1080 grid video (mp4, 1 fps source
held for 1 s each) and a 1080p mp4 of the dashboard recording (webm from Playwright) if present.

    python tools/stack_video.py out/stackrec out/doomsat_stack_1080p.mp4
    python tools/stack_video.py --convert out/recording/<file>.webm out/doomsat_dashboard_1080p.mp4
    python tools/stack_video.py --frames out/dashrec out/doomsat_dashboard_1080p.mp4   (from tools/dashboard_record.mjs)
"""
import glob
import os
import subprocess
import sys

import imageio_ffmpeg
from PIL import Image, ImageDraw

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
TILES = [("dashboard", "Mission dashboard (from Yamcs)"), ("yamcs-tlm", "Yamcs web: telemetry"),
         ("yamcs-cmd", "Yamcs web: command history"), ("openmct", "Open MCT")]


def compose(src, out_mp4):
    frames = sorted(glob.glob(os.path.join(src, "dashboard-*.png")))
    tmp = os.path.join(src, "grid")
    os.makedirs(tmp, exist_ok=True)
    for i, f in enumerate(frames):
        idx = os.path.basename(f).split("-")[1].split(".")[0]
        canvas = Image.new("RGB", (1920, 1080), (12, 14, 18))
        d = ImageDraw.Draw(canvas)
        for k, (name, title) in enumerate(TILES):
            p = os.path.join(src, f"{name}-{idx}.png")
            x, y = (k % 2) * 960, (k // 2) * 540
            if os.path.exists(p):
                im = Image.open(p).convert("RGB").resize((952, 522), Image.LANCZOS)
                canvas.paste(im, (x + 4, y + 14))
            d.rectangle((x + 4, y, x + 956, y + 13), fill=(30, 34, 44))
            d.text((x + 10, y + 1), title, fill=(200, 210, 225))
        canvas.save(os.path.join(tmp, f"grid-{i:04d}.png"))
    cmd = [FFMPEG, "-y", "-framerate", "1", "-i", os.path.join(tmp, "grid-%04d.png"), "-vf", "fps=10,format=yuv420p",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", out_mp4]
    subprocess.run(cmd, check=True, capture_output=True)
    print("wrote", out_mp4, "from", len(frames), "seconds")


def convert(webm, out_mp4):
    cmd = [FFMPEG, "-y", "-i", webm, "-vf", "scale=1920:1080,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "20", out_mp4]
    subprocess.run(cmd, check=True, capture_output=True)
    print("wrote", out_mp4)


def frames(src, out_mp4, fps=4):
    cmd = [FFMPEG, "-y", "-framerate", str(fps), "-i", os.path.join(src, "f-%05d.png"), "-vf", "scale=1920:1080,format=yuv420p",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", out_mp4]
    subprocess.run(cmd, check=True, capture_output=True)
    print("wrote", out_mp4, "from", len(glob.glob(os.path.join(src, "f-*.png"))), "frames")


if __name__ == "__main__":
    if sys.argv[1] == "--frames":
        frames(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "--convert":
        convert(sys.argv[2], sys.argv[3])
    else:
        compose(sys.argv[1], sys.argv[2])
