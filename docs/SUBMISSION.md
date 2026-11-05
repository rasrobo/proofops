# Submission notes

What was built, what was actually executed, and what is honestly missing.

## 1. Projects inspected

| project | path | shape | verification coverage before |
|---|---|---|---|
| **claw-way-django** | hub `/home/beeze/claw-way-django` | Django + Docker SaaS: provisioning, auth, billing, monitoring, jobs | 241 tests; real `/health` |
| founder-portal | hub `/home/beeze/founder-portal-deploy` | Node, static pages | none |
| flipwright | local `bec8c56` | no compose, 1 test | effectively none |
| docuvibe | local `5659aa9` | no compose, 0 tests | none |
| master-loop | local | not a git repo | n/a |

## 2. Selected: claw-way-django — "the deployment is ready"

The only project with all four properties the brief requires: a real readiness endpoint
whose fields can be asserted, deterministic acceptance criteria, a safe local
reproduction, and no production dependency.

## 3. Coverage matrix

| workflow | completion claim | actual check | evidence | important limitations |
|---|---|---|---|---|
| deployment readiness | "the app is deployed and ready" | `/health` 200; `status == "ok"`; `backend == "django"`; `database == "postgresql"` | status, parsed field values, elapsed ms | the fields are **self-reported**; cannot show migrations ran, workers alive, or that the image matches a revision |
| deployed configuration | "the release is fine" | `manage.py check` inside the container exits 0 **and** prints "System check identified no issues" | exit code, stdout tail | a valid config can still sit behind a dead proxy |
| migration replay | "a fresh database can be built" | rebuild the test DB from the graph; assert production history untouched | exit code, `prod legacy rows: 0` | compares table **count** only — see drift below |
| schema fidelity | "the rebuild matches production" | structural diff of columns, indexes, constraints | per-table differences, `schema drift: N` | structure only, not data or behaviour; **currently FAILS with 39 drifts** |
| deliverable inventory | "the export contains what we shipped" | directory listing (names, sizes, optional per-file sha256) against a pinned digest | file count, total bytes, listing digest, mismatches | names and bytes only; says nothing about whether an image is *correct*, only whether it is unchanged |
| tabular deliverable | "the data loaded, all rows, no gaps" | row count, header equality, per-column null counts | observed rows/columns/nulls/blank_rows, per-field mismatches | CSV shape only; does not validate types, ranges or referential integrity |
| image dimensions | "the images are the size the client ordered" | PNG/GIF/JPEG header parse (no decode) | format and observed dimensions | dimensions only; not colour space, DPI metadata or visual content |
| defect detection rate | "the checks work" | 13 injected defects + 3 benign changes in `bench/run_bench.py` | caught/flagged per plan strength | measure is about these defect classes; a defect class not injected is not measured |

## 4. Executed runs (real receipts)

| receipt | plan | verdict |
|---|---|---|
| `PO-20261104T231847Z-6a1a` | deployment readiness (production) | PASS 4/4 |
| `PO-20261104T231902Z-e374` | fixture baseline | PASS 4/4 |
| `PO-20261104T231903Z-ff6b` | fixture with injected defect | **FAIL 3/4** |
| `PO-20261104T231908Z-1e3c` | fixture repaired | PASS 4/4 |
| `PO-20261104T232221Z-67bf` | deployed configuration | PASS 2/2 |
| `PO-20261104T232528Z-1586` | migration replay | PASS 2/2 |
| `PO-20261104T232710Z-8e21` | migration replay (cache) | PASS 2/2, 1:29 |
| `PO-20261105T164330Z-2f2a` | deployment readiness (production, re-run) | PASS 4/4 |
| `PO-20261105T164355Z-2408` | deployed configuration (re-run) | PASS 2/2 |
| `PO-20261105T164431Z-f391` | schema drift (before `extract`) | FAIL 0/1 |
| `PO-20261105T164715Z-b6b4` | schema drift (with `extract`) | FAIL 0/1 — `drift_count=39`, `tables_compared=181` |
| `PO-20261105T164723Z-b71b` | readiness, sealed, verified | PASS 4/4 |
| `PO-20261105T164728Z-5139` | readiness, signed (HMAC) | PASS 4/4 |
| `PO-20261105T164337Z-287c` / `...f286` / `...ee0d` | demo: defect → repaired | FAIL 3/4 → PASS 4/4 → PASS 4/4, one revision |
| `PO-20261105T165107Z-c882` | migration replay (re-run, sealed) | PASS 2/2 |

