# ProofOps

**For a non-technical overview, read [`docs/EXECUTIVE-SUMMARY.md`](docs/EXECUTIVE-SUMMARY.md).**

**Agents say "done". ProofOps checks whether that is true.**

ProofOps runs a declared plan of read-only checks against a target and writes a
**receipt**: what was checked, what was actually observed, and — in every receipt — what
passing does *not* prove.

It exists because "the command succeeded" and "the outcome is correct" are different
claims, and only the second one matters.

```
ProofOps run PO-20261104T231903Z-ff6b fail:
  plan      claw-way-django deployment readiness (local fixture) (sha256:eb01b6d884f0b144)
  target    http://127.0.0.1:8099 [local-fixture]
  [PASS] health-reachable: the readiness endpoint answers 200
  [FAIL] health-reports-ok: the application itself reports status=ok
         observed: {"expected": "ok", "observed": "degraded", "http_status": 200, ...}
```

That failure is the whole point: **HTTP 200 with `status=degraded`**. A monitor that only
checks status codes calls that healthy.

## Install and run

No dependencies beyond the Python standard library.

```bash
python3 -m proofops list --plans plans
python3 -m proofops run plans/claw-way-deployment.json --target https://hub.sqs.chat
python3 -m proofops show receipts/PO-....json
```

Exit codes: `0` all checks passed · `1` a check failed · `2` the run could not be performed
(bad plan, a target the plan never declared, or a command the operator never authorised).
A caller that ignores the output can still trust the exit code.

## Use it as a Hermes plugin

The repository root is a loadable Hermes plugin (`plugin.yaml` + `__init__.py`): three
tools and one skill, no dependencies.

```bash
hermes plugins install https://github.com/<owner>/proofops   # or: cp -r . ~/.hermes/plugins/proofops
hermes plugins enable proofops
hermes plugins validate ~/.hermes/plugins/proofops           # the catalog CI gate
```

| tool | what it does |
|---|---|
| `proofops_plans` | list the plans available, with the revision and the limitations each declares |
| `proofops_run` | run one plan, return the receipt's substance and its `does_not_prove` list |
| `proofops_receipt` | re-print a stored receipt by run id |

The bundled `verify-before-done` skill tells the agent when to reach for them: before it
writes "done", "deployed", "fixed" or "everything works". The plugin adds no check types
and cannot repair anything — it only puts a receipt between the claim and the user.

`hermes plugins validate .` passes: manifest, `requires_hermes`, capability probe, declared
tools matching registrations, security scan, and no-core-override.

## Plans are data

```json
{
  "name": "claw-way-django deployment readiness",
  "target_kind": "production-readonly",
  "allowed_origins": ["https://hub.sqs.chat"],
  "checks": [
    { "id": "health-reports-ok", "type": "http_json_field",
      "path": "/health", "field": "status", "equals": "ok",
      "proves": "the application itself reports status=ok" }
  ],
  "does_not_prove": [
    "that the readiness check actually queries the database — the field is self-reported",
    "that migrations have run for this release",
    "that background workers are alive"
  ]
}
```

Supported check types: `http_status`, `http_json_field` (`equals` or `contains`),
`http_body_contains`, `http_header`.

Every check must state `proves`. Every plan must state `does_not_prove`. A plan missing
either is rejected — a green tick is not a claim of correctness.

## Two safety properties, enforced in code

1. **Origin allowlist.** A plan names every origin it may contact. Pointing a run at any
   other origin is refused *before* a request is made:

   ```
   refused: refusing to contact https://example.com: not in allowed_origins [...]
   ```

   Editing one flag cannot silently redirect a plan at production.

2. **Read-only by construction.** The only network verb implemented is `GET`. There is no
   path through this tool to POST, PUT, DELETE, or to run a shell command. Repair belongs
   to normal development tools; ProofOps only verifies.

## The receipt

Written to `receipts/<run-id>.json` and git-ignored — receipts describe a live
environment and do not belong in a public repository.

Each receipt records the plan revision (`sha256` of the plan body), so two receipts can be
proven to come from **the same** plan. That is what makes a before/after comparison
honest: weakening an assertion changes the revision.

