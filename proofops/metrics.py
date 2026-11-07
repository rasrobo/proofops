"""Opt-in install metrics: local aggregation, explicit sharing, nothing by default.

Design constraint that shapes everything here: ProofOps is a tool whose product is *not overstating
what it knows*. So this module may never send anything that has not been (a) opted into with an
explicit yes, and (b) shown to the operator byte for byte first.

  proofops stats                 # local only, reads your own receipts, never touches the network
  proofops share --dry-run       # prints the exact payload, sends nothing
  proofops share --enable        # records consent, then sends
  proofops share --disable       # forgets consent; nothing is ever sent again

Payload is deliberately minimal. No paths, hostnames, plan names, receipt contents or command
output. The install id is a random uuid4, never derived from a machine id.
"""
from __future__ import annotations

import json
import os
import platform
import re
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_ENDPOINT = "https://hub.sqs.chat/api/proofops/metrics/"


def home() -> Path:
    return Path(os.environ.get("PROOPS_HOME", Path.home() / ".proofops"))


def _install() -> dict:
    p = home() / "install.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except ValueError:
            pass
    data = {"install_id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))
    return data


def _consent_path() -> Path:
    return home() / "consent.json"


def consent() -> dict:
    p = _consent_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except ValueError:
            pass
    return {"share": False, "endpoint": DEFAULT_ENDPOINT}


def set_consent(share: bool, endpoint: str | None = None) -> dict:
    c = {"share": bool(share), "endpoint": endpoint or consent().get("endpoint", DEFAULT_ENDPOINT),
         "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    p = _consent_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(c, indent=2))
    return c


# Mirrors proofops/checks.py:REGISTRY. Kept as a literal so the client does not import the check
# implementations just to report a name; a test asserts the two never drift.
CHECK_TYPES = frozenset({
    "command_exit", "file_sha256", "file_exists", "dir_manifest", "csv_stats", "image_size",
    "pdf_pages", "pdf_page_size", "pdf_text_contains", "sqlite_query",
    "http_status", "http_json_field", "http_body_contains", "http_header",
})


def collect_stats(receipts_dir: Path) -> dict:
    """Aggregate the operator's own receipts. Pure local file reads."""
    runs = 0
    checks = {"pass": 0, "fail": 0, "not_run": 0}
    by_type: dict[str, dict[str, int]] = {}
    verdicts: dict[str, int] = {}
    plans: set[str] = set()
    for f in sorted(Path(receipts_dir).glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        runs += 1
        summary = d.get("summary") or {}
        verdict = (summary.get("verdict") or d.get("verdict") or "").upper()
        if verdict:
            verdicts[verdict] = verdicts.get(verdict, 0) + 1
        if d.get("plan_revision"):
            plans.add(str(d["plan_revision"]))
        for c in d.get("checks") or []:
            status = c.get("status")
            if status == "not_run" or c.get("not_run"):
                outcome = "not_run"
            elif c.get("passed") is True:
                outcome = "pass"
            elif c.get("passed") is False:
                outcome = "fail"
            elif c.get("passed") is None and "passed" in c:
                # receipts mark a check that could not run as passed=None (see receipt.py)
                outcome = "not_run"
            else:
                continue
            checks[outcome] += 1
            # The check TYPE is a category (http_status, pdf_pages...). The check ID, path and
            # command are not collected at all - they describe the customer.
            t = str(c.get("type") or "")
            if t in CHECK_TYPES:
                bucket = by_type.setdefault(t, {"pass": 0, "fail": 0, "not_run": 0})
                bucket[outcome] += 1
    return {"runs": runs, "checks": checks, "by_type": by_type,
            "verdicts": verdicts, "plans": len(plans)}


VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+[0-9a-z.+-]{0,8}$")
PLATFORMS = {"linux", "darwin", "windows", "freebsd", "openbsd", "netbsd", "sunos", "aix"}


def sanitise(payload: dict) -> dict:
    """Force the payload into the shape we publish. Defence in depth.

    The gatherer already never reads a path, hostname or plan name, but this function exists so a
    future bug in `collect_stats` cannot leak one: anything that is not the expected key, not a
    non-negative int, or not a short [a-z0-9._-] token is dropped rather than forwarded.
    """
    def version(value) -> str:
        v = str(value or "").strip().lower()
        return v if VERSION_RE.match(v) else "unknown"

    def plat(value) -> str:
        # allow-list, not a blacklist: character-stripping a hostname still leaves the hostname
        p = str(value or "").strip().lower()
        return p if p in PLATFORMS else "other"

    def count(value) -> int:
        try:
            return max(0, min(int(value or 0), 10_000_000))
        except (TypeError, ValueError):
            return 0

    def by_type(value) -> dict:
        out = {}
        for t, counts in (value or {}).items():
            if t not in CHECK_TYPES or not isinstance(counts, dict):
                continue
            out[t] = {k: count(counts.get(k, 0)) for k in ("pass", "fail", "not_run")}
        return dict(sorted(out.items()))

    checks = payload.get("checks") or {}
    return {
        "schema": 2,
        "install_id": str(uuid.UUID(str(payload.get("install_id", "")))),
        "version": version(payload.get("version")),
        "platform": plat(payload.get("platform")),
        "runs": count(payload.get("runs")),
        "plans": count(payload.get("plans")),
        "checks": {k: count(checks.get(k, 0)) for k in ("pass", "fail", "not_run")},
        "by_type": by_type(payload.get("by_type")),
    }


def build_payload(receipts_dir: Path) -> dict:
    from . import __version__
    stats = collect_stats(receipts_dir)
    return {
        "install_id": _install()["install_id"],
        "version": __version__,
        "runs": stats["runs"],
        "checks": stats["checks"],
        "by_type": stats["by_type"],
        "plans": stats["plans"],
        "platform": platform.system().lower(),
    }


def payload_bytes(receipts_dir: Path) -> bytes:
    return json.dumps(sanitise(build_payload(receipts_dir)), sort_keys=True, indent=2).encode()


def send(receipts_dir: Path, endpoint: str | None = None) -> dict:
    """Send only with recorded consent. Refuses before opening a socket otherwise."""
    c = consent()
    if not c.get("share"):
        raise PermissionError(
            "sharing is off — run `proofops share --dry-run` to see the payload, "
            "then `proofops share --enable` to opt in")
    body = payload_bytes(receipts_dir)
    # Consent recorded by an earlier version stored the endpoint without its trailing slash, and
    # Django answers a slashless POST with 405 (it cannot 301 a body). Normalise, do not trust.
    url = (endpoint or c["endpoint"]).rstrip("/") + "/"
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "proofops-metrics"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return {"status": r.status, "sent_bytes": len(body)}


def stats_report(receipts_dir: Path) -> str:
    s = collect_stats(receipts_dir)
    lines = [f"runs        {s['runs']}",
             f"checks      {s['checks']['pass']} passed, {s['checks']['fail']} failed, "
             f"{s['checks']['not_run']} not run",
             f"plans       {s['plans']} distinct revisions"]
    if s["verdicts"]:
        lines.append("verdicts    " + ", ".join(f"{k} {v}" for k, v in sorted(s["verdicts"].items())))
    lines.append("")
    lines.append("Local only — nothing has left this machine.")
    return "\n".join(lines)
