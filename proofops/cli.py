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
from . import newplan as newplan_mod
from . import metrics as metrics_mod
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


def cmd_stats(args) -> int:
    """Local only: what this machine's own receipts add up to. No network, ever."""
    print(metrics_mod.stats_report(pathlib.Path(args.receipts)))
    return 0


def cmd_share(args) -> int:
    """Show the exact payload, then send it only if consent was recorded."""
    receipts = pathlib.Path(args.receipts)
    if args.enable:
        metrics_mod.set_consent(True, args.endpoint)
        print(f"sharing enabled -> {metrics_mod.consent()['endpoint']}")
    if args.disable:
        metrics_mod.set_consent(False, args.endpoint)
        print("sharing disabled — nothing will be sent")

    # `share` alone is always a dry run; only --enable/--send reach the network, and --send still
    # requires consent recorded on this machine. Remembering consent is not the same as using it.
    if args.dry_run or not (args.enable or getattr(args, "send", False)):
        print(metrics_mod.payload_bytes(receipts).decode())
        if not args.enable and not args.disable:
            print("\nNothing sent. Pass --enable to send (and remember), or --send to send again.")
        return 0

    try:
        res = metrics_mod.send(receipts, args.endpoint)
    except PermissionError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # network problems are not the payload's fault
        print(f"send failed: {e}", file=sys.stderr)
        return 2
    print(f"sent {res['sent_bytes']} bytes -> HTTP {res['status']}")
    return 0


def cmd_show(args) -> int:
    rec = json.loads(pathlib.Path(args.receipt).read_text())
    print(receipt_mod.summarise(rec))
    return _exit_code(rec)


def _run_mode(plan: dict) -> str:
    """Say up front whether a plan needs the operator to opt into running commands."""
    needs = any(c.get("type") == "command_exit" for c in plan["checks"])
    return "needs --allow-commands" if needs else "read-only"


def cmd_list(args) -> int:
    for p in sorted(pathlib.Path(args.plans).glob("*.json")):
        try:
            plan = plan_mod.load(p)
        except plan_mod.PlanError as e:
            print(f"{p.name}: INVALID — {e}")
            continue
        print(f"{p.name:44} {plan['name']}")
        print(f"{'':44} {plan['_revision']}  checks={len(plan['checks'])}  "
              f"target_kind={plan['target_kind']}  {_run_mode(plan)}")
    return 0


def cmd_new(args) -> int:
    """Write a starter plan for a directory, using what is actually in it."""
    try:
        body = newplan_mod.build(args.dir, args.name)
    except ValueError as e:
        print(f"cannot build a plan: {e}", file=sys.stderr)
        return 2

    text = json.dumps(body, indent=2) + "\n"
    if args.stdout:
        print(text, end="")
        return 0

    out = pathlib.Path(args.out) if args.out else pathlib.Path(args.dir) / "proofops-plan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not args.force:
        print(f"refusing to overwrite {out} (pass --force)", file=sys.stderr)
        return 2
    out.write_text(text)
    print(f"wrote {out}")
    print("  checks   " + ", ".join(c["id"] for c in body["checks"]))
    print(f"  next     python3 -m proofops run {out} --target local")
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

    n = sub.add_parser("new", help="write a starter plan for a directory")
    n.add_argument("--dir", default=".")
    n.add_argument("--name", default=None)
    n.add_argument("--out", default=None)
    n.add_argument("--stdout", action="store_true", help="print the plan instead of writing it")
    n.add_argument("--force", action="store_true")
    n.set_defaults(fn=cmd_new)

    l = sub.add_parser("list", help="list plans in a directory")
    l.add_argument("--plans", default="plans")
    l.set_defaults(fn=cmd_list)

    st = sub.add_parser("stats", help="what your own receipts add up to (local only)")
    st.add_argument("--receipts", default="receipts")
    st.set_defaults(fn=cmd_stats)

    sh = sub.add_parser("share", help="show, and opt in to sending, the anonymous usage aggregate")
    sh.add_argument("--receipts", default="receipts")
    sh.add_argument("--dry-run", action="store_true", help="print the payload and send nothing")
    sh.add_argument("--enable", action="store_true", help="record consent and send")
    sh.add_argument("--send", action="store_true", help="send using consent recorded earlier")
    sh.add_argument("--disable", action="store_true", help="forget consent")
    sh.add_argument("--endpoint", default=None)
    sh.set_defaults(fn=cmd_share)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
