# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Serve ground/openmct for the replay page, with no Yamcs and no build step.

    python tools/openmct_serve.py [--port 8071]      then open http://localhost:8071/replay.html

Open MCT itself comes from the first of: ground/openmct/node_modules/openmct/dist (npm install openmct@^4.3
in ground/openmct) or external/openmct-yamcs/node_modules/openmct/dist (the build start_openmct.sh uses).
/aar/ serves docs/results, for the after-action web page. Threaded, because the imagery strip asks for dozens
of frames at once.
"""
import argparse
import functools
import http.server
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "ground" / "openmct"
DIST = [WEB / "node_modules" / "openmct" / "dist", ROOT / "external" / "openmct-yamcs" / "node_modules" / "openmct" / "dist"]
AAR = ROOT / "docs" / "results"


class Handler(http.server.SimpleHTTPRequestHandler):
    dist = None

    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/node_modules/openmct/dist/") and self.dist:
            return str(self.dist / clean[len("/node_modules/openmct/dist/"):])
        if clean.startswith("/aar/"):
            return str(AAR / clean[len("/aar/"):])
        return super().translate_path(path)

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8071)
    a = ap.parse_args()
    Handler.dist = next((d for d in DIST if (d / "openmct.js").exists()), None)
    if Handler.dist is None:
        raise SystemExit("no Open MCT build found: cd ground/openmct && npm install openmct@^4.3")
    if not (WEB / "replay").is_dir():
        print("no replay pack yet: python tools/build_openmct_replay.py")
    print(f"serving {WEB.relative_to(ROOT)} with Open MCT from {Handler.dist.relative_to(ROOT)} "
          f"on http://localhost:{a.port}/replay.html")
    http.server.ThreadingHTTPServer(("", a.port), functools.partial(Handler, directory=str(WEB))).serve_forever()


if __name__ == "__main__":
    main()
