"""Receipts: the artefact a completion claim should point at.

A receipt is a JSON document that says what was checked, what was observed, and what the
result does NOT prove. It is written to disk with the run id in the filename and is
deliberately git-ignored: receipts describe a live environment and do not belong in a
public repository.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import platform
import secrets

SCHEMA = "proofops.receipt/1"


def new_run_id() -> str:
    """Time-ordered and unique: PO-20261104T2330Z-4f2a"""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"PO-{stamp}-{secrets.token_hex(2)}"


def write(receipt: dict, out_dir: str | pathlib.Path = "receipts") -> pathlib.Path:
    d = pathlib.Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{receipt['run_id']}.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=False) + "\n")
    return path


def build(plan: dict, target: str, results: list[dict]) -> dict:
    # Three outcomes, not two. ``passed`` is True / False / None, where None means the
    # check could not be performed (a command the operator never authorised). Counting a
    # refusal as a failure would let a receipt assert that something was tested and broke
    # when in fact it was never run.
    passed = sum(1 for r in results if r["passed"] is True)
    failed = sum(1 for r in results if r["passed"] is False)
    not_run = sum(1 for r in results if r["passed"] is None)
    if not results:
        verdict = "FAIL"
    elif failed:
        verdict = "FAIL"
    elif not_run:
        verdict = "INCOMPLETE"
    else:
        verdict = "PASS"
    return {
        "schema": SCHEMA,
        "run_id": new_run_id(),
        "plan": plan["name"],
        "plan_revision": plan["_revision"],
        # The full plan body travels with the receipt, so the evidence is self-contained:
        # you can read exactly which assertions produced this verdict, and re-run them,
        # without needing the file that happened to sit on disk at the time.
        "plan_body": {k: v for k, v in plan.items() if not k.startswith("_")},
        "plan_file": plan["_path"],
        "target": target,
        "target_kind": plan["target_kind"],
        "started_at": results[0]["started_at"] if results else None,
        "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "checks": len(results),
            "passed": passed,
            "failed": failed,
            "not_run": not_run,
            "verdict": verdict,
        },
        "checks": results,
        # Copied into every receipt on purpose: the limitations travel with the evidence,
        # so a receipt can never be quoted as "everything works".
        "does_not_prove": plan["does_not_prove"],
        "environment": {
            "proofops": "0.1.0",
            "python": platform.python_version(),
            "platform": platform.system(),
        },
    }


def summarise(receipt: dict) -> str:
    lines = [
        f"ProofOps run {receipt['run_id']} {receipt['summary']['verdict'].lower()}:",
        f"  plan      {receipt['plan']} ({receipt['plan_revision']})",
        f"  target    {receipt['target']} [{receipt['target_kind']}]",
    ]
    for c in receipt["checks"]:
        mark = {True: "PASS", False: "FAIL", None: "NOT RUN"}[c["passed"]]
        lines.append(f"  [{mark}] {c['id']}: {c['proves']}")
        detail = c["evidence"]
        if c["passed"] is not True:
            lines.append(f"         observed: {json.dumps(detail)[:300]}")
    lines.append("  Not verified:")
    for item in receipt["does_not_prove"]:
        lines.append(f"    - {item}")
    return "\n".join(lines)
