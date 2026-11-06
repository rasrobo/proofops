# ProofOps

**Agents say "done". ProofOps checks whether that is true.**

It runs a declared plan of read-only checks against a system or a deliverable and writes a
**receipt**: every check's actual result, what that result proves, and — printed on every
receipt — what passing does *not* prove.

It exists because "the command succeeded" and "the outcome is correct" are different claims,
and only the second one is worth acting on.

```
ProofOps run PO-20261104T231903Z-ff6b fail:
  plan      claw-way-django deployment readiness (sha256:eb01b6d884f0b144)
  [PASS] health-reachable: the readiness endpoint answers 200
  [FAIL] health-reports-ok: the application itself reports status=ok
         observed: {"expected": "ok", "observed": "degraded", "http_status": 200, ...}
```

That failure is the product in one line: **HTTP 200 with `status=degraded`**. Every uptime
monitor on earth calls that healthy. The deploy was not fine, and nothing said so.

---

## What you actually get

Three things, each of which you can hand to somebody else:

**A claim you can send.** Not "I checked" — a file with the values that were observed, the
commands that produced them, the machine it ran on, and a hash over the whole thing. Attach it
to a deploy, an invoice, a client email, a handover.

**A gap you can see.** Checks that could not be performed are named at the top, not buried in a
mostly-green list. The receipt then carries `claimable: false`, so an agent cannot quote the
green part and skip the rest.

**Proof the goalposts did not move.** Every receipt records the plan revision — a sha256 of the
checks themselves. Weakening an assertion to get a pass changes that revision, so a before/after
comparison cannot be faked by editing the test.

What it does not do is make your work correct. It makes your claim **auditable**.

## When you would reach for it

The same shape every time: something reported success, and the thing that matters is one layer
below the report.

| the claim | what a status code sees | what ProofOps sees |
|---|---|---|
| "the deploy is healthy" | HTTP 200 | the app reports `status=degraded` |
| "the export shipped" | the file exists | 194 rows, 2 columns, 0 nulls — or 193 rows |
| "the report went out" | the PDF was written | 2 pages, page 1 contains "Invoice" — or 1 page |
| "the digest was sent" | `sentMessageId: 143` | no row in the message store |
| "the rebuild is identical" | no errors | 181/181 tables match, 39 structural drifts |
| "the tests pass" | exit 0 | 2 of 3 shards green, 1 never ran |

## 60 seconds, on your own files

```bash
python3 -m proofops new --dir ~/exports            # writes ~/exports/proofops-plan.json
python3 -m proofops run ~/exports/proofops-plan.json --target local
python3 -m proofops verify receipts/PO-….json      # is the receipt still the one that was written?
```

`new` inspects what is actually in the directory — CSV row/column/null counts, image dimensions,
PDF page counts, SQLite table counts, a directory inventory with per-file hashes — and writes a
plan asserting **the shape it has right now**. It reads only, executes nothing, and the plan is
plain JSON you can edit. Remove one row afterwards and the same plan fails.

[`docs/PLANS.md`](docs/PLANS.md) has copy-paste recipes when you want a plan the generator would
not write for you.

## Install

No dependencies beyond the Python standard library.

```bash
python3 -m proofops list --plans plans
python3 -m proofops run plans/claw-way-deployment.json --target https://app.example.com
python3 -m proofops verify receipts/PO-....json
python3 -m proofops show receipts/PO-....json
```

Exit codes are a contract: `0` all checks passed · `1` a check failed · `2` the run could not be
performed (bad plan, an origin the plan never declared, a command the operator never authorised).
A caller that ignores every line of output can still trust the exit code.

### As a Hermes plugin

The repository root is a loadable plugin (`plugin.yaml` + `__init__.py`): four tools and one
skill, still no dependencies.

```bash
hermes plugins install https://github.com/rasrobo/proofops
hermes plugins enable proofops
# non-interactive (SSH, CI) needs --yes-deps, or the install is refused
```

| tool | what it does |
|---|---|
| `proofops_plans` | list the plans available, with each plan's revision and declared limitations |
| `proofops_run` | run one plan, return the receipt's substance and its `does_not_prove` list |
| `proofops_receipt` | re-print a stored receipt by run id |
| `proofops_verify` | check a receipt against its seal: `valid`, `tampered`, `unsealed` or `needs-key` |

