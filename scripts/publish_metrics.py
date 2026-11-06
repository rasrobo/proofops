#!/usr/bin/env python3
"""Aggregate opted-in ProofOps install metrics into a public JSON report.

Reads the hub's NDJSON ingest log (one line per `proofops share`), keeps the LATEST record per
install id — the client sends cumulative counters, so summing every row would double-count — and
writes a small aggregate a static page can render.

    python3 scripts/publish_metrics.py --ndjson /app/data/proofops_metrics.ndjson --out docs/metrics/data.json
    python3 scripts/publish_metrics.py --from-hub            # fetch over ssh, then write
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HOP = ("ssh -o ConnectTimeout=15 rasrobo@gpu.sqs.chat "
       "'ssh hub \"docker exec claw-way-django-web-1 cat /app/data/proofops_metrics.ndjson\"'")


def latest_per_install(lines: list[str]) -> dict[str, dict]:
    seen: dict[str, dict] = {}
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        iid = str(rec.get("install_id") or "")
        if not iid:
            continue
        prev = seen.get(iid)
        if prev is None or str(rec.get("received_at", "")) >= str(prev.get("received_at", "")):
            seen[iid] = rec
    return seen


def aggregate(records: dict[str, dict]) -> dict:
    runs = 0
    checks = {"pass": 0, "fail": 0, "not_run": 0}
    versions: Counter = Counter()
    platforms: Counter = Counter()
    for rec in records.values():
        runs += int(rec.get("runs", 0) or 0)
        c = rec.get("checks") or {}
        for k in checks:
            checks[k] += int(c.get(k, 0) or 0)
        versions[str(rec.get("version", "unknown"))[:20]] += 1
        platforms[str(rec.get("platform", "unknown"))[:20]] += 1
    total_checks = sum(checks.values())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "installs": len(records),
        "runs": runs,
        "checks": checks,
        "total_checks": total_checks,
        "pass_rate": round(100 * checks["pass"] / total_checks, 1) if total_checks else None,
        "versions": dict(versions.most_common()),
        "platforms": dict(platforms.most_common()),
        "source": "self-reported by operators who ran `proofops share --enable`",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ndjson", default=None)
    ap.add_argument("--from-hub", action="store_true")
    ap.add_argument("--out", default="docs/metrics/data.json")
    args = ap.parse_args()

    if args.from_hub:
        res = subprocess.run(HOP, shell=True, capture_output=True, text=True)
        text = res.stdout if res.returncode == 0 else ""
        if res.returncode != 0:
            print("hub read failed; writing an empty report:", res.stderr.strip()[:160])
    elif args.ndjson:
        p = Path(args.ndjson)
        text = p.read_text() if p.exists() else ""
    else:
        text = ""

    agg = aggregate(latest_per_install(text.splitlines()))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(agg, indent=2) + "\n")
    print(json.dumps({k: agg[k] for k in ("installs", "runs", "checks", "pass_rate")}, indent=2))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