Note on revisions: `claw-way-schema-drift.json` moved from `sha256:36f14d2bb9c4fd50` to
`sha256:f4bca58123c4bf7a` because an `extract` block was **added** (evidence, not an
assertion). The assertion `stdout_contains: "schema drift: 0"` is byte-identical in both, so
the FAIL is not a weakened comparison — but the two revisions must not be quoted as
equivalent, and they are not.

## 5. Failure → repair → pass

One plan revision throughout (`sha256:eb01b6d884f0b144`), so the comparison is
equivalent by construction:

- **Baseline** `e374` — PASS
- **Defect** — readiness reported `degraded`; the endpoint still returned **200**
- **Failure** `ff6b` — FAIL 3/4, evidence records `expected "ok"`, `observed "degraded"`, `http_status 200`
- **Repair** — restore the value with normal tools; ProofOps repaired nothing
- **Pass** `1e3c` — PASS 4/4, same revision

## 6. The finding that matters most

The migration plan originally asserted `count(*) from pg_tables`. Adding a structural
comparison showed **39 differences across 181 matching tables**:

```
app_audit_events.id        integer  -> bigint
app_jobs.created_at        nullable -> NOT NULL, default now() lost
claw_configs.created_at    NOT NULL -> nullable
affiliate_applications.approved     default false dropped
```

The rebuilt database has the right table *names* and the wrong *schema*. That is exactly
the failure mode ProofOps exists to catch, and it was caught by ProofOps rather than by
trusting the earlier green result. `plans/claw-way-schema-drift.json` is kept **failing
on purpose** as the evidence.

## 7. Demo outline (~80 s, sanitized)

1. `proofops list` — plan + revision (5 s)
2. Run against the fixture — PASS (10 s)
3. Set one value to `degraded`; re-run — **200 OK, FAIL** (20 s)
4. Restore; re-run — PASS, same revision (10 s)
5. `proofops show` the failing receipt; read `does_not_prove` aloud (20 s)
6. Close: "ProofOps never repaired anything. It proved the repair." (5 s)

No customer data, no internal hostnames in the frame: a localhost fixture and one public
readiness document.

## 8. Next two applications

1. **Provisioning verification** — a throwaway instance must answer, identify itself as
   the intended tenant, and carry expected non-secret config. Medium effort; still cannot
   prove tenant isolation, billing or TLS.
2. **Triage the 39 schema drifts** — classify acceptable (constraint naming) from
   defective (`bigint`/`integer`, lost `NOT NULL`, lost defaults), then make the drift
   plan pass for the right reason.

## 9. Honest assessment

| brief requirement | state |
|---|---|
| discovery from real code | done |
| plans as data, reusable | done (5 plans) |
| real failure → repair → pass, same revision | done |
| gates that cannot be bypassed | done, counter-tested |
| limitations stated per plan | done, enforced at load |
| the tool's own tests | **done — 69 tests** |
| published detection + false-alarm rates | **done — 3/13 · 12/13 · 13/13 by plan strength; 0 false alarms for structural, 3 for strict** |
| receipts cannot be edited undetected | **done — sealed sha256, optional HMAC, `verify` exits 0/1/2** |
| receipts self-contained | done — plan body embedded |
| project-local integration (`proofops/` in the target repo, AGENTS.md note) | **not done** |
| authenticated / browser flows | **not attempted** — deliberately, see limitations |
| UI | none |

The weakest part of this submission is coverage breadth: four plans, all about one
project, and none touching authentication, billing or provisioning — the workflows where a
premature "done" would cost the most. The strongest part is that every claim above has a
receipt behind it, and one of those receipts contradicts an earlier claim of mine.

## 10. Plugin packaging