The bundled `verify-before-done` skill tells the agent when to reach for them: before it writes
"done", "deployed", "fixed" or "everything works". The plugin adds no check types and repairs
nothing — it only puts a receipt between the claim and the user.

The plugin never reads a signing key. A signed receipt reports `needs-key` there by design;
signing and keyed verification are CLI operations, where the operator holds the secret.

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

| family | types |
|---|---|
| live service | `http_status`, `http_json_field` (`equals` or `contains`), `http_body_contains`, `http_header` |
| process | `command_exit` (fenced twice — see below) |
| deliverable | `file_exists`, `file_sha256`, `dir_manifest`, `csv_stats`, `image_size` |
| document | `pdf_pages`, `pdf_page_size`, `pdf_text_contains` |
| record | `sqlite_query` — read-only, single SELECT/WITH, inside `allowed_paths` |

Every check must state `proves`. Every plan must state `does_not_prove`. A plan missing either is
rejected at load — a green tick is never a claim of correctness.

Deliverable checks answer what a demo never shows: the export that lost a file, the CSV that
parses and is short, the images at the wrong size. They are fenced by **`allowed_paths`**: a plan
names the directories it may read, paths are resolved through symlinks and refused if they escape,
and every read is bounded (full-file hashing is capped at 256 MB per check).

### Side effects need two keys

`command_exit` is the only place ProofOps can cause a side effect, so two independent gates must
open: the plan lists the command **verbatim** in `allowed_commands`, *and* the operator passes
`--allow-commands`. Neither alone is enough — a plan copied from elsewhere executes nothing, and a
careless flag cannot run what the plan never declared. There is no shell; argv is split with
`shlex`, so `&&`, pipes and redirection are unavailable to a plan.

Identical commands run once per run and are cached, with `reused_from_cache: true` recorded rather
than hidden — two checks about a 90-second replay cost 90 seconds, not 180.

### A refusal is a third outcome, never a failure

The failure mode that matters is not a failing check — it is a check that never ran, sitting in a
mostly-green list.

```
  [NOT RUN] django-check-exit: the deployed container's settings validate
         reason: commands are disabled for this run (pass --allow-commands)

  INCOMPLETE - 2 of 2 checks could not be performed.
  NOTHING MAY BE CLAIMED from this receipt, including the checks that passed.
```

The receipt carries `summary.claimable` (true only for a clean PASS), `summary.not_run_ids`, and a
top-level `not_verified` list of `{id, proves, reason}`. The Hermes tool returns the same fields,
so an agent has a machine-checkable branch instead of prose to interpret. An unknown check type is
refused when the plan loads — a typo can never be recorded as a pass or a failure.

This used to be a `FAIL`, which was a lie of exactly the kind the tool exists to catch: the
receipt read *"the deployed configuration failed validation"* for a command that never executed.
A verifier that manufactures false negatives is worse than none, because somebody acts on it.

## The receipt

Written to `receipts/<run-id>.json` (git-ignored: receipts describe a live environment).

```
run_id            PO-20261104T231903Z-ff6b
plan_revision     sha256:eb01b6d884f0b144
summary           3/4 passed, FAIL
checks[]          id, type, proves, passed, evidence{expected, observed, elapsed_ms}
does_not_prove[]  copied into every receipt
```

Every receipt is **sealed** with a sha256 over the whole body, so editing a verdict, an observed
value or a limitation afterwards is detectable. Supply a key (`--key-file` or
`PROOPS_SIGNING_KEY`) and it is also signed with HMAC-SHA256, which lets a second party prove
*which* key produced it.

```bash
python3 -m proofops verify receipts/PO-....json     # valid / tampered / unsealed / needs-key
```

`0` valid · `1` edited or signed by a different key · `2` cannot verify. Sealing proves the file
is unchanged — not that the checks were honest, that the plan was adequate, or that the observer
is truthful. The command says so itself every time it runs.

A receipt also names its inspector: `environment.commit` (the ProofOps build), host, Python and
working directory. A certificate with no identity behind it is not evidence.

