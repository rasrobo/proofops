"""Plan loading and safety validation.

A plan is data, not code. It names a target, lists the only origins it may touch, and
declares checks. Two rules are enforced here rather than trusted to the author:

1. **Origin allowlist.** A plan must name every origin it will contact. A run against an
   origin the plan does not declare is refused *before* any request is made. This is what
   stops a copied plan from being pointed at production by editing one flag.

2. **Declared limitations are mandatory.** Every plan must state what passing does NOT
   prove. A plan without that field is rejected — the whole point is that a green tick is
   not a claim of correctness.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from urllib.parse import urlparse

REQUIRED = ("name", "target_kind", "allowed_origins", "checks", "does_not_prove")


class PlanError(Exception):
    pass


def load(path: str | pathlib.Path) -> dict:
    p = pathlib.Path(path)
    try:
        plan = json.loads(p.read_text())
    except FileNotFoundError:
        raise PlanError(f"plan not found: {p}")
    except json.JSONDecodeError as e:
        raise PlanError(f"plan is not valid JSON: {e}")

    missing = [k for k in REQUIRED if k not in plan]
    if missing:
        raise PlanError(f"plan missing required field(s): {', '.join(missing)}")

    if not isinstance(plan["checks"], list) or not plan["checks"]:
        raise PlanError("plan declares no checks")
    if not isinstance(plan["allowed_origins"], list):
        raise PlanError("allowed_origins must be a list")
    # A command-only plan contacts nothing, so an empty allowlist is legitimate there;
    # a plan with HTTP checks must name the origins it will reach.
    has_http = any(c.get("type", "").startswith("http_") for c in plan["checks"])
    if has_http and not plan["allowed_origins"]:
        raise PlanError("plan has HTTP checks but declares no allowed_origins")

    for c in plan["checks"]:
        if "type" not in c or "id" not in c:
            raise PlanError(f"check needs 'id' and 'type': {c}")
        if "proves" not in c:
            raise PlanError(f"check '{c['id']}' must state what it proves")
        if c["type"] == "command_exit":
            declared = plan.get("allowed_commands") or []
            if c.get("command") not in declared:
                raise PlanError(
                    f"check '{c['id']}' runs a command not listed in allowed_commands: "
                    f"{c.get('command')!r}"
                )

    plan["_path"] = str(p)
    plan["_revision"] = revision(plan)
    return plan


def revision(plan: dict) -> str:
    """Content hash of the plan body, excluding loader metadata and display-only notes.

    Receipts record this, so a before/after comparison can prove the SAME plan produced
    both results. Changing an assertion changes the revision — which is exactly why a
    weakened plan cannot be passed off as the original.
    """
    body = {k: v for k, v in plan.items() if not k.startswith("_")}
    return "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def check_origin(plan: dict, target: str) -> None:
    origin = "{0.scheme}://{0.netloc}".format(urlparse(target))
    if origin not in plan["allowed_origins"]:
        raise PlanError(
            f"refusing to contact {origin}: not in allowed_origins {plan['allowed_origins']}. "
            "Add it to the plan deliberately if this is intended."
        )
