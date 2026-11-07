# ProofOps

[![verify](https://github.com/rasrobo/proofops/actions/workflows/verify.yml/badge.svg)](https://github.com/rasrobo/proofops/actions/workflows/verify.yml)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-yellow?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/robodigitalis)

### Your agent said "done". This is the receipt that proves it — or shows you the gap.

ProofOps is a **Hermes Agent plugin** — and a standalone Python CLI — for verifying what an AI agent
actually did. Every plugin makes an agent **do** more; this one makes it **prove** it.

An agent, a script or a colleague reports success. ProofOps runs a declared plan of read-only
checks against the real system or the deliverable, and writes a **receipt**: every check's actual
result, what that result proves, and — printed on every receipt — what passing does *not* prove.
It is the missing verification step between an agent saying "done" and anyone relying on it.

[`docs/EXECUTIVE-SUMMARY.md`](docs/EXECUTIVE-SUMMARY.md) is the two-minute version for someone who
will never read the code.

---

## The failure this exists for

Last week an agent told me a database rebuild was identical. It was convincing: 181 of 181 tables
matched, no errors, clean exit. Underneath, 39 structural drifts — columns, types and constraints
that no longer matched production.

The same week, three tool calls reported `sentMessageId 66` and `143`. No message existed in any
account database. It had never left.

Neither failure was a crash. Both were **well-formed claims that were completely wrong**, and both
would have survived any check that asks "did the command succeed?" That question is not the one
that matters. ProofOps asks the other one.

```
ProofOps run PO-20261104T231903Z-ff6b fail:
  plan      claw-way-django deployment readiness (sha256:eb01b6d884f0b144)
  [PASS] health-reachable: the readiness endpoint answers 200
  [FAIL] health-reports-ok: the application itself reports status=ok
         observed: {"expected": "ok", "observed": "degraded", "http_status": 200, ...}
```

**HTTP 200 with `status=degraded`.** Every uptime monitor on earth calls that healthy.

## What you get

**A claim you can send.** Not "I checked" — a file with the values observed, the commands that
produced them, the machine it ran on, and a hash over the whole thing. Attach it to a deploy, an
invoice, a client email, a handover.

**A gap you can see.** Checks that could not run are named at the top, not buried in a mostly-green
list, and the receipt carries `claimable: false`. An agent cannot quote the green part and skip the
rest.

**Proof the goalposts did not move.** Every receipt records the plan revision — a sha256 of the
checks themselves. Weakening an assertion to get a pass changes that revision, so a before/after
comparison cannot be faked by editing the test.

It does not make your work correct. It makes your claim **auditable**.

## Start here — one command, under two seconds

```bash
DEMO_FAST=1 ./demo/run_demo.sh      # without DEMO_FAST it pauses between acts so you can read
```

Starts a throwaway endpoint on loopback, runs a four-check plan against it (**PASS 4/4**), injects
one defect, re-runs the *same* plan (**FAIL 3/4**), repairs it, re-runs (**PASS 4/4**). Measured:
`real 0m1.638s`. Real output, last lines:

```
  same plan revision in all three runs:
    PO-20261106T021707Z-0e2a  PASS       4/4  sha256:eb01b6d884f0b144
    PO-20261106T021707Z-614f  FAIL       3/4  sha256:eb01b6d884f0b144
    PO-20261106T021707Z-7a4d  PASS       4/4  sha256:eb01b6d884f0b144
    identical revision: True
```

Three things to look at:

- the **FAIL still returns HTTP 200** — a status check calls that healthy, this does not
- every receipt prints what it did **not** check, in the run that passed too
- the plan revision is identical across PASS, FAIL and PASS — the green was not bought by
  loosening a check

### What you need, and whether it is safe to run

Python 3.10+. Nothing to install, no key, no account, no network beyond what a plan declares.

- **Reads only.** There is no POST, PUT or DELETE anywhere in the code. GETs go only to origins the
  plan lists — the demo's plan allows exactly `127.0.0.1:8099`.
- **Writes one thing:** `receipts/`, under the working directory.
- **Commands need two keys:** the plan lists the command verbatim *and* you pass
  `--allow-commands`. Neither alone is enough.
- **Touches nothing of yours:** the demo runs against a disposable fixture in the repo.

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

## Then point it at a folder of your own

Two commands, on a real directory, with real output:

```bash
python3 -m proofops new --dir /tmp/readme-demo        # inspect, write a plan — executes nothing
python3 -m proofops run /tmp/readme-demo/proofops-plan.json --target local
```

```
wrote /tmp/readme-demo/proofops-plan.json
  checks   csv-data, inventory-images
  next     python3 -m proofops run /tmp/readme-demo/proofops-plan.json --target local
```

```
ProofOps run PO-20261106T021722Z-49f9 pass:
  plan      readme-demo as it is today (sha256:b75e2c2b5da137d9)
  [PASS] csv-data: data.csv has the rows, header and complete cells it has today
  [PASS] inventory-images: images/ still contains exactly the 2 files it has today, unchanged
  Not verified:
    - that the contents are correct, only that they match what was recorded today
    - that anything outside this plan was checked
```

Delete one row, run the same command again, change nothing else:

```
ProofOps run PO-20261106T021724Z-c713 fail:
  [FAIL] csv-data: data.csv has the rows, header and complete cells it has today
         observed: rows expected 3, got 2
```

That is the whole product in four lines: a claim, the evidence, the gap, and a number you can act
on. `new` reads CSV shape, image dimensions, PDF page counts, SQLite table counts and a per-file
directory inventory; it never runs anything and the plan is plain JSON you can edit.

[`docs/PLANS.md`](docs/PLANS.md) has copy-paste recipes for when you want a plan the generator would
not write for you — "the message landed", "the report went out", "the tests ran".

### Is the receipt still the receipt?

```bash
python3 -m proofops verify receipts/PO-….json      # valid / tampered / unsealed / needs-key
```

## Install

```bash
hermes plugins install https://github.com/rasrobo/proofops
hermes plugins enable proofops
# non-interactive (SSH, CI) needs --yes-deps, or the install is refused
```

Four tools and one skill, no dependencies beyond the Python standard library.

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

Runs without Hermes too:

```bash
python3 -m proofops list --plans plans
python3 -m proofops run plans/claw-way-deployment.json --target https://app.example.com
python3 -m proofops show receipts/PO-....json
```

Exit codes are a contract: `0` all checks passed · `1` a check failed · `2` the run could not be
performed (bad plan, an origin the plan never declared, a command the operator never authorised).
A caller that ignores every line of output can still trust the exit code.

## Metrics — off by default

It asks **once**, at the only moment you have a receipt worth counting — after your first run. One
screen, Enter means no, and it never asks again:

```
  [y] count my runs anonymously      [d] show me the exact bytes first
  [Enter] no - and do not ask again
```

No default-yes, no countdown, no pre-ticked box: a prompt that could be defaulted into consent
would make every number on the public page a lie. Answering `y` sends the first one immediately, so
the decision shows up on the dashboard rather than waiting for you to remember a second command.

Everything is still available explicitly:

```bash
python3 -m proofops stats            # your own receipts, local only, no socket
python3 -m proofops share --dry-run  # print the exact payload — sends nothing
python3 -m proofops share --enable   # opt in and send
python3 -m proofops share --send     # send again later, using recorded consent
python3 -m proofops setup            # ask the question again, if you changed your mind
```

`CI=1` or `PROOPS_NO_PROMPT=1` suppresses the prompt entirely for unattended runs — nothing is
enabled in that case. The full field-by-field spec is in [docs/METRICS.md](docs/METRICS.md).

The payload is exactly this and nothing else — a random install id, version, run count, plan count,
platform, pass/fail/not-run totals, and the same totals **per check type** so the report can say
what kind of thing is being verified (a web service, a file, a PDF, a database) without saying whose:

```json
{"schema":2,"install_id":"<uuid4>","version":"0.3.5","runs":41,"plans":3,"platform":"linux",
 "checks":{"pass":128,"fail":9,"not_run":2},
 "by_type":{"http_status":{"pass":40,"fail":2,"not_run":0},
            "pdf_pages":{"pass":6,"fail":1,"not_run":0}}}
```

The type names are a closed set of fourteen, and the server rejects anything outside it — so a plan
named after a customer cannot become a type name.

No paths, hostnames, plan names, receipt contents or command output — a test asserts the payload
contains none of those, and another asserts `urlopen` is never reached without recorded consent.
`--disable` forgets the consent; nothing is sent again.

The aggregate is published, not hoarded: **[rasrobo.github.io/proofops/metrics](https://rasrobo.github.io/proofops/metrics/)**
shows installs, runs verified and check outcomes, including how many checks failed. Sanitising is an
allow-list on both ends — an unrecognised version is stored as `unknown` and an unrecognised
platform as `other`, so a client that sends a hostname or an email cannot store one.

## How it works

### Plans are data

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

### The receipt

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

## Risks, and what has been done about them

A verification tool fails quietly, which is why this section is here rather than in a footnote.
Each risk is real, each mitigation is in the code, and what remains is stated as remaining.

**A plan can be too narrow and still pass.** A row count calls a short file healthy.
*Done:* the benchmark publishes the miss rate per plan strength — narrow catches 3 of 22 defects —
so nobody can read "PASS" as "correct". Every receipt names what it did not test.

**A verifier can cry wolf.** Exact checks flag files that were merely re-saved.
*Done:* false alarms are measured, not assumed: 3 of 5 benign changes flagged by byte-exact plans,
0 by structural, document and record plans. The numbers are in this README, not in a pitch.

**A verdict can depend on the machine.** CI caught `select 1` against a non-database file passing
on one SQLite build and failing on another.
*Done:* fixed at the source (`PRAGMA schema_version` forces the header check) and pinned by a test.
Fourteen limits tests now assert that unreadable inputs fail **loudly**, never cleanly.

**A receipt can be edited after the fact.**
*Done:* sha256 seal, optional HMAC, and a `verify` command whose own output states what sealing
does *not* prove — that the checks were honest, or that the plan was adequate.

**An agent can quote the green part of a mostly-green run.**
*Done:* `claimable: false`, the `not_verified` list, and exit code `2` for a run that could not be
performed. A refusal is a third outcome, never a pass and never a failure.

**Judgement is not observable.** A plan can prove a page contains a contact form, that a submission
returns 200, and that a row appeared. It cannot prove the submitter was human, that the enquiry was
legitimate, or that anyone will answer it. "Legitimate", "valid", "real" and "quality" are
judgements; a receipt records the observation underneath them, never the judgement itself. Do not
cite one as if it did.

**What remains:** ProofOps cannot prove the checks were run honestly, cannot cover authenticated
flows or browser journeys, and cannot read scanned PDFs or CID fonts without ToUnicode. Those are
named in every receipt rather than left to be discovered.

## How good is it? Measured, including where it fails

`bench/run_bench.py` answers the only honest question a verifier can be asked: what is my detection
rate, and what do I flag when nothing is wrong. The corpus is two independently published CSVs (194
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
letting a row-count plan claim a catch it had not made; and CI found the SQLite cross-version
verdict above. Each is fixed and pinned by a test.

## Where it stands, and what is next

**Shipped:** 0.3.3 — a loadable Hermes plugin (4 tools + 1 skill, `hermes plugins validate` clean)
over a stdlib-only engine: 5 plans, 14 check types, command checks fenced twice, path-fenced
deliverable/document/record checks, sealed and optionally signed receipts, origin allowlists, a
CLI, and an injected-defect benchmark. **116 tests**, CI green on every push (tests, benchmark,
end-to-end demonstration, seal check).

**Next, in order:** a plan linter that warns when a plan asserts less than its `proves` line
implies; a `diff` command comparing two receipts of the same revision; and Postgres read-back as a
first-class check rather than through `psql`.

**Deliberately not built:** authenticated HTTP, browser journeys, plan composition, and any UI.
ProofOps does not repair anything, and does not claim to.

## FAQ

**Is this a Hermes Agent plugin?**
Yes. `hermes plugins install https://github.com/rasrobo/proofops` adds four tools — `proofops_plans`,
`proofops_run`, `proofops_receipt`, `proofops_verify` — and one skill that tells the agent to verify
before it writes "done". It also runs standalone, with no Hermes installed.

**How do I check whether my AI agent actually finished the task?**
Turn the claim into observable checks (`proofops new --dir …` does this automatically for files),
run them, and read the receipt. A PASS means the checks you declared were observed to hold — and the
same receipt prints what they do not cover, so a pass can never be quoted as "everything works".

**Why does my agent say "done" when it isn't?**
Because "the command succeeded" and "the outcome is correct" are different claims, and most tooling
only reports the first. An HTTP 200, a zero exit code and an existing file are all compatible with
the job not being done — that gap is what this checks.

**Does it use an LLM?**
No model, no API key, and **no telemetry unless you opt in**. The only network traffic is the HTTP
GETs a plan explicitly declares — plus, if and only if you run `proofops share --enable`, one
payload you can print first with `--dry-run`. Same plan against the same state gives the same verdict, which is what makes a receipt
worth quoting.

**Is it a test runner or a CI pipeline?**
No — it verifies claims about *state* (a deployment, an export, a database row, a document), which
test suites rarely see. It runs happily inside CI; this repository has a workflow that tests it,
benchmarks it and verifies its own receipts on every push.

**Can it verify that an email or message was really sent?**
It verifies the row a send is supposed to leave behind — `sqlite_query` for SQLite, `psql` through
`command_exit` for Postgres. It cannot see the recipient's inbox, and says so rather than implying
otherwise.

**What is a receipt, exactly?**
A JSON file holding each check's result and observed values, the plan revision, the inspector's
identity, and a sha256 seal. `proofops verify` returns valid / tampered / unsealed / needs-key.

**Does it send anything about me?**
Not unless you opt in. `proofops stats` is local-only, and `proofops share` prints the exact payload
with `--dry-run` before anything leaves the machine. Nothing about your plans, paths or receipt
contents is ever in it.

**What do I need to run it?**
Python 3.10+. Nothing else — the standard library, no install step, no credentials.

## If something here is wrong

Open an issue. Every number in this README is reproducible with the command beside it, and a
figure that has stopped being true is a bug — catching bugs of exactly that kind is the point of
the project.

## Support this

ProofOps is MIT-licensed, has no company behind it, and takes no money from the thing it verifies —
no hosted tier, no telemetry by default, no upsell, no "enterprise verification" edition later.

If it caught something that would have cost you an afternoon, you can
**[buy me a coffee](https://buymeacoffee.com/robodigitalis)**. That is genuinely it: nothing about
the tool changes whether you do or not, there is no subscriber-only version, and a star or a bug
report is worth just as much.

## Provenance

Built for the Hermes Agent plugin hackathon. Every number in this README comes from the repository
and is reproducible with the commands shown beside it. If one stops being true, that is a bug —
and catching bugs of exactly that kind is what the project is for.
