"""Check implementations.

Every check is read-only by construction: the only network verb is GET. A plan cannot
ask ProofOps to POST, PUT, DELETE or run a shell command — those belong to the tools that
perform repairs, not to the thing that verifies them.

Each check returns (passed: bool, evidence: dict). Evidence is what a reader needs to
judge the claim without trusting the verdict: the value observed, where it came from,
and how long it took.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

TIMEOUT = 15
MAX_BODY = 2 * 1024 * 1024  # never pull more than 2 MB into a receipt


def _get(url: str) -> tuple[int | None, bytes, dict, float, str]:
    started = time.monotonic()
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "proofops/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read(MAX_BODY)
            return r.status, body, dict(r.headers), time.monotonic() - started, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read(MAX_BODY), dict(e.headers or {}), time.monotonic() - started, ""
    except Exception as e:  # DNS, TLS, timeout, refusal
        return None, b"", {}, time.monotonic() - started, f"{type(e).__name__}: {e}"


def http_status(spec: dict, target: str) -> tuple[bool, dict]:
    url = target.rstrip("/") + spec["path"]
    status, _, _, elapsed, err = _get(url)
    want = int(spec["expect"])
    ok = status == want
    return ok, {
        "url": url,
        "expected_status": want,
        "observed_status": status,
        "elapsed_ms": round(elapsed * 1000),
        "error": err,
    }


def http_json_field(spec: dict, target: str) -> tuple[bool, dict]:
    """Assert one field of a JSON response.

    'equals' is exact (string compare after json parsing); 'contains' is a substring test
    for prose fields. Use 'equals' whenever the value is enumerable — a substring match
    on a status field would accept "not_ok".
    """
    url = target.rstrip("/") + spec["path"]
    field = spec["field"]
    status, body, _, elapsed, err = _get(url)
    observed = None
    parsed = False
    if body:
        try:
            doc = json.loads(body)
            parsed = True
            cur = doc
            for part in field.split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            observed = cur
        except Exception:
            parsed = False

    if "equals" in spec:
        ok = parsed and observed == spec["equals"]
        mode = "equals"
        want = spec["equals"]
    else:
        ok = parsed and observed is not None and str(spec["contains"]) in str(observed)
        mode = "contains"
        want = spec["contains"]

    return ok, {
        "url": url,
        "field": field,
        "mode": mode,
        "expected": want,
        "observed": observed,
        "body_parsed_as_json": parsed,
        "http_status": status,
        "elapsed_ms": round(elapsed * 1000),
        "error": err,
    }


def http_body_contains(spec: dict, target: str) -> tuple[bool, dict]:
    url = target.rstrip("/") + spec["path"]
    status, body, _, elapsed, err = _get(url)
    text = body.decode("utf-8", "replace")
    needle = spec["contains"]
    ok = needle in text
    return ok, {
        "url": url,
        "contains": needle,
        "http_status": status,
        "body_bytes": len(body),
        "observed_snippet": text[max(0, text.find(needle) - 40): text.find(needle) + len(needle) + 40]
        if needle in text else text[:120],
        "elapsed_ms": round(elapsed * 1000),
        "error": err,
    }


def http_header_equals(spec: dict, target: str) -> tuple[bool, dict]:
    url = target.rstrip("/") + spec["path"]
    status, _, headers, elapsed, err = _get(url)
    name = spec["header"]
    observed = None
    for k, v in headers.items():
        if k.lower() == name.lower():
            observed = v
    ok = observed is not None and str(spec["equals"]).lower() in str(observed).lower()
    return ok, {
        "url": url,
        "header": name,
        "expected_contains": spec["equals"],
        "observed": observed,
        "http_status": status,
        "elapsed_ms": round(elapsed * 1000),
        "error": err,
    }


from . import commands  # noqa: E402  (registered below)

REGISTRY = {
    "command_exit": commands.command_exit,
    "http_status": http_status,
    "http_json_field": http_json_field,
    "http_body_contains": http_body_contains,
    "http_header": http_header_equals,
}