## What it does not do

- It does not repair anything, and does not claim to.
- It does not prove a claim the plan never tests. The `does_not_prove` list exists so a receipt
  can never be quoted as "everything works".
- It does not cover authenticated flows, browser behaviour or state-changing operations. Those
  need the project's own tests; ProofOps can record that gap, not close it.
- It cannot read scanned PDFs or CID fonts without ToUnicode, and says so instead of guessing.

## How good is it? Measured, including where it fails

A verifier's honest question about itself is not "do my checks pass" but "what is my detection
rate, and what do I flag when nothing is wrong". `bench/run_bench.py` answers both against a
corpus whose ground truth is known by construction: **two independently published CSVs** (194
countries; 891 passengers with 177/687/2 real nulls), a deterministic image export, a two-page PDF
and a seeded SQLite system of record — **22 defects injected one at a time**, **5 benign changes**
applied to a clean copy.

```
  plan              defects caught   benign changes flagged
  narrow                 3/22                0/5    row count only
  structural            12/22                0/5    rows + header + nulls + inventory + dimensions
  strict                13/22                3/5    byte-exact checksums
  documents              3/22                0/5    page count, page size, text landmarks
  records                2/22                0/5    is the message actually in the database
  passengers             4/22                0/5    second dataset's shape and real nulls
```

The point is the trade-off, not a winner:

- **narrow** catches a dropped row, a duplicate, an emptied file — and misses a blanked cell, a
  truncated line, a renamed header, a missing image. This is what most "the export looks fine"
  checks actually assert.
- **structural** catches 12 of 22 with no false alarms, and still misses an image whose pixels
  changed but whose size did not: structure is not content.
- **strict** catches everything and also flags files that were merely re-saved with CRLF endings,
  reordered, or given a trailing newline. Exactness is a choice about what you promise, not a
  higher grade of verification.
- **documents** and **records** each catch every defect in their own domain and nothing outside
  it. A plan is only as wide as the claims it makes.

Run it with `python3 bench/run_bench.py` (`--offline` reuses the cached corpus). It exits
non-zero if the strict plan misses a defect, if the structural plan raises a false alarm, or if a
clean corpus is flagged.

The benchmark has already caught three defects in this tool: `csv_stats` counted a trailing blank
line as a data row; the first benchmark split CSV rows on commas, mangling quoted fields and
letting a row-count plan claim a catch it had not made; and CI found a verdict that depended on
the SQLite library version, where `select 1` against a non-database file passed on one build and
failed on another. Each is fixed and pinned by a test.

## Reproduce the whole demonstration

Copy-paste, about 20 seconds, no dependencies. The defect is a one-line change to a throwaway
fixture — no service is touched.

```bash
python3 fixtures/readiness_server.py 8099 &          # disposable readiness endpoint

python3 -m proofops run plans/claw-way-deployment.local.json --target http://127.0.0.1:8099
#   -> PASS 4/4

sed -i 's/"status": "ok"/"status": "degraded"/' fixtures/state.json
python3 -m proofops run plans/claw-way-deployment.local.json --target http://127.0.0.1:8099
#   -> FAIL 3/4, observed {"expected": "ok", "observed": "degraded", "http_status": 200}

sed -i 's/"status": "degraded"/"status": "ok"/' fixtures/state.json
python3 -m proofops run plans/claw-way-deployment.local.json --target http://127.0.0.1:8099
#   -> PASS 4/4
```

All three receipts carry plan revision `sha256:eb01b6d884f0b144`. Identical revisions are what
prove the plan was not loosened to get the green.

## Status

Version 0.3.3. Loadable Hermes plugin (4 tools + 1 bundled skill, `hermes plugins validate`
clean) over a stdlib-only engine: 5 shipped plans, plan loading, fourteen check types, command
checks fenced twice, path-fenced deliverable/document/process checks, sealed and optionally
signed receipts, origin allowlists, a CLI, and an injected-defect benchmark. **116 tests**, CI
green on every push (tests, benchmark, end-to-end demonstration, seal check).

Deliberately not built: authenticated HTTP, browser journeys, plan composition, and any UI.
