"""Execute a plan and write a receipt.

Extracted from the CLI so the Hermes plugin and `python3 -m proofops` run **one** code
path: a plugin that re-implemented the loop would eventually disagree with the CLI, and
two ways to produce a receipt is two different meanings for "verified".

`execute` raises `plan.PlanError` for a bad plan or an origin the plan never declared —
the caller decides the exit code / tool error.
"""

from __future__ import annotations

import datetime

from . import artifacts as artifacts_mod
from . import checks as checks_mod
from . import commands as commands_mod
from . import plan as plan_mod
from . import receipt as receipt_mod


def execute(
    plan_path: str,
    target: str,
    *,
    allow_commands: bool = False,
    out: str = "receipts",
    key: str | None = None,
) -> tuple[dict, str]:
    """Run every check in the plan. Returns (receipt, path the receipt was written to)."""
    plan = plan_mod.load(plan_path)
    if any(c.get("type", "").startswith("http_") for c in plan["checks"]):
        plan_mod.check_origin(plan, target)

    commands_mod.set_policy(commands_mod.CommandPolicy(
        enabled=bool(allow_commands),
        allowed=tuple(plan.get("allowed_commands") or ()),
    ))
    # File reads are fenced by the plan's own declared roots, exactly like origins: a copied
    # plan cannot be redirected at a home directory by editing one string.
    artifacts_mod.set_policy(artifacts_mod.PathPolicy(tuple(plan.get("allowed_paths") or ())))

    results = []
    for spec in plan["checks"]:
        fn = checks_mod.REGISTRY.get(spec["type"])
        started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        if fn is None:
            results.append({
                "id": spec["id"], "type": spec["type"], "passed": False,
                "proves": spec["proves"], "started_at": started,
                "evidence": {"error": f"unsupported check type '{spec['type']}'"},
            })
            continue
        try:
            ok, evidence = fn(spec, target)
        except KeyError as e:
            # A malformed check is a defect in the PLAN, not in the target: nothing was tested, so
            # this must never read as "the service failed". NOT RUN, with the key that is missing.
            ok = None
            evidence = {
                "error": f"check is missing required key {e}",
                "how_to_fix": f"add {e} to this check, or run `proofops new` for a valid template",
            }
        results.append({
            "id": spec["id"], "type": spec["type"], "passed": ok,
            "proves": spec["proves"], "started_at": started, "evidence": evidence,
        })

    rec = receipt_mod.build(plan, target, results, key=key)
    path = receipt_mod.write(rec, out)
    return rec, str(path)