```
run_id            PO-20261104T231903Z-ff6b
plan_revision     sha256:eb01b6d884f0b144
summary           3/4 passed, FAIL
checks[]          id, type, proves, passed, evidence{expected, observed, elapsed_ms}
does_not_prove[]  copied into every receipt
```

## What this does not do

- It does not repair anything, and does not claim to.
- It does not prove correctness of a claim the plan does not test. The `does_not_prove`
  list exists so a receipt can never be quoted as "everything works".
- It does not check authenticated flows, browser behaviour, or state-changing operations.
  Those need the project's own test suite; ProofOps can invoke a plan that records that
  gap, not close it.

## Worked example in this repo

`fixtures/readiness_server.py` is a throwaway stand-in for a readiness endpoint, so the
failure → repair → pass cycle runs without touching a real environment:

```bash
python3 fixtures/readiness_server.py 8099 &
python3 -m proofops run plans/claw-way-deployment.local.json --target http://127.0.0.1:8099
# inject: fixtures/state.json -> {"status": "degraded", ...}
# re-run: FAIL   (same plan revision)
# repair: restore {"status": "ok", ...}
# re-run: PASS   (same plan revision)
```

Three real receipts from that cycle:

| run | verdict | revision |
|---|---|---|
| `PO-20261104T231902Z-e374` | PASS 4/4 | `sha256:eb01b6d884f0b144` |
| `PO-20261104T231903Z-ff6b` | FAIL 3/4 | `sha256:eb01b6d884f0b144` |
| `PO-20261104T231908Z-1e3c` | PASS 4/4 | `sha256:eb01b6d884f0b144` |

Identical revisions: the plan was not weakened between runs.

## Status

Loadable Hermes plugin (3 tools + 1 bundled skill, `hermes plugins validate` clean) over a
stdlib-only engine: 5 plans, Plan loading, four check types, command checks fenced twice,
receipts, allowlist enforcement, CLI. 29 tests. Deliberately not built: authenticated HTTP
and browser flows, artifact/file assertions, plan composition, and any UI.

## Command checks — fenced twice

Some claims cannot be verified with a GET: "the migration graph builds a database",
"the deployed configuration validates". `command_exit` covers those, and is the only
place ProofOps can cause a side effect, so two independent gates must both open:

1. the plan lists the command **verbatim** in `allowed_commands`
2. the operator passes `--allow-commands`

Neither alone is enough. A plan copied from elsewhere executes nothing; a careless flag
cannot run what the plan never declared. There is no shell — argv is split with `shlex`,
so `&&`, pipes and redirection are not available to a plan.

```
refused: check 'django-check-exit' runs a command not listed in allowed_commands: 'ssh …'
refused: commands are disabled for this run (pass --allow-commands)
```

Identical commands run **once per plan run** and are cached, so two checks asserting
different things about a 90-second replay cost 90 seconds, not 180. The receipt records
`reused_from_cache: true` on the second check rather than hiding the reuse.

### A refusal is a third outcome, never a failure

If the plan declares the command but the operator did not pass `--allow-commands` (or the
plan never declared it), the check is recorded as **`NOT RUN`**, the receipt's verdict is
**`INCOMPLETE`**, and the CLI exits **2**.

This used to be a `FAIL`. That was a lie of exactly the kind this tool exists to catch: the
receipt read *"the deployed configuration failed validation"* for a command that was never
executed. A verification tool that manufactures false negatives is worse than none, because
someone will act on it. `tests/test_proofops.py` pins the behaviour.

### Two command plans, both executed

| plan | target | run | verdict |
|---|---|---|---|
| deployed configuration is valid | hub container | `PO-20261104T232221Z-67bf` | PASS 2/2 |
| builds from migrations (fresh DB) | test database | `PO-20261104T232710Z-8e21` | PASS 2/2 (1:29) |

The migration plan is the one worth watching: it drops and rebuilds the designated test
database from the migration graph and asserts production's history is untouched. It
replaced a suite that previously produced **241 errors**.
