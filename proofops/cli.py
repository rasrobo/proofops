"""CLI: proofops run|list|show

Exit codes matter more than the text: 0 only when every check passed, 1 when any check
failed, 2 when the run could not be performed at all (bad plan, refused origin, or a
command the operator never authorised — a receipt that says NOT RUN, never FAIL).
A caller that ignores the output can still trust the exit code.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import plan as plan_mod
from . import receipt as receipt_mod
from . import runner


def cmd_run(args) -> int:
    try:
        rec, path = runner.execute(
            args.plan, args.target,
            allow_commands=args.allow_commands, out=args.out,
        )
    except plan_mod.PlanError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2

    print(receipt_mod.summarise(rec))
    print(f"\nreceipt: {path}")
    return _exit_code(rec)


def _exit_code(rec: dict) -> int:
    """0 pass · 1 any check failed · 2 nothing was actually tested (refused / incomplete)."""
    verdict = rec["summary"]["verdict"]
    return {"PASS": 0, "INCOMPLETE": 2}.get(verdict, 1)


def cmd_show(args) -> int:
    rec = json.loads(pathlib.Path(args.receipt).read_text())
    print(receipt_mod.summarise(rec))
    return _exit_code(rec)


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
