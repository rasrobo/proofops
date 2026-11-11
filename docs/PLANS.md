# Plan recipes

A plan is one claim, checked. These are the shapes that come up most; copy one, change the paths
or the URL, keep `proves` and `does_not_prove` honest.

Rules that are enforced when a plan loads, so you cannot get them wrong silently:

* every check states `proves` — the sentence you would say out loud if it passed
* every plan states `does_not_prove` — the sentence that stops the receipt being overquoted
* file checks live inside `allowed_paths`; HTTP checks live inside `allowed_origins`
* inside Hermes the operator must also configure `plugins.entries.proofops.settings.allowed_paths`.
  While it is unset, a plan that declares file roots is refused — the plan is written by the model
  it verifies, so it cannot nominate its own read roots. (The CLI is its own operator: there the
  plan's roots apply.)
* a `command_exit` check must list its argv **verbatim** in `allowed_commands`
* an unknown check `type` is refused, not skipped

Start from the generated plan instead of a blank file:

```bash
python3 -m proofops new --dir ~/exports
```

---

## "The service is up and serving this build"

```json
{
  "name": "hub is serving the new build",
  "target_kind": "production-readonly",
  "allowed_origins": ["https://hub.example.com"],
  "checks": [
    { "id": "reachable", "type": "http_status", "path": "/health", "expect": 200,
      "proves": "the readiness endpoint answers" },
    { "id": "reports-ok", "type": "http_json_field", "path": "/health",
      "field": "status", "equals": "ok",
      "proves": "the app itself says ok, not merely a proxy" },
    { "id": "build-marker", "type": "http_body_contains", "path": "/",
      "contains": "data-build=\"2026.11.06\"",
      "proves": "the page served is the build we shipped" }
  ],
  "does_not_prove": [
    "that the readiness field is honest — it is self-reported",
    "that the database behind it is reachable",
    "that logged-in pages render"
  ]
}
```

## "The export shipped"

```json
{
  "name": "export contains what we sent",
  "target_kind": "local-artifacts",
  "allowed_origins": [],
  "allowed_paths": ["/home/me/exports/2026-11-06"],
  "checks": [
    { "id": "inventory", "type": "dir_manifest", "path": "images",
      "expect": { "files": 120, "sha256": "<digest from `proofops new`>" },
      "proves": "images/ holds the same 120 files, byte for byte" },
    { "id": "sample-dims", "type": "image_size", "path": "images/hero.png",
      "width": 1920, "height": 1080,
      "proves": "the hero image is the size the client ordered" }
  ],
  "does_not_prove": ["that each image is correct, only unchanged", "that filenames are sensible"]
}
```

Pinning `sha256` is strict: re-saving a file with different line endings will fail it. Drop
`sha256` and keep `files`/`bytes` when you want “same shape, may be reformatted”.

## "The data loaded"

```json
{
  "name": "the export parsed completely",
  "target_kind": "local-artifacts",
  "allowed_origins": [],
  "allowed_paths": ["/home/me/data"],
  "checks": [
    { "id": "shape", "type": "csv_stats", "path": "orders.csv",
      "expect": { "rows": 194312, "columns": ["id", "email", "total"],
                  "nulls": { "id": 0, "email": 0 } },
      "proves": "every row is present and the two required columns are complete" }
  ],
  "does_not_prove": ["that totals are arithmetically right", "that emails are valid"]
}
```

Row counts catch truncation, which is the failure a “it loaded fine” claim always misses.

## "The report is the one we sent"

```json
{
  "name": "Q4 report matches what went to the client",
  "target_kind": "local-artifacts",
  "allowed_origins": [],
  "allowed_paths": ["/home/me/reports"],
  "checks": [
    { "id": "exact-bytes", "type": "file_sha256", "path": "q4.pdf",
      "equals": "<sha256 of the sent file>", "proves": "the file is byte-identical" },
    { "id": "pages", "type": "pdf_pages", "path": "q4.pdf", "equals": 12,
      "proves": "it still has twelve pages" },
    { "id": "heading", "type": "pdf_text_contains", "path": "q4.pdf",
      "contains": "Q4 2026", "proves": "the quarter heading is present" }
  ],
  "does_not_prove": [
    "that the PDF renders correctly — no rendering is performed",
    "that scanned pages contain the text (extraction needs a text layer)"
  ]
}
```

## "The message actually landed"

```json
{
  "name": "the message is in the system of record",
  "target_kind": "local-artifacts",
  "allowed_origins": [],
  "allowed_paths": ["/home/me/mail"],
  "checks": [
    { "id": "row", "type": "sqlite_query", "path": "account.db",
      "query": "select count(*) from messages where id = ? and sent = 1",
      "params": [143], "expect": { "equals": 1 },
      "proves": "message 143 exists and is marked sent" }
  ],
  "does_not_prove": ["that the body is what we meant to send",
                     "that any replica saw the write"]
}
```

A 200 from an API cannot see a missing row. This can. The query is opened `mode=ro` and must be a
single `SELECT`/`WITH` — the check cannot write.

For Postgres or MySQL, use `command_exit` with `psql`/`mysql` and assert both the exit code and a
line of output, so “exit 0, nothing collected” cannot pass.

## "The tests ran"

```json
{
  "name": "the suite actually executed",
  "target_kind": "local-artifacts",
  "allowed_origins": [],
  "allowed_paths": ["/home/me/project"],
  "allowed_commands": ["python3 -m pytest -q"],
  "checks": [
    { "id": "exit", "type": "command_exit", "command": "python3 -m pytest -q",
      "expect_exit": 0, "stdout_contains": "passed",
      "extract": { "name": "passed", "regex": "(\\d+) passed" },
      "proves": "the suite exited 0 and reported passing tests" }
  ],
  "does_not_prove": ["that the tests cover the behaviour you care about"]
}
```

Asserting the word `passed` as well as the exit code is what stops an exit-0-with-nothing-collected
run from looking like a green suite. Run it with `--allow-commands`.

---

## Claims a plan cannot prove, however it is written

Some claims sound like facts and are judgements. A plan can gather the evidence for them; it cannot
establish them, and a receipt that implied otherwise would be the exact failure this tool exists to
catch.

| claim | what a plan can show | what it cannot |
|---|---|---|
| "the enquiries are legitimate" | a submission returned 200 and a row exists | whether a human sent it, or whether it is spam, a scam or a buyer |
| "the copy is good" | the page contains the headline and the CTA | whether anyone reads, understands or acts |
| "the tests are meaningful" | N tests ran, in M shards, with K passing | whether they assert anything worth asserting |
| "the data is correct" | counts, headers, nulls and byte-identity match a baseline | whether the baseline was right |
| "it is secure" | the header is present, the endpoint refuses an unauthenticated request | whether the control works |

Write these as the observation plus a separate human judgement, and say so in `does_not_prove`.
When an agent claims something is legitimate, valid, real or high quality, a receipt is evidence of
the observation, not of the judgement.

## Writing your own

1. **One claim per check.** A check named `everything` will be quoted as “everything”.
2. **`proves` is the sentence you may say out loud.** If you would not say it to a client, it is
   too strong.
3. **`does_not_prove` is not decoration.** The receipt prints it every time; a plan without it
   does not load.
4. **Never widen the plan to get a pass.** Widening changes the revision, and the revision is what
   proves a before/after comparison was the same test.
