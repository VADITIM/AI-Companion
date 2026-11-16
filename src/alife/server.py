"""HTTP for the viewer and the developer dashboard. Local only."""
import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import ROOT

WEB = ROOT / "web" / "alife"


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/api/snapshot":
                return self._json(engine.snapshot())
            if path == "/api/memories":
                return self._json({"memories": engine.store.memories(limit=60),
                                   "summaries": [dict(r) for r in engine.store.q("SELECT day, summary, lesson, source FROM daily_summaries ORDER BY day DESC LIMIT 10")]})
            name = "index.html" if path == "/" else path.lstrip("/")
            file = (WEB / name).resolve()
            if WEB.resolve() not in file.parents or not file.is_file():
                return self._json({"error": "not found"}, 404)
            body = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/api/input":
                return self._json({"error": "not found"}, 404)
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10_000)) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json({"error": "bad request"}, 400)
            self._json(engine.user_input(body))

    return Handler


def serve(engine, port):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(engine))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
