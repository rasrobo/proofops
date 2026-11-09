# Submission — what the organisers ask for

**The form itself:** http://form.typeform.com/to/FwJLvOln (🐴 Hermes Agent Plugin Hackathon, ~5 min).
Its six questions, in order: Plugin Title · Plugin Description · Email Address · Discord Username ·
X Demo Post Link · one more (repo/PR) — so the X post must exist before the form can be completed.

Answers for the first three are below; the X link comes from the posted thread.

**Deadline: 11 November 2026, 13:00 PST (16:00 EST)** — that is the time the organiser's own
confirmation screen states. **Submitted 2026-11-09.** Three things were required; all three are done:

| | |
|---|---|
| Demo video, public | youtu.be/3ee1VbHZpXo (74 s) |
| X thread tagging @NousResearch | x.com/stephanunc/status/2118762360324399271 |
| Submission form | **Submission Received** — screenshot at `docs/evidence/submission-confirmed-2026-11-09.png` |

The fields submitted were: title *ProofOps*; the one-liner below; stephanunc@gmail.com; discord
`robodigitalis`; the X post URL; and the catalogue PR link.

| # | the ask | status |
|---|---|---|
| 1 | Open a pull request adding the plugin to the Hermes catalogue | **done** — [PR #149625](https://github.com/NousResearch/hermes-agent/pull/149625), open and mergeable |
| 2 | Post a demo **on X, under 90 seconds, tagging @NousResearch** | **yours** — copy below, video is 74 s |
| 3 | Submit both links through the organiser's form ([typeform](http://form.typeform.com/to/FwJLvOln)) | **yours** — answers below |

The X post is not optional and a YouTube link alone does not satisfy it: the rules ask for the
demo posted on X. It has to come from your account, because it is judged as your entry.

## The X post (paste this, then reply with the second block)

```
ProofOps: a Hermes plugin that checks whether “done” is true.

CI caught it catching itself: a check that passed on one machine, failed on another. Every run leaves a sealed receipt — what was verified, and what wasn’t.

74s: youtu.be/3ee1VbHZpXo #HermesAgent
```

Reply to your own post with:

```
The numbers ship with the tool: a row-count plan catches 3 of 22 injected defects. Checksums catch 13 of 22 — and raise 3 false alarms on files that were only reformatted.

139 tests, CI green. Public usage dashboard, failures included: rasrobo.github.io/proofops/metrics
@NousResearch catalogue PR: github.com/NousResearch/hermes-agent/pull/149625
```

The video is already public (verified 2026-11-07): https://youtu.be/3ee1VbHZpXo — attach it to post 1
so the link plays inline, and put the alt text on the attachment, not in the text.

---

# Form answers — the text to paste

Every field below is ready to copy. Figures are from the frozen release; the pin and the version
are the ones in the catalogue entry.

| field | value |
|---|---|
| Project name | ProofOps |
| Repository | https://github.com/rasrobo/proofops |
| Catalogue PR | https://github.com/NousResearch/hermes-agent/pull/149625 |
| Pinned commit | `8c7744f32195cca86861bd0d930b05a18a865865` (version 0.3.9) |
| Demo video | https://youtu.be/3ee1VbHZpXo (74 s, public, limit is 90 s) |
| X post | the thread tagging @NousResearch, `#HermesAgent` |

## One line

An independent inspector for AI "done" claims: it runs a declared plan of read-only checks and
returns a sealed receipt of what it verified — and what it did not.

## What it does

When an agent says a task is complete, ProofOps runs a plan of read-only checks against the system
or the deliverable and writes a receipt: each check's actual result, what it proves, and — printed
on every receipt — what passing does not prove. Receipts are sealed with a sha256 digest and can
be HMAC-signed; `proofops verify` reports valid / tampered / unsealed / needs-key.

A check that cannot be performed is a third outcome, `NOT RUN`, never a failure and never a pass.
The receipt then carries `claimable: false`, so a gap cannot be quoted as a green tick.

## How it is used in Hermes

Four tools — `proofops_plans`, `proofops_run`, `proofops_receipt`, `proofops_verify` — plus a
bundled `verify-before-done` skill that tells the agent to run a plan before it writes "done".
No hooks, no middleware, no core modification, no dependencies beyond Python's standard library.

Install:

```
hermes plugins install https://github.com/rasrobo/proofops
```

Then getting started takes one command: `proofops new --dir <your directory>` inspects what is actually
there (CSV shape, image dimensions, PDF page counts, SQLite table counts, directory inventory) and
writes a plan asserting the shape it has now.

## Evidence — all reproducible

- **116 automated tests**, `python3 -m unittest discover -s tests`, including 14 limits tests that
  assert the tool fails *loudly* on what it cannot read.
- **`bench/run_bench.py`** — 22 defects injected one at a time into two independently published
  CSVs (194 countries; 891 passengers with 177/687/2 real nulls), a deterministic image export, a
  two-page PDF and a SQLite record, with 5 benign changes that must not be flagged:

  | plan | defects caught | false alarms |
  |---|---|---|
  | row count only | 3/22 | 0/5 |
  | rows + header + nulls + inventory + dimensions | 12/22 | 0/5 |
  | byte-exact checksums | 13/22 | 3/5 |
  | documents: page count, page size, text landmarks | 3/22 | 0/5 |
  | records: is the message actually in the database | 2/22 | 0/5 |
  | second dataset: shape and real nulls | 4/22 | 0/5 |

- **`hermes plugins validate`** — clean: manifest, capability probe, declared tools matching
  registrations, security scan, no core override.
- **CI green on the pinned commit** (run 42146490772): unit tests, benchmark, end-to-end
  demonstration, and a seal check on the receipt the demonstration produced.
- **Live receipts against a production SaaS**: deployment readiness PASS 4/4, deployed
  configuration PASS 2/2, migration replay PASS 2/2, and schema drift FAIL with 39 structural
  drifts across 181 matching tables — kept failing on purpose, because that is the evidence.

## Judging criteria

- **Usefulness** — it targets the failure that costs days: work that reports success and isn't.
  Receipts are quotable evidence for a customer or an auditor.
- **Reliability** — 139 tests and a public benchmark with its own false-alarm rate; a refusal is a
  third outcome, not a green tick; weakening a plan changes its revision, so a loosened check
  cannot masquerade as the original; receipts cannot be edited after the run without detection.
  CI caught the tool's own verdict changing with the SQLite library version — a `select 1` against
  a non-database file passed on one build and failed on another — and that is fixed at the source
  (`PRAGMA schema_version` forces the header check).
- **Polish** — exit codes are a contract (0 pass / 1 fail / 2 could-not-run); every receipt states
  its own limits; the benchmark publishes where it misses.

## Disclosures

Network access is HTTP GET only, against origins the plan declares. Command checks run the exact
argv a plan lists, and only with operator opt-in. Receipts are written under the plugin's own data
directory and contain observed values, hostname, cwd and command output. No credentials are read
or stored; no telemetry by default (opt-in aggregate only, payload inspectable with `proofops share --dry-run`); the aggregate is published at https://rasrobo.github.io/proofops/metrics/.

## Known limits

A receipt proves only what a plan describes. No authenticated flows, no browser journeys, no
rendering checks. PDF text extraction cannot read scanned pages or CID fonts without ToUnicode,
and says so instead of guessing. Postgres read-back goes through `command_exit` + `psql` rather
than a native check.
