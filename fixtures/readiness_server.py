#!/usr/bin/env python3
"""Disposable local stand-in for a deployment readiness endpoint.

This exists only so the failure -> repair -> pass cycle can be demonstrated without
touching a real environment. It serves the same shape as claw-way-django's /health:

    {"status": "ok", "backend": "django", "database": "postgresql"}

The values come from state.json next to this file, so a "defect" is a one-line edit of a
throwaway file — not a change to any running service.

    python3 fixtures/readiness_server.py 8099
"""

import json
import pathlib
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE = pathlib.Path(__file__).with_name("state.json")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(json.loads(STATE.read_text())).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass  # keep the demo output clean


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print(f"readiness fixture on http://127.0.0.1:{port}/health  (state: {STATE})", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
