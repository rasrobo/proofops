"""`proofops demo` — one command, no config, no network: a defect, caught.

The first minute matters more than any feature. A judge who installs should not have to author a
plan to see what this does. So the demo builds its own fixture, serves it on loopback, runs a real
plan against it, and then shows the two things that make the tool worth having:

  1. a check that PASSES while the product is broken (the 200 that lies), and
  2. a receipt whose verdict changes when someone edits it.

Everything is temporary and local. Nothing leaves the machine.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import integrity, receipt as receipt_mod, runner

PLAN = {
    "name": "demo: does this service actually work?",
    "target_kind": "local-fixture",
    "notes": "A loopback fixture that reports the wrong thing while answering 200.",
    "allowed_origins": [],          # filled in at run time with the ephemeral port
    "checks": [
        {"id": "reachable", "type": "http_status", "path": "/health.json", "expect": 200,
         "proves": "the endpoint answers 200"},
        {"id": "says-ok", "type": "http_json_field", "path": "/health.json", "field": "status",
         "equals": "ok",
         "proves": "the service says it is healthy, rather than a proxy answering for it"},
        {"id": "export-has-three-rows", "type": "csv_stats", "path": "export.csv", "rows": 3,
         "proves": "the export contains every row it should"},
        {"id": "export-exists", "type": "file_exists", "path": "export.csv",
         "proves": "the export was written at all"},
    ],
    "does_not_prove": [
        "that the rows are correct, only that there are three of them",
        "that anyone has read the export",
    ],
}

BANNER = """
──────────────────────────────────────────────────────────────────────
  proofops demo — a green tick that lies, caught in about 20 seconds
──────────────────────────────────────────────────────────────────────
"""


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - base class signature
        """A demo should not print access logs."""
        return


def run(stream=None) -> int:
    out = stream or sys.stdout

    def say(s=""):
        print(s, file=out, flush=True)

    say(BANNER)
    with tempfile.TemporaryDirectory(prefix="proofops-demo-") as td:
        root = Path(td)
        # A service that is up, answering 200, and reporting the wrong state. This is the case
        # status codes cannot catch.
        (root / "health.json").write_text(json.dumps({"status": "degraded", "backend": "django"}))
        (root / "export.csv").write_text("country,region\nSpain,EU\nFrance,EU\nItaly,EU\n")

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Quiet, directory=str(root)))
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        target = f"http://127.0.0.1:{port}"

        plan = dict(PLAN, allowed_origins=[target], allowed_paths=[str(root)])
        plan_path = root / "demo-plan.json"
        plan_path.write_text(json.dumps(plan, indent=2))

        say(f"fixture: {target}/health.json answers 200 and reports {{\"status\": \"degraded\"}}")
        say("")
        try:
            # The demo fixture is the operator's own loopback server, started above:
            # local targets are allowed here, and only here, by an explicit opt-in.
            rec, path = runner.execute(str(plan_path), target, out=str(root / "receipts"),
                                       allow_local_targets=True)
        finally:
            httpd.shutdown()
            httpd.server_close()

        say(receipt_mod.summarise(rec))
        say("")
        say("  → read the first two lines: the endpoint answered 200, and the check that only asked")
        say("    for a status code passed. The check that asked what the service SAYS is the one that")
        say("    failed. A monitoring ping would have called this healthy.")
        say("")

        # Second half: a receipt whose verdict changes when edited.
        sealed = Path(path)
        tampered = root / "tampered.json"
        data = json.loads(sealed.read_text())
        for c in data.get("checks", []):
            if c.get("id") == "says-ok":
                c["passed"] = True                      # forge the failure into a pass
                break
        tampered.write_text(json.dumps(data, indent=2))

        say("  Now edit the receipt: flip the failed check to passed, as a hurried agent might.")
        before = integrity.verify(json.loads(sealed.read_text()))
        after = integrity.verify(json.loads(tampered.read_text()))
        say(f"    original receipt: {before[0]}")
        say(f"    edited receipt:   {after[0]}  ({after[1].get('detail', '')})")
        say("")

        if rec.get("summary", {}).get("verdict") == "PASS":
            say("  WARNING: the demo fixture changed behaviour — this demo is meant to end in a FAIL.")
            return 3
        say("  That is the whole product: not a status code, a claim you can check.")
        say("")
        say("  next:  proofops new my-plan.json     # write a plan for your own service")
        say("         proofops run my-plan.json --target https://your-service.example")
        say("         proofops verify receipts/<run>.json")
        say("  docs:  github.com/rasrobo/proofops")
    return 0