The hackathon is a *plugin* hackathon, so the repository root is now a loadable Hermes
plugin: `plugin.yaml` + `__init__.py`, no dependencies, four tools and one bundled skill.

| tool | purpose |
|---|---|
| `proofops_plans` | list the plans available, with revision and declared limitations |
| `proofops_run` | run one plan; return the receipt's substance and `does_not_prove` |
| `proofops_receipt` | re-print a stored receipt by run id |
| `proofops_verify` | check a receipt against its seal (valid / tampered / unsealed / needs-key) |

`skills/verify-before-done/SKILL.md` is registered with `ctx.register_skill`, so the agent
is told to reach for a plan before it writes "done", "deployed", "fixed" or "everything
works". The plugin adds no check types, cannot repair anything, and cannot widen a plan's
allowlist.

Verified by the catalog CI gate, run locally:

```
✓ manifest · requires_hermes · capability probe · declared tools match registrations
✓ security scan — safe · no core override · built-in tool collisions — none
Validation passed.
```

and by exercising the registered tools inside a real Hermes container: 5 plans listed, a
fixture run `PASS 4/4`, a command plan without `allow_commands` correctly returning
`INCOMPLETE` with both checks `NOT RUN`, and receipt lookup by run id.

### The claim that was not true until 2026-11-05

The executive summary described the product as handing over "a signed record". It did not:
receipts were plain JSON, and an agent that wanted a green result could edit the verdict
after the run and nothing would notice — the precise failure the tool exists to catch,
committed by the tool itself, in its own marketing copy.

Receipts are now sealed with a sha256 digest of the whole body (plan body, evidence,
`does_not_prove` list included), optionally HMAC-SHA256 signed, and `proofops verify` is a
first-class command and plugin tool. Counter-tested: editing `summary.verdict` in a written
receipt returns `tampered` with both digests, exit 1; stripping the block returns `unsealed`;
a signed receipt without the key returns `needs-key`, exit 2. The verify output states what
sealing does not prove, because "sealed" is a weaker claim than "true".

The same run found a second defect: a failing command check reported `exit 1` and a
truncated output tail, so the schema-drift receipt said FAIL without saying **39**. Checks
may now declare `extract` patterns, and that receipt reads `drift_count=39,
tables_compared=181`.

### The defect this packaging exposed

A refused command used to be written into the receipt as `FAIL` with exit 1 — the receipt
claimed the deployed configuration failed validation when nothing had run. It is now a third
outcome: `NOT RUN`, verdict `INCOMPLETE`, exit 2. Caught by running the tool against itself,
which is the only honest way to test a verifier.

Still missing for submission: the sanitised public mirror, the recorded demo, and the
project-local integration in `claw-way-django`.

## 11. Project-local integration

`claw-way-django` (the live SaaS this was built against) now carries `proofops/` — two plans,
a README, and one `AGENTS.md` instruction. Receipts are written to `proofops/receipts/`,
which is git-ignored.

| plan | the claim it answers | today's run |
|---|---|---|
| `deployment-readiness.json` | "the deploy is live" | `PO-20261105T011634Z-02ef` — **PASS 4/4** |
| `auth-endpoint-suite.json` | "authentication is fixed" | `PO-20261105T012615Z-ab8b` — **FAIL 6/241** |

The second one is the reason this tool exists. It ran the project's own endpoint and
authentication suite inside the deployed container: **235 passed, 6 failed in 9m22s**. One
cause is proven rather than guessed — the suite expects an SSH hop to
`claw.token.sqs.chat`, a name with no DNS record, so the view logs
`Could not resolve hostname` and the redirect carries no token fragment. The other five need
triage (tracked in that repository's #488).

An agent asked to report on that work would have said "authentication is fixed". The plan
returned six failing assertions and the observed values instead.

Neither plan can be quietly turned green: `deployment-readiness` needs the application to
report `status=ok`, and `auth-endpoint-suite` needs the suite's own exit code *and* the word
`passed` in its output — an exit 0 with nothing collected fails.

The one thing this integration does **not** prove is that a real user can log in: the suite
drives Django's test client, not a browser. That limitation is printed on every receipt.
