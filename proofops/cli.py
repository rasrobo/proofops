"""CLI: proofops run|verify|show|list

Exit codes matter more than the text: 0 only when every check passed, 1 when any check
failed, 2 when the run could not be performed at all (bad plan, refused origin, or a
command the operator never authorised — a receipt that says NOT RUN, never FAIL).
A caller that ignores the output can still trust the exit code.

``verify`` has its own contract, because it answers a different question — not "did the
checks pass" but "is this file the one that was written": 0 valid, 1 edited/signed by the
wrong key, 2 cannot verify (unsealed, or a signed receipt and no key).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import integrity as integrity_mod
from . import plan as plan_mod
from . import receipt as receipt_mod
from . import runner


def cmd_run(args) -> int:
    try:
        rec, path = runner.execute(
            args.plan, args.target,
            allow_commands=args.allow_commands, out=args.out,
            key=integrity_mod.key_from(args.key_file),
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


def cmd_verify(args) -> int:
    """Check that a receipt is the one that was written, and say what that does not prove."""
    path = pathlib.Path(args.receipt)
    try:
        rec = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read receipt: {e}", file=sys.stderr)
        return 2

    verdict, detail = integrity_mod.verify(rec, integrity_mod.key_from(args.key_file))
    print(f"{path}: {verdict}")
    print(f"  {detail.get('detail', '')}")
    for k in ("sealed", "recomputed", "key_id", "supplied_key_id"):
        if k in detail:
            print(f"  {k}: {detail[k]}")
    if rec.get("run_id"):
        print(f"  run: {rec['run_id']}  plan: {rec.get('plan')}  "
              f"verdict: {rec.get('summary', {}).get('verdict')}")
    print("  What this does NOT prove: that the checks were run honestly, that the plan was "
          "adequate, or that the observer is truthful. It proves the file is unchanged.")
    return {"valid": 0, "tampered": 1}.get(verdict, 2)


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
    r.add_argument("--key-file", default=None,
                   help="sign the receipt with this key (or set PROOPS_SIGNING_KEY)")
    r.set_defaults(fn=cmd_run)

    v = sub.add_parser("verify", help="check that a receipt has not been edited since it was written")
    v.add_argument("receipt")
    v.add_argument("--key-file", default=None,
                   help="key used to sign it (or set PROOPS_SIGNING_KEY)")
    v.set_defaults(fn=cmd_verify)

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
