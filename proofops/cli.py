"""CLI: proofops run|list|show

Exit codes matter more than the text: 0 only when every check passed, 1 when any check
failed, 2 when the run could not be performed at all (bad plan, refused origin).
A caller that ignores the output can still trust the exit code.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

from . import checks as checks_mod
from . import commands as commands_mod
from . import plan as plan_mod
from . import receipt as receipt_mod


def cmd_run(args) -> int:
    try:
        plan = plan_mod.load(args.plan)
        if any(c.get("type", "").startswith("http_") for c in plan["checks"]):
            plan_mod.check_origin(plan, args.target)
    except plan_mod.PlanError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2

    commands_mod.set_policy(commands_mod.CommandPolicy(
        enabled=bool(args.allow_commands),
        allowed=tuple(plan.get("allowed_commands") or ()),
    ))

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
            ok, evidence = fn(spec, args.target)
        except KeyError as e:
            ok, evidence = False, {"error": f"check is missing required key {e}"}
        results.append({
            "id": spec["id"], "type": spec["type"], "passed": ok,
            "proves": spec["proves"], "started_at": started, "evidence": evidence,
        })

    rec = receipt_mod.build(plan, args.target, results)
    path = receipt_mod.write(rec, args.out)
    print(receipt_mod.summarise(rec))
    print(f"\nreceipt: {path}")
    return 0 if rec["summary"]["verdict"] == "PASS" else 1


def cmd_show(args) -> int:
    rec = json.loads(pathlib.Path(args.receipt).read_text())
    print(receipt_mod.summarise(rec))
    return 0 if rec["summary"]["verdict"] == "PASS" else 1


def cmd_list(args) -> int:
    for p in sorted(pathlib.Path(args.plans).glob("*.json")):
        try:
            plan = plan_mod.load(p)
        except plan_mod.PlanError as e:
            print(f"{p.name}: INVALID — {e}")
            continue
        print(f"{p.name:44} {plan['name']}")
        print(f"{'':44} {plan['_revision']}  checks={len(plan['checks'])}  target_kind={plan['target_kind']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="proofops", description="Verify completion claims independently.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a plan against a target")
    r.add_argument("plan")
    r.add_argument("--target", required=True)
    r.add_argument("--out", default="receipts")
    r.add_argument("--allow-commands", action="store_true",
                   help="permit checks to run commands the plan declares in allowed_commands")
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("show", help="re-print a saved receipt")
    s.add_argument("receipt")
    s.set_defaults(fn=cmd_show)

    l = sub.add_parser("list", help="list plans in a directory")
    l.add_argument("--plans", default="plans")
    l.set_defaults(fn=cmd_list)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
