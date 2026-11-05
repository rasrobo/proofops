"""proofops — make Hermes verify its own "done" before it says it.

Three tools and one skill. The engine is the same code `python3 -m proofops` runs; this
plugin adds no check types, cannot repair anything, and cannot widen a plan's allowlist.
Its only job is to put a receipt between an agent and the word "done".

Read-only: the only network verb in the engine is GET. The one side effect available is a
command a plan declares verbatim in `allowed_commands` **and** the operator opts into per
call with allow_commands=true — the same two-gate fence the CLI enforces.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
# The engine package sits beside this file. It is imported under a private module name so
# that it can never collide with this plugin module (which the loader may register as
# "proofops" itself).
_ENGINE_NAME = "proofops_engine_runtime"
_SKILL = _HERE / "skills" / "verify-before-done" / "SKILL.md"


def _engine():
    if _ENGINE_NAME in sys.modules:
        return sys.modules[_ENGINE_NAME]
    init = _HERE / "proofops" / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        _ENGINE_NAME, str(init), submodule_search_locations=[str(init.parent)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_ENGINE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


def _sub(name: str):
    _engine()
    return importlib.import_module(f"{_ENGINE_NAME}.{name}")


def _receipt_dir() -> pathlib.Path:
    home = pathlib.Path(os.environ.get("HERMES_HOME") or "~/.hermes").expanduser()
    d = home / "proofops" / "receipts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mark(passed) -> str:
    return {True: "PASS", False: "FAIL", None: "NOT RUN"}[passed]


def _plans(args: dict, **_kw) -> str:
    """List the plans in a directory, with the revision each one is pinned to."""
    d = pathlib.Path(args.get("plans_dir") or "plans").expanduser()
    if not d.is_dir():
        return json.dumps({"error": f"no plans directory at {d}",
                           "hint": "pass plans_dir, or run from a repo that has plans/*.json"})
    plan_mod = _sub("plan")
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            plan = plan_mod.load(p)
        except plan_mod.PlanError as e:
            out.append({"file": str(p), "invalid": str(e)})
            continue
        out.append({
            "file": str(p),
            "name": plan["name"],
            "revision": plan["_revision"],
            "target_kind": plan["target_kind"],
            "checks": len(plan["checks"]),
            "does_not_prove": plan["does_not_prove"],
        })
    return json.dumps({"plans_dir": str(d), "plans": out}, indent=2)


def _run(args: dict, **_kw) -> str:
    """Run one plan and return the receipt's substance, including what it does not prove."""
    plan_path, target = args.get("plan"), args.get("target")
    if not plan_path or not target:
        return json.dumps({"error": "both 'plan' and 'target' are required"})
    out = pathlib.Path(args.get("out") or _receipt_dir())
    runner = _sub("runner")
    plan_mod = _sub("plan")
    try:
        rec, path = runner.execute(
            str(plan_path), str(target),
            allow_commands=bool(args.get("allow_commands")), out=str(out))
    except plan_mod.PlanError as e:
        # A refused plan is not a failed check: say plainly that nothing was tested.
        return json.dumps({"refused": str(e), "ran": False,
                           "note": "nothing was contacted or executed"}, indent=2)
    except Exception as e:  # a broken plan/target must surface, never look like a pass
        return json.dumps({"error": f"{type(e).__name__}: {e}", "ran": False})

    checks = []
    for c in rec["checks"]:
        item = {"id": c["id"], "result": _mark(c["passed"]), "proves": c["proves"]}
        if c["passed"] is not True:
            item["observed"] = c["evidence"]
        checks.append(item)

    verified = [c["proves"] for c in rec["checks"] if c["passed"] is True]
    report = (f"ProofOps run {rec['run_id']} {rec['summary']['verdict'].lower()}: "
              + "; ".join(f"{c['id']} {_mark(c['passed']).lower()}" for c in rec["checks"])
              + ". Not verified: " + "; ".join(rec["does_not_prove"]))
    return json.dumps({
        "run_id": rec["run_id"],
        "verdict": rec["summary"]["verdict"],
        "summary": rec["summary"],
        "receipt": path,
        "target": rec["target"],
        "plan_revision": rec["plan_revision"],
        "checks": checks,
        "verified_claims": verified,
        "does_not_prove": rec["does_not_prove"],
        "report_line": report,
    }, indent=2)


