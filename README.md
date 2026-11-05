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
python3 -m proofops run plans/claw-way-deployment.json --target https://app.example.com
python3 -m proofops verify receipts/PO-....json      # is this receipt still the one that was written?
python3 -m proofops show receipts/PO-....json
```

Exit codes: `0` all checks passed · `1` a check failed · `2` the run could not be performed
(bad plan, a target the plan never declared, or a command the operator never authorised).
A caller that ignores the output can still trust the exit code.

## Use it as a Hermes plugin

The repository root is a loadable Hermes plugin (`plugin.yaml` + `__init__.py`): four
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
| `proofops_verify` | check a stored receipt against its seal: `valid`, `tampered`, `unsealed` or `needs-key` |

The plugin never reads a signing key: a signed receipt reports `needs-key` there by design, and
signing or keyed verification is a CLI operation where the operator holds the secret.

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
  "allowed_origins": ["https://app.example.com"],
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

Supported check types:

| family | types |
|---|---|
| live service | `http_status`, `http_json_field` (`equals` or `contains`), `http_body_contains`, `http_header` |
| process | `command_exit` (fenced twice — see below) |
| deliverable | `file_exists`, `file_sha256`, `dir_manifest`, `csv_stats`, `image_size` |
| document | `pdf_pages`, `pdf_page_size`, `pdf_text_contains` |
| record | `sqlite_query` — read-only, single SELECT/WITH, against a database inside `allowed_paths` |

Deliverable checks answer the claims a demo never shows: the export that lost a file, the CSV
that parses and is short, the images that are the wrong size. They are fenced by
**`allowed_paths`**: a plan must name the directories it may read, paths are resolved through
symlinks and refused if they escape, and every read is bounded. Full-file hashing is capped at
256 MB per check.

A `command_exit` check may also carry `extract`, naming the value the receipt should show
rather than leaving the reader to re-run a 35-second command to find out how bad it is:

```json
"extract": [
  {"name": "drift_count", "regex": "schema drift: (\\d+)"},
  {"name": "tables_compared", "regex": "tables compared: (\\d+) \\(prod\\)"}
]
```

A pattern that does not match records `extract_error` and leaves the verdict alone:
extraction is evidence, never an assertion.

Every check must state `proves`. Every plan must state `does_not_prove`. A plan missing
either is rejected — a green tick is not a claim of correctness.

## Two safety properties, enforced in code

1. **Origin allowlist.** A plan names every origin it may contact. Pointing a run at any
   other origin is refused *before* a request is made:

   ```
   refused: refusing to contact https://example.com: not in allowed_origins [...]
   ```

   Editing one flag cannot silently redirect a plan at production.

2. **Read-only by construction.** The only network verb implemented is `GET`, and the only
   file verbs are reads. There is no path through this tool to POST, PUT, DELETE, or to write
   a file. Repair belongs to normal development tools; ProofOps only verifies.

3. **File reads are fenced by declared roots.** Deliverable checks may only read inside the
   directories the plan lists in `allowed_paths`; `..`, absolute paths and symlinks that
   resolve outside are refused before the file is opened.

## The receipt

Written to `receipts/<run-id>.json` and git-ignored — receipts describe a live
environment and do not belong in a public repository.

Each receipt records the plan revision (`sha256` of the plan body), so two receipts can be
proven to come from **the same** plan. That is what makes a before/after comparison
honest: weakening an assertion changes the revision.

Every receipt is **sealed**: a `sha256` digest of the whole body, so editing a verdict, an
observed value or a limitation after the fact is detectable. Supply a key
(`--key-file`, or `PROOPS_SIGNING_KEY`) and it is also signed (`hmac-sha256`), which is what
lets a second party prove *which* key produced it:

```bash
python3 -m proofops verify receipts/PO-....json           # valid / tampered / unsealed / needs-key
```

Verification exit codes: `0` valid · `1` edited, or signed by a different key · `2` cannot
verify (unsealed, or signed and no key supplied). What sealing does **not** prove is stated
by the verify command itself: that the checks were honest, that the plan was adequate, or
that the observer is truthful. It proves the file is unchanged — nothing more.

A receipt also names the inspector that produced it: `environment.commit` (the ProofOps
build), host, Python and working directory. A certificate without the inspector's identity
is not evidence.

## When nothing could be checked

The failure mode that matters most in practice is not a failing check — it is a check that
never ran, sitting in a mostly-green list. A refused command is the normal way this happens
(the operator did not pass `--allow-commands`), and it must not be summarised as a pass, nor
as a failure.

```
$ python3 -m proofops run plans/claw-way-deployed-config.json --target prod
...
  [NOT RUN] django-check-exit: the deployed container's settings and model graph validate
         reason: commands are disabled for this run (pass --allow-commands)

  INCOMPLETE - 2 of 2 checks could not be performed.
  NOTHING MAY BE CLAIMED from this receipt, including the checks that passed.
    not run: django-check-exit - ... validate without errors
             reason: commands are disabled for this run (pass --allow-commands)
