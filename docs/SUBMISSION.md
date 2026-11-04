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
| the tool's own tests | **done — 26 tests** |
| receipts self-contained | done — plan body embedded |
| project-local integration (`proofops/` in the target repo, AGENTS.md note) | **not done** |
| authenticated / browser flows | **not attempted** — deliberately, see limitations |
| UI | none |

The weakest part of this submission is coverage breadth: four plans, all about one
project, and none touching authentication, billing or provisioning — the workflows where a
premature "done" would cost the most. The strongest part is that every claim above has a
receipt behind it, and one of those receipts contradicts an earlier claim of mine.
