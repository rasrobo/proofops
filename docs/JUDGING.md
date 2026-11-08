# Judge's map — claim → evidence → the link to open

A judge with four days of entries and ten minutes should not have to read a 400-line README to score
this. Every row below is a claim, the artefact that proves it, and one link. Nothing here is a
promise about the future.

## 0. Open these three, in order

| | |
|---|---|
| **See it work, 20 s** | `pipx install git+https://github.com/rasrobo/proofops && proofops demo` — no config, no network |
| **Watch it, 74 s** | https://youtu.be/3ee1VbHZpXo |
| **Read the numbers, incl. failures** | https://rasrobo.github.io/proofops/metrics/ |

## 1. Usefulness — does it fix a failure that costs days?

| Claim | Evidence | Link |
|---|---|---|
| It catches the case status codes miss: a 200 that reports the wrong state | The demo's first two lines: `[PASS] reachable` then `[FAIL] says-ok` with `observed: "degraded"` | `proofops demo` |
| It caught a real one, in its own product | A `select 1` check passed on CI and failed locally — SQLite never reads a page, so the file was never validated. Fixed at the source with `PRAGMA schema_version`, with a positive test so the fix cannot be "fail everything" | `git log --grep="schema_version"` |
| It scales from a service to a deliverable | 14 check types across HTTP, files, checksums, CSV, images, PDF and read-only SQLite | `docs/PLANS.md` |
| The output is quotable | A receipt is a JSON file with the observed value for every check, a plan revision and a seal | `docs/EXECUTIVE-SUMMARY.md` |

## 2. Reliability — would you trust the verdict?

| Claim | Evidence | Link |
|---|---|---|
| 140 tests, and they assert absence, not just happy paths | e.g. the socket is unreachable without consent; the payload cannot carry a hostname; a refused prompt is never re-asked | `tests/` |
| The benchmark publishes its own misses | 22 injected defects over two public datasets, 5 benign changes, 6 plan strengths. Best strict plan: 13/22 caught **and 3 false alarms declared** | `bench/latest.json` |
| A third outcome exists | `NOT RUN` is reported as `NOT RUN`, never a green tick; exit code 2 means nothing was tested | `proofops/receipt.py` |
| Editing a receipt is detectable | The demo flips a failed check to passed and `verify` reports `tampered` | `proofops demo` |
| Weakening a plan is visible | Any edit changes `plan_revision` (sha256 of the plan body) | `proofops/plan.py` |
| CI runs the whole thing on every push | tests, benchmark, end-to-end demo, seal check | Actions badge in the README |

## 3. Polish — is it a product or a script?

| Claim | Evidence | Link |
|---|---|---|
| Exit codes are a contract | 0 pass / 1 any failure / 2 could-not-run | `proofops/cli.py` |
| Every receipt states its own limits | `does_not_prove` is printed, not buried | any receipt |
| Installing is one command and it works offline | `pip install` → `proofops demo` (the package version now comes from the code, not a stale literal) | `pyproject.toml` |
| It respects the operator | diagnostics are opt-in, asked once, `Enter` means no, and the exact bytes are printable before anything is sent | `docs/METRICS.md` |
| The public numbers include the failures | 12 failed checks are on the page next to the 120 passes | the dashboard |

## 4. What this deliberately does not do

- It does not decide whether a *person* is honest: a receipt proves what was observed, and says so.
- It does not replace monitoring: a pass is a claim checked, not a defect avoided.
- It does not phone home: no telemetry unless the operator ticks the box, and `proofops share
  --dry-run` prints the entire payload first.

These limits are on every receipt and on the dashboard, because a verifier that overstates itself is
the exact thing this project exists to catch.