```

The receipt carries `summary.claimable` (`true` only for a clean PASS), `summary.not_run_ids`,
and a top-level `not_verified` list of `{id, proves, reason}`. The Hermes tool returns the same
fields and a report line ending in `NOT CLAIMABLE: …`, so an agent has a machine-checkable
branch instead of prose to interpret. An unknown check type is refused when the plan loads —
a typo can never be recorded as either a pass or a failure.

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

## Reproduce the whole demonstration from a clean clone

Copy-paste, about 20 seconds, no dependencies. The defect is a one-line change to a
throwaway fixture — no service is touched.

```bash
python3 fixtures/readiness_server.py 8099 &          # disposable readiness endpoint

# 1. healthy — PASS 4/4
python3 -m proofops run plans/claw-way-deployment.local.json --target http://127.0.0.1:8099

# 2. inject the defect: the app reports "degraded" but still answers HTTP 200
sed -i 's/"status": "ok"/"status": "degraded"/' fixtures/state.json
python3 -m proofops run plans/claw-way-deployment.local.json --target http://127.0.0.1:8099
#    -> FAIL 3/4, observed {"expected": "ok", "observed": "degraded", "http_status": 200}

# 3. repair with ordinary tools (ProofOps repairs nothing), re-run the SAME plan
sed -i 's/"status": "degraded"/"status": "ok"/' fixtures/state.json
python3 -m proofops run plans/claw-way-deployment.local.json --target http://127.0.0.1:8099
#    -> PASS 4/4, identical plan revision
```

The plan revision in all three receipts is `sha256:eb01b6d884f0b144` — that is what proves
the test was not loosened to get the green.

## Three real receipts from that cycle

| run | verdict | revision |
|---|---|---|
| `PO-20261104T231902Z-e374` | PASS 4/4 | `sha256:eb01b6d884f0b144` |
| `PO-20261104T231903Z-ff6b` | FAIL 3/4 | `sha256:eb01b6d884f0b144` |
| `PO-20261104T231908Z-1e3c` | PASS 4/4 | `sha256:eb01b6d884f0b144` |

Identical revisions: the plan was not weakened between runs.

## Status

Loadable Hermes plugin (4 tools + 1 bundled skill, `hermes plugins validate` clean) over a
stdlib-only engine: 5 plans, plan loading, fourteen check types, command checks fenced twice,
path-fenced deliverable, document and process checks, sealed and optionally signed receipts,
allowlist enforcement, CLI, and a defect-injection benchmark. 95 tests. Deliberately not built: authenticated HTTP
and browser flows, plan composition, and any UI.

## What does it actually catch? (`bench/run_bench.py`)

A verifier's honest question about itself is not "do my checks pass" but "what is my detection
rate, and what do I flag when nothing is wrong". The benchmark answers both against a corpus
whose ground truth is known by construction: a real public CSV (194 countries, 194 rows), a
deterministic image export, a two-page PDF and a seeded SQLite system of record, with **18
defects injected one at a time** and **4 benign changes** applied to a clean copy.

```
  plan              defects caught   benign changes flagged
  narrow                 3/18                0/4
  structural            12/18                0/4
  strict                13/18                3/4
  documents              3/18                0/4     (the 3 PDF defects)
  records                2/18                0/4     (both "the message landed" defects)
```

The point is the trade-off, not a winner:

* **narrow** (row count only) catches a dropped row, a duplicated row, an emptied file — and
  misses a blanked cell, a truncated line, a renamed header, a missing image, a wrong
  dimension. This is what most "the export looks fine" checks actually assert.
* **structural** (rows + header + per-column nulls + export inventory + image dimensions)
  catches 12 of 16, with no false alarms. It still misses an image whose pixels changed but
  whose size did not — structure is not content — and it asserts nothing at all about the PDF.
* **documents** (page count, page size, text landmarks) catches all three PDF defects with no
  false alarms. It says nothing about the CSV: a plan is only as wide as the claims it makes.
* **records** (read the system of record) catches both database defects — a message row that
  was never written, and one written but never marked sent — and ignores an unrelated message
  added to the same table. This is the check a "sent" claim needs, because a status code cannot
  see a missing row.
* **strict** (byte-exact checksums) catches everything, and also flags a file that was merely
  re-saved with CRLF endings, reordered rows, or given a trailing newline. Exactness is a
  choice about what you are promising, not a higher grade of verification.

Run it with `python3 bench/run_bench.py` (add `--offline` to reuse the cached corpus). It exits
non-zero if the strict plan misses a defect, if the structural plan raises a false alarm, or
if a clean corpus is flagged.

The benchmark has already caught two defects in this tool: `csv_stats` counted a trailing blank
line as a data row (false alarm), and the benchmark's own first version split CSV rows on
commas, which mangled quoted fields and let a row-count plan claim a catch it had not made.

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
