# Diagnostics — what leaves your machine, exactly

This is the authoritative description of the opt-in aggregate ProofOps can send, and of the public
page it feeds: **https://rasrobo.github.io/proofops/metrics/**

If this file and the code disagree, the code is wrong and the file is the bug report.

## The three states

| State | How you get there | What happens |
|---|---|---|
| `undecided` | Every fresh install starts here | Nothing is sent. You are asked **once**, at the first moment you have a receipt to show for it. |
| `enabled` | Answer `y` at the prompt, or run `proofops share --enable` | One small POST per share. Repeated with `proofops share --send`. |
| `declined` | Press Enter at the prompt, or `proofops share --disable` | Nothing is ever sent, and you are never asked again. |

State lives in `~/.proofops/consent.json` (override the directory with `PROOPS_HOME`).
`proofops setup` asks again, deliberately, if you change your mind.

**Enter means no.** There is no default-yes, no countdown, no pre-ticked box. A prompt that could be
defaulted into consent would make every number on the public page a lie, and this tool exists to
avoid exactly that.

Set `PROOPS_NO_PROMPT=1` (or `CI=1`) and the prompt never appears — useful for scripts, CI and
agent runs where nobody is at the keyboard. Nothing is enabled in that case; it stays `undecided`.

## The exact payload

```json
{
  "schema": 2,
  "install_id": "5e92b6c2-a3b2-4a5a-8265-0815357bb2df",
  "version": "0.6.0",
  "platform": "linux",
  "runs": 39,
  "plans": 7,
  "checks": {"pass": 120, "fail": 12, "not_run": 4},
  "by_type": {
    "http_json_field": {"pass": 81, "fail": 9, "not_run": 0},
    "http_status":     {"pass": 30, "fail": 0, "not_run": 0},
    "command_exit":    {"pass":  6, "fail": 2, "not_run": 4}
  }
}
```

Twenty keys at most, and that is the whole thing. `proofops share --dry-run` prints it, byte for
byte, before anything is sent — and the prompt offers `d` to show it too.

### What is never collected

No repository or file paths. No hostnames, URLs or IP addresses. No plan names, check ids, check
commands or `proves` text. No receipt contents, no observed values, no command output, no
environment variables, no timestamps of individual runs. No machine id — `install_id` is a random
UUID4 generated locally on first use and never derived from hardware, user or network.

## Why the type names are safe

`by_type` carries counts per **check type**, from a closed set of fourteen:

```
command_exit  file_sha256  file_exists  dir_manifest  csv_stats  image_size
pdf_pages  pdf_page_size  pdf_text_contains  sqlite_query
http_status  http_json_field  http_body_contains  http_header
```

Both ends allow-list them. The client refuses to serialise anything else; the server refuses to
store anything else. A plan named `acme-customer-portal` cannot become a category, because the
category is the *kind of check*, not the thing being checked.

## Sanitising is allow-list, not character-stripping

An earlier build removed every character outside `[a-z0-9._-]`. Fed `jane.doe@example.com`, it
produced `janedoeexamplecom`: every character removed, every identifying detail retained. A test
caught it because the assertion was "the string `jane` must not appear anywhere".

The rules now:

| Field | Rule | If it fails |
|---|---|---|
| `version` | matches `^\d+\.\d+\.\d+[0-9a-z.+-]{0,8}$` | replaced wholesale with `unknown` |
| `platform` | one of eight known OS names | replaced wholesale with `other` |
| `install_id` | must parse as a UUID | request rejected |
| counts | non-negative integers, clamped to 10,000,000 | clamped or zero |
| `by_type` keys | must be in the fourteen | dropped silently |
| any other key | — | request rejected with `unexpected fields` |

The server applies the same table independently, because a client is not a trust boundary.
Verified: a POST claiming `platform: "acme-prod-01.internal"` and a version containing an email
address was stored as `"other"` and `"unknown"`.

## Aggregation, and why the numbers do not drift upward

Each install sends cumulative totals, not deltas. Summing every row would double-count any install
that reported twice. The publisher keeps the **latest record per `install_id`** and sums those;
`scripts/publish_metrics.py` is the only thing that touches the data.

The page reports `installs`, `runs`, `checks`, `pass_rate`, the per-type table, the per-family
breakdown (derived at publish time, never sent), plus the versions and platforms in use.

## What we actually do with it

The numbers are the only field feedback this project gets, and they drive the backlog:

1. The check type with the most **not-run** checks is the next fix. A check that cannot run is a
   defect in the tool, not in the user's plan.
2. The type with the most **failures** gets the next diagnostic message — the count says where the
   friction is, not what it is.
3. Failures that never appear in any type are a signal too: it means that check is either perfect or
   never used, and one of those is worth knowing.

This is not a slogan: the `by_type` breakdown was added precisely because pass/fail could not say
which check to work on next, and the public page states the current "next fix" line from the data.

## Where the data lives

The **store of record is a JSON file in this repository**: `docs/metrics/data.json`. It is committed,
versioned, and it is the only thing the public page reads. If you want to know what the project
knows, read that file — there is no database behind the page.

Submissions are reduced to counters when they arrive. The individual records are not published, not
kept as a growing archive, and not queryable; what persists is the aggregate. That is deliberate: a
permanent log of per-install rows is a liability that buys nothing the counters do not already say.

Outside the client's single copy of that URL, nothing here names an ingest host, a filesystem path
or a provider. The URL is a dull name that says nothing about the product or what sits behind it —
documenting infrastructure is how a small tool becomes somebody's practice target.

## What the page cannot prove

It is self-reported: whoever runs the command could edit their own receipts first. It reports only
people who opted in, which is not a sample of installs. A passing check is not a defect avoided —
it is a claim that was checked. And the categories are check types, not industries.
