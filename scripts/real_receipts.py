"""Produce a gallery of receipts against public, third-party targets.

Why: every receipt in the repo until now came from a fixture we built, so "does it work on anything
real?" is a fair question. These are read-only GETs against public endpoints, run once, with the
observed values published verbatim - including the checks that fail.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

PLANS = [
    {
        "name": "public: httpbin responds correctly",
        "target_kind": "public-readonly",
        "allowed_origins": ["https://httpbin.org"],
        "checks": [
            {"id": "status", "type": "http_status", "path": "/status/200", "expect": 200,
             "proves": "the endpoint answers 200"},
            {"id": "json-field", "type": "http_json_field", "path": "/json",
             "field": "slideshow.author", "equals": "Yours Truly",
             "proves": "a nested JSON field holds the documented value"},
            {"id": "body", "type": "http_body_contains", "path": "/html",
             "contains": "Herman Melville",
             "proves": "the response body contains the documented text"},
        ],
        "does_not_prove": ["that the service is useful, only that it answers as documented"],
    },
    {
        "name": "public: github api is up and rate-limited as documented",
        "target_kind": "public-readonly",
        "allowed_origins": ["https://api.github.com"],
        "checks": [
            {"id": "root-200", "type": "http_status", "path": "/", "expect": 200,
             "proves": "the API root answers 200"},
            {"id": "no-auth-required-for-root", "type": "http_status", "path": "/zen",
             "expect": 200, "proves": "an unauthenticated read succeeds"},
            {"id": "ratelimit-header-declared", "type": "http_header", "path": "/",
             "header": "x-ratelimit-limit", "equals": "60",
             "proves": "the rate-limit header is present and declares the documented budget"},
        ],
        "does_not_prove": ["that any repository or user data is reachable"],
    },
    {
        "name": "public: a static site serves the page it claims",
        "target_kind": "public-readonly",
        "allowed_origins": ["https://example.com"],
        "checks": [
            {"id": "200", "type": "http_status", "path": "/", "expect": 200,
             "proves": "the site answers 200"},
            {"id": "content-type", "type": "http_header", "path": "/",
             "header": "content-type", "equals": "text/html",
             "proves": "the response is HTML, not a JSON error page served with 200"},
            {"id": "has-title", "type": "http_body_contains", "path": "/",
             "contains": "Example Domain",
             "proves": "the body is the page the domain is documented to serve"},
        ],
        "does_not_prove": ["that the site is reachable from anywhere but here"],
    },
]


def main() -> int:
    root = pathlib.Path("/tmp/real-receipts")
    root.mkdir(exist_ok=True)
    out = []
    for plan in PLANS:
        p = root / (plan["name"].split(": ", 1)[1].replace(" ", "-")[:40] + ".json")
        p.write_text(json.dumps(plan, indent=2))
        target = plan["allowed_origins"][0]
        res = subprocess.run(
            [sys.executable, "-m", "proofops", "run", str(p), "--target", target,
             "--out", str(root / "receipts")],
            capture_output=True, text=True, timeout=120)
        rec_file = None
        for line in res.stdout.splitlines():
            if line.startswith("receipt: "):
                rec_file = line.split("receipt: ", 1)[1].strip()
        rec = json.loads(pathlib.Path(rec_file).read_text()) if rec_file else None
        out.append({"plan": plan["name"], "target": target, "stdout": res.stdout, "receipt": rec})
        print(f"{plan['name']}: exit {res.returncode}")

    pathlib.Path("/tmp/real-receipts/results.json").write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
