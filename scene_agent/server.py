"""HTTP front-end for the Scene Agent PoC (standard library only).

Run:
    python -m scene_agent.server --root ./scene_agent_data --port 8765

The service binds 127.0.0.1 by default (single user, no auth), matching the
first-phase delivery decision (D6). All paths are POST /v1/scene/... and return
HTTP 200 with {"ok": ...}; protocol errors use 400/404/500.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import errors as E
from .store import SceneStore

MAX_BODY = 2 * 1024 * 1024

ROUTES = {
    "/v1/scene/import": lambda st, b: st.import_scene(b),
    "/v1/scene/load": lambda st, b: st.scene_load(b),
    "/v1/scene/query": lambda st, b: st.scene_query(b),
    "/v1/scene/get": lambda st, b: st.scene_get(b),
    "/v1/scene/edit/plan": lambda st, b: st.scene_plan(b),
    "/v1/scene/edit/commit": lambda st, b: st.scene_commit(b),
    "/v1/scene/verify": lambda st, b: st.scene_verify(b),
    "/v1/scene/versions": lambda st, b: st.scene_versions(b),
    "/v1/scene/rollback": lambda st, b: st.scene_rollback(b),
    "/v1/scene/undo": lambda st, b: st.scene_undo(b),
    "/v1/scene/checkpoint/save": lambda st, b: st.checkpoint_save(b),
    "/v1/scene/checkpoint/open": lambda st, b: st.checkpoint_open(b),
}


def _read_json(handler):
    length = handler.headers.get("Content-Length")
    if not length:
        raise ValueError("Content-Length is required")
    n = int(length)
    if n <= 0 or n > MAX_BODY:
        raise ValueError(f"body must be 1..{MAX_BODY} bytes")
    raw = handler.rfile.read(n)
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("body must be a JSON object")
    return obj


class Handler(BaseHTTPRequestHandler):
    server_version = "SceneAgent/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep stdout clean for tests
        pass

    def _send(self, status, obj):
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/v1/scene/health", "/health"):
            self._send(200, {"ok": True, "service": "scene-agent", "version": "0.1"})
        else:
            self._send(404, {"ok": False, "error": {"code": E.NOT_FOUND,
                                                    "message": "unknown path"}})

    def do_POST(self):
        path = self.path.split("?")[0]
        handler = ROUTES.get(path)
        if not handler:
            self._send(404, {"ok": False, "error": {"code": E.NOT_FOUND,
                                                    "message": f"unknown path: {path}"}})
            return
        try:
            body = _read_json(self)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            self._send(400, {"ok": False, "error": {"code": E.PARAM_TYPE,
                                                    "message": f"bad request: {exc}"}})
            return
        try:
            response = handler(self.server.store, body)
            self._send(200, response)
        except E.SceneError as exc:
            self._send(200, exc.to_response())
        except Exception:  # pragma: no cover - defensive
            traceback.print_exc()
            self._send(500, {"ok": False, "error": {"code": "E_SCENE_INTERNAL",
                                                    "message": "internal error"}})


def make_server(root, host="127.0.0.1", port=8765):
    store = SceneStore(root)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.store = store
    return httpd


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scene Agent PoC HTTP service")
    ap.add_argument("--root", default="scene_agent_data", help="data root (default: ./scene_agent_data)")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default: loopback)")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    httpd = make_server(args.root, args.host, args.port)
    host, port = httpd.server_address[:2]
    print(f"Scene Agent listening on http://{host}:{port}  (root={args.root})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
