#!/usr/bin/env python3
"""Honk, the keeper on the Moon: runs his life (the sim loop) and serves the viewer.

Standard library only. Run it from anywhere:

    python3 src/honk/server.py                 his real life: the model from config/honk.toml, the live gateway
    python3 src/honk/server.py --test          test mode: scripted mind, fixture Foundry, recorded pages, its own database
    python3 src/honk/server.py --speed 20      simulated minutes per real minute (default from config)

then open http://127.0.0.1:8765/

Endpoints (JSON):
  GET  /api/state?since=<event id>&params=1   everything the viewer shows (params=1 adds the tuning panel's data)
  GET  /api/builds                            what stands on the Moon, with the shapes to draw it
  POST /api/postcard   {name, text, answers?} a postcard from a visitor (answers: the id of one of his questions to visitors)
  POST /api/param      {key, value}           change one number live; logged in param_changes
  POST /api/preset     {name}                 load a preset ("" = the plain config)
  POST /api/control    {paused?, speed?}      the kill switch (paused: true) and the clock speed
  POST /api/reset      {"confirm": "erase everything"}   he forgets everything and wakes up new

Settings (environment): HONK_PORT (8765), HONK_DATA (data/), OPENROUTER_API_KEY (the Foundry's cloud model; optional).
"""
import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __package__ in (None, ""):      # run as a script: import the package from src/, not from this folder
    sys.path[0] = str(Path(__file__).resolve().parents[1])
from honk import config, snapshot  # noqa: E402
from honk.db import DB  # noqa: E402
from honk.loop import Sim  # noqa: E402

ROOT = config.ROOT
STATIC = {"World": ROOT / "World"}
MAX_REQUEST = 20_000


class App:
    """The running Honk: one database, one sim loop in its own thread."""

    def __init__(self, data, test=False, speed=None):
        self.data, self.test, self.speed = Path(data), test, speed
        self.sim, self.thread, self.status, self.status_at = None, None, {}, 0.0
        self.start()

    def path(self):
        return self.data / ("honk-test.db" if self.test else "honk.db")

    def start(self):
        self.data.mkdir(parents=True, exist_ok=True)
        db = DB(self.path())
        params = config.load(preset=db.get("preset"), overrides=db.get("overrides", {}))
        if self.test:
            params["mind"]["provider"], params["foundry"]["provider"], params["gateway"]["mode"] = "stub", "stub", "cassette"
        if self.speed:
            params["sim"]["speed"] = float(self.speed)
        self.sim = Sim(db, params, threaded=True)
        self.thread = threading.Thread(target=self.sim.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.sim.stop.set()
        self.thread.join(timeout=200)
        self.sim.db.close()

    def reset(self, body):
        if not isinstance(body, dict) or body.get("confirm") != "erase everything":
            raise ValueError('send {"confirm": "erase everything"}')
        self.stop()
        for suffix in ("", "-wal", "-shm"):
            f = Path(str(self.path()) + suffix)
            if f.exists():
                f.unlink()
        self.start()
        return {"ok": True}

    def model_status(self):
        if time.time() - self.status_at > 15:
            self.status_at = time.time()
            try:
                self.status = self.sim.client.status()
            except Exception as e:
                self.status = {"up": False, "ready": False, "note": str(e)}
        return self.status

    def postcard(self, body, address):
        sim = self.sim
        answers = body.get("answers")
        row = sim.postcards.accept(str(body.get("name") or ""), body.get("text"), address, sim.clock, int(answers) if isinstance(answers, (int, float)) else None)
        return {"ok": True, "id": row["id"], "status": row["status"]}

    def control(self, body):
        sim = self.sim
        if isinstance(body.get("paused"), bool):
            with sim.lock:
                sim.flags["paused"] = body["paused"]
                sim.db.put("flags", sim.flags)
                sim.db.insert("param_changes", ts=sim.clock, key="paused", old="", new=str(body["paused"]), who="panel")
        if isinstance(body.get("speed"), (int, float)) and 0.1 <= body["speed"] <= 600:
            sim.set_param("sim.speed", body["speed"])
        return {"ok": True, "paused": bool(sim.flags.get("paused")), "speed": sim.p["sim"]["speed"]}


class Handler(BaseHTTPRequestHandler):
    server_version = "Honk/0.2"
    app = None

    def log_message(self, fmt, *args):
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        try:
            if url.path == "/":
                self.send_response(302)
                self.send_header("Location", "/World/main-hub.html")
                self.end_headers()
            elif url.path == "/api/state":
                since = int(q.get("since", ["0"])[0] or 0)
                out = snapshot.state(self.app.sim, since, with_params="params" in q)
                out["mind"]["status"] = self.app.model_status()
                out["mind"]["test"] = self.app.test
                self.send_json(out)
            elif url.path == "/api/builds":
                self.send_json({"builds": snapshot.builds(self.app.sim)})
            else:
                self.serve_static(url.path)
        except (ValueError, KeyError) as e:
            self.send_json({"error": str(e)}, 400)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).hostname not in ("127.0.0.1", "localhost"):
            return self.send_json({"error": "forbidden origin"}, 403)
        if "application/json" not in self.headers.get("Content-Type", ""):
            return self.send_json({"error": "send JSON"}, 415)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_REQUEST:
            return self.send_json({"error": "request too big"}, 413)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("send a JSON object")
            app = self.app
            routes = {
                "/api/postcard": lambda: app.postcard(body, self.client_address[0]),
                "/api/param": lambda: {"ok": True, "key": body.get("key"), "value": app.sim.set_param(str(body.get("key")), body.get("value"))},
                "/api/preset": lambda: (app.sim.set_preset(str(body.get("name") or "")), {"ok": True})[1],
                "/api/control": lambda: app.control(body),
                "/api/reset": lambda: app.reset(body),
            }
            if path not in routes:
                return self.send_json({"error": "not found"}, 404)
            self.send_json(routes[path]())
        except (ValueError, KeyError, TypeError, FileNotFoundError) as e:
            self.send_json({"error": str(e)}, 400)

    def serve_static(self, path):
        head, _, rest = urllib.parse.unquote(path).lstrip("/").partition("/")
        base = STATIC.get(head)
        if not base or not rest:
            return self.send_error(404)
        base = base.resolve()
        target = (base / rest).resolve()
        if base not in target.parents or not target.is_file():
            return self.send_error(404)
        data = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)


def main():
    ap = argparse.ArgumentParser(description="Honk, the keeper on the Moon")
    ap.add_argument("--test", action="store_true", help="scripted mind, fixture Foundry and recorded pages; uses data/honk-test.db")
    ap.add_argument("--speed", type=float, help="simulated minutes per real minute")
    ap.add_argument("--port", type=int, default=int(os.environ.get("HONK_PORT", "8765")))
    args = ap.parse_args()
    app = App(os.environ.get("HONK_DATA") or ROOT / "data", test=args.test, speed=args.speed)
    Handler.app = app
    st = app.model_status()
    print(f"Honk's Moon: http://127.0.0.1:{args.port}/", flush=True)
    print(f"Mind: {app.sim.client.name} -> " + ("ready" if st.get("ready") else st.get("note") or "not ready"), flush=True)
    print(f"Foundry: {app.sim.foundry.client.name}   Gateway: {app.sim.p['gateway']['mode']}   Speed: {app.sim.p['sim']['speed']} sim min per real min", flush=True)
    try:
        ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        app.stop()


if __name__ == "__main__":
    main()
