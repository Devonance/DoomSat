"""Serve the mission dashboard (ground/dashboard) on http://localhost:8070 and proxy /api/* to Yamcs,
so the page can read telemetry, events, commands and image products from Yamcs without CORS trouble.
Also serves the repo's out/ directory (the payload's diagnostic map image).

    python tools/serve_dashboard.py [--port 8070] [--yamcs http://localhost:8090]
"""
import argparse
import http.server
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Handler(http.server.SimpleHTTPRequestHandler):
    yamcs = "http://localhost:8090"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, *a):
        pass

    def _proxy(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(self.yamcs + self.path, data=body, method=method,
                                     headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                data = r.read()
                self.send_response(r.status)
                self.send_header("Content-Type", r.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            # Yamcs answered, with a refusal: pass its status and its reason through (a refused command
            # says why, and the page shows it) instead of hiding both behind a 502.
            data = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:  # noqa: BLE001
            self.send_error(502, str(e))

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._proxy("GET")
        if self.path in ("/", "/index.html"):
            self.path = "/ground/dashboard/index.html"
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._proxy("POST")
        self.send_error(404)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8070)
    p.add_argument("--yamcs", default="http://localhost:8090")
    a = p.parse_args()
    Handler.yamcs = a.yamcs
    print(f"dashboard on http://localhost:{a.port}/  (Yamcs at {a.yamcs})", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