def _receipt(args: dict, **_kw) -> str:
    """Re-print a stored receipt so a claim can be quoted from evidence, not memory."""
    ref = args.get("receipt")
    if not ref:
        return json.dumps({"error": "'receipt' (a run id or path) is required"})
    p = pathlib.Path(ref).expanduser()
    if not p.exists():
        p = _receipt_dir() / f"{ref}.json"
    if not p.exists():
        return json.dumps({"error": f"no receipt at {ref} or {p}"})
    rec = json.loads(p.read_text())
    return json.dumps({
        "run_id": rec["run_id"],
        "verdict": rec["summary"]["verdict"],
        "summary": rec["summary"],
        "plan": rec["plan"],
        "plan_revision": rec["plan_revision"],
        "checks": [{"id": c["id"], "result": _mark(c["passed"]), "proves": c["proves"]}
                   for c in rec["checks"]],
        "does_not_prove": rec["does_not_prove"],
        "summary_text": _sub("receipt").summarise(rec),
    }, indent=2)


_TOOLS = (
    ("proofops_plans", {
        "name": "proofops_plans",
        "description": ("List the verification plans available in a directory, with the "
                        "revision each is pinned to and the limitations each declares. Call "
                        "this before claiming a task is complete, to see whether an existing "
                        "plan covers the outcome."),
        "parameters": {
            "type": "object",
            "properties": {
                "plans_dir": {"type": "string",
                              "description": "Directory of plan JSON files (default: ./plans)."}
            },
            "additionalProperties": False,
        },
    }, _plans),
    ("proofops_run", {
        "name": "proofops_run",
        "description": ("Run one declared verification plan against a target and get a "
                        "receipt: each check's actual result, what it proves, and what the "
                        "receipt does NOT prove. Use it instead of asserting an outcome from "
                        "memory. Read-only for HTTP (GET only); a command check requires the "
                        "plan to declare it verbatim AND allow_commands=true."),
        "parameters": {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Path to the plan JSON file."},
                "target": {"type": "string",
                           "description": ("Origin (https://…, http://127.0.0.1:PORT) or "
                                           "'local' for command-only plans.")},
                "allow_commands": {"type": "boolean",
                                   "description": ("Permit command checks the plan declares in "
                                                   "allowed_commands. Default false: they come "
                                                   "back NOT RUN, never FAIL.")},
                "out": {"type": "string",
                        "description": "Receipt directory (default: $HERMES_HOME/proofops/receipts)."},
            },
            "required": ["plan", "target"],
            "additionalProperties": False,
        },
    }, _run),
    ("proofops_receipt", {
        "name": "proofops_receipt",
        "description": ("Read a stored receipt by run id or path. Quote its run id and its "
                        "does_not_prove list when reporting completion; never summarise it as "
                        "'everything works'."),
        "parameters": {
            "type": "object",
            "properties": {
                "receipt": {"type": "string", "description": "Run id (PO-…) or a file path."}
            },
            "required": ["receipt"],
            "additionalProperties": False,
        },
    }, _receipt),
)


def register(ctx) -> None:
    """Register the three tools and the skill the agent should read before saying 'done'."""
    for name, schema, handler in _TOOLS:
        ctx.register_tool(name=name, toolset="proofops", schema=schema, handler=handler,
                          emoji="🔎")
    if _SKILL.exists():
        ctx.register_skill(
            name="verify-before-done",
            path=_SKILL,
            description=("Run a ProofOps plan and quote the receipt before telling the user "
                         "something is complete."),
        )
