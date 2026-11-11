# proofops held-out eval — 20 cases

Twenty fresh (plan, fixture) pairs proofops was not tuned against: 10 true
claims that should PASS, 10 false claims that should FAIL. Fixtures are all
generated locally (CSV / PNG / PDF / SQLite / a loopback HTTP server), so the
run is deterministic and offline-safe. Run with `python3 bench/run_eval.py`; the
full per-case results are in `bench/eval-latest.json`.

Generated 2026-11-11T14:56:51+00:00 · proofops 0.5.0 · script 72bdbdba17731039

## Results

- **Precision 1.000** (10 true passes / 10 passes returned)
- **Recall 1.000** (10 true passes / 10 true claims)
- **Accuracy 1.000** (20 / 20 verdicts match ground truth)
- TP 10 · FP 0 · FN 0 · TN 10

## Cases

| case | claim | expected | actual | what it proves |
|------|-------|----------|--------|----------------|
| E01 | the service is up and reports status ok | PASS | PASS ✓ | a 200 plus a healthy status field together mean 'up', not just 'reachable' |
| E02 | the readiness page says all systems nominal | PASS | PASS ✓ | the body carries the expected readiness string |
| E03 | the service reports version 1.2.3 | PASS | PASS ✓ | the response header carries the expected version |
| E04 | the release artifact exists with the expected SHA-256 | PASS | PASS ✓ | existence plus exact bytes pins the artifact, not just its name |
| E05 | the roster CSV has 6 rows, the expected header and null counts | PASS | PASS ✓ | row count, header and per-column nulls match the source |
| E06 | the export directory holds 4 files with the expected listing | PASS | PASS ✓ | file count plus the listing digest pins the whole export |
| E07 | the thumbnail is 320x240 | PASS | PASS ✓ | the image dimensions are the expected ones |
| E08 | the report is 3 A4 pages and carries its landmark heading | PASS | PASS ✓ | page count, page size and the landmark string together describe the document |
| E09 | message 143 is recorded as sent | PASS | PASS ✓ | the system of record holds the claimed row with sent=1 |
| E10 | the smoke-test command exits 0 | PASS | PASS ✓ | a declared command, run with operator approval, exits cleanly |
| E11 | the service is up and reports status ok (it reports degraded) | FAIL | FAIL ✓ | a 200 with a degraded status field must not pass as healthy |
| E12 | the endpoint answers 200 (it answers 404) | FAIL | FAIL ✓ | a missing endpoint must not pass a 200 assertion |
| E13 | the release artifact exists with the expected SHA-256 (bytes differ) | FAIL | FAIL ✓ | a changed artifact must fail its hash assertion even though it exists |
| E14 | the roster CSV has 6 rows (it has 5) | FAIL | FAIL ✓ | a CSV short by one row must fail its row-count assertion |
| E15 | the export directory holds 4 files (one is missing) | FAIL | FAIL ✓ | a manifest missing a file must fail on count and on the listing digest |
| E16 | the thumbnail is 320x240 (it is 640x480) | FAIL | FAIL ✓ | an image with the wrong dimensions must fail its size assertion |
| E17 | the report is 3 A4 pages (it has 2) | FAIL | FAIL ✓ | a report with fewer pages must fail its page-count assertion |
| E18 | the report carries its landmark heading (it does not) | FAIL | FAIL ✓ | a report missing its landmark text must fail its text assertion |
| E19 | message 143 is recorded as sent (no such row) | FAIL | FAIL ✓ | a message id with no row in the system of record must not pass |
| E20 | the smoke-test command exits 0 (it exits 1) | FAIL | FAIL ✓ | a declared command that exits non-zero must fail its exit assertion |

## Reading the numbers

Precision is the dangerous direction: a false claim that returns PASS is a
verifier telling you a lie is true. Recall is the noisy direction: a true
claim that returns FAIL is a verifier crying wolf.
This run has neither — every true claim passed and every false claim
failed — so both are 1.000.
The two headline cases are E11 (HTTP 200 but the app reports degraded) and
E19 (message 143 claimed sent, no row in the system of record): the two
shapes of overclaim the tool exists to catch.

## What this does not prove

Twenty cases on generated fixtures, not production traffic. It measures
whether the checks return the right verdict on claims whose truth is known
by construction — not whether a plan written by a model asserts the right
things in the first place. A plan that never checks the database can still
pass a claim that is false in the database; that failure is in the plan,
not in the checks, and this eval does not cover it.
