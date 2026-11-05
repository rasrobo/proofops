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
import re
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

    # File reads are fenced the same way origins are: a plan that reads deliverables must
    # name the roots it may read, and every path it asks for must stay inside them.
    from .checks import FILE_CHECK_TYPES  # lazy: keeps plan.py free of the check modules

    has_file = any(c.get("type") in FILE_CHECK_TYPES for c in plan["checks"])
    if has_file:
        roots = plan.get("allowed_paths")
        if not isinstance(roots, list) or not roots:
            raise PlanError("plan has file checks but declares no allowed_paths")
        for root in roots:
            if not isinstance(root, str) or not root.startswith("/"):
                raise PlanError(f"allowed_paths entries must be absolute: {root!r}")
    for c in plan["checks"]:
        if c.get("type") in FILE_CHECK_TYPES:
            p = c.get("path")
            if not isinstance(p, str) or not p or p.startswith("/") or ".." in pathlib.PurePath(p).parts:
                raise PlanError(f"check '{c['id']}' path must be relative and stay inside the roots: {p!r}")

    for c in plan["checks"]:
        if "type" not in c or "id" not in c:
            raise PlanError(f"check needs 'id' and 'type': {c}")
        if "proves" not in c:
            raise PlanError(f"check '{c['id']}' must state what it proves")
        # An unknown type is a broken plan, not a failed assertion: at run time it would be
        # the one outcome that must never be guessed at. Refuse it before anything executes.
        from .checks import REGISTRY

        if c["type"] not in REGISTRY:
            raise PlanError(
                f"check '{c['id']}' has unknown type '{c['type']}'. "
                f"Known types: {', '.join(sorted(REGISTRY))}"
            )
        ex = c.get("extract")
        if ex is not None:
            # Extraction feeds the receipt's headline evidence, so a broken pattern is a
            # plan error at load time — never a silent blank in a judge-facing document.
            for item in (ex if isinstance(ex, list) else [ex]):
                if not isinstance(item, dict) or not item.get("name") or not item.get("regex"):
                    raise PlanError(
                        f"check '{c['id']}' has an extract block but no 'name' and 'regex'"
                    )
                try:
                    re.compile(item["regex"])
                except re.error as e:
                    raise PlanError(f"check '{c['id']}' extract regex is invalid: {e}")
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
