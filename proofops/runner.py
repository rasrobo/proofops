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


def _constrain_roots(plan_roots, operator_roots) -> tuple[str, ...]:
    """A model-written plan may not widen the file roots the operator configured.

    Every plan root must sit inside an operator root (resolved, so symlinks cannot smuggle
    a root out). An empty operator list allows no file reads at all. The plan's own roots
    are returned unchanged — they are already inside the operator's, so they stay the
    tighter fence.
    """
    import os

    op = [os.path.realpath(r) for r in operator_roots]
    for root in plan_roots:
        real = os.path.realpath(root)
        if not any(real == o or real.startswith(o + os.sep) for o in op):
            raise plan_mod.PlanError(
                f"plan allowed_paths {root!r} is outside the operator-configured "
                f"allowed_paths {list(operator_roots)}")
    return tuple(plan_roots)


def execute(
    plan_path: str,
    target: str,
    *,
    allow_commands: bool = False,
    out: str = "receipts",
    key: str | None = None,
    approve_command=None,
    env_vars: tuple[str, ...] = (),
    allow_local_targets: bool = False,
    operator_allowed_paths: tuple[str, ...] | None = None,
) -> tuple[dict, str]:
    """Run every check in the plan. Returns (receipt, path the receipt was written to).

    approve_command(command, argv) -> bool is the per-command operator approval used by
    the plugin (config allowlist, then an approval prompt showing the exact argv). The
    CLI passes None: there --allow-commands already is the operator's approval.
    operator_allowed_paths, when set, is the operator-owned fence for file reads: every
    plan root must sit inside it.
    """
    plan = plan_mod.load(plan_path)
    if any(c.get("type", "").startswith("http_") for c in plan["checks"]):
        plan_mod.check_origin(plan, target)

    checks_mod.set_network_policy(allow_local_targets)
    commands_mod.set_policy(commands_mod.CommandPolicy(
        enabled=bool(allow_commands),
        allowed=tuple(plan.get("allowed_commands") or ()),
        approver=approve_command,
        env_vars=tuple(env_vars or ()),
    ))
    # File reads are fenced by the plan's own declared roots, exactly like origins: a copied
    # plan cannot be redirected at a home directory by editing one string. When the operator
    # configured roots too, the plan's roots must sit inside them.
    roots = tuple(plan.get("allowed_paths") or ())
    if operator_allowed_paths is not None:
        roots = _constrain_roots(roots, tuple(operator_allowed_paths))
    artifacts_mod.set_policy(artifacts_mod.PathPolicy(roots))

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
