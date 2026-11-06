# ProofOps — executive summary

**One line:** ProofOps is an independent inspector for AI work. When an AI agent says
"done", ProofOps checks whether that is true — and hands you a sealed record of what it
verified and what it did not.

---

## The problem, in business terms

AI agents are now trusted to deploy software, run backups, and complete operational work.
They are confident, fast, and occasionally wrong in ways that look exactly like success.

The expensive failures are not the loud ones. They are these:

- A backup job reports **success** while three of four servers have no copy.
- A deployment reports **healthy** while the application is not actually ready.
- A rebuilt system reports **complete** while quietly differing from the original.

In each case the dashboard is green. The people responsible believe the work is done.
The problem surfaces days or weeks later, when it is much more expensive.

Traditional monitoring does not catch this, because monitoring asks *"is it running?"*.
Nobody asks *"is the outcome actually correct — and what evidence do we have?"*

---

## What ProofOps does

It runs a short **inspection plan** against a system and produces a **receipt**.

A receipt is one page. It lists each check, what was actually observed, whether it
passed — and, printed on every receipt, **what passing does not prove**.

Think of a building inspection. The certificate does not say "the building is perfect".
It says what was inspected, what was found, and what was out of scope. That distinction is
the entire product.

Three principles are enforced in the software, not just promised in a document:

1. **An inspection cannot touch what it was not authorised to touch.** A plan must name
   the systems it may contact, and any command it may run. Pointing it elsewhere is
   refused before anything happens.
2. **A receipt can never say "everything works".** Every plan must state its limitations
   up front, or it will not load.
3. **The inspection cannot be quietly weakened to get a pass.** Each run is stamped with a
   fingerprint of the exact checks used. Changing a check changes the fingerprint, so a
   weaker test can never masquerade as the original.

A fourth property is what makes a receipt usable as evidence at all: **it cannot be edited
after the fact without that being detectable.** Every receipt is sealed with a hash, and can
be signed with a key, so a reader can check it themselves in one command:

```
$ python3 -m proofops verify receipts/PO-20261105T164723Z-b71b.json
receipts/PO-20261105T164723Z-b71b.json: valid
  digest matches - the file has not been edited since it was sealed. It is NOT signed:
  anyone who rewrites the body could also rewrite the digest.
  What this does NOT prove: that the checks were run honestly, that the plan was
  adequate, or that the observer is truthful. It proves the file is unchanged.
```

The tool states its own limit on the face of the output. Configure a signing key
(`--key-file` or `PROOPS_SIGNING_KEY`) and the same command checks an HMAC-SHA256
signature instead, so a second party can prove *which* key sealed the record.

Editing a verdict, an observed value, or the list of limitations breaks the seal. A receipt
also records which build of the inspector produced it, so "verified" is attributable rather
than anonymous.

---

## Proof, from our own business last week

These are real results from our production systems, not a demonstration environment.

**1. The backup that said it worked.**
Four servers back up nightly. The job that copies them off-site reported success. In
reality it crashed partway through, and three servers had no off-site copy. A status check
would have called this healthy; the receipt showed the gap.

**2. The rebuild that looked identical.**
After a database rebuild, a simple comparison said "182 of 182 tables — identical". A
deeper inspection found **39 structural differences**, including a column that had changed
size and timestamps that had stopped being mandatory. Same furniture, different wiring.

**3. The benchmark, not the demo, is the evidence.**
We inject known defects into a copy of a real dataset — 13 of them, one at a time — and count
what each quality of check catches:

| the plan you wrote | defects caught | false alarms on unchanged-but-reformatted files |
|---|---|---|
| row count only ("the export looks fine") | 3 of 18 | 0 |
| rows + header + nulls + inventory + dimensions | 12 of 18 | 0 |
| byte-exact checksums | 13 of 18 | 3 |
| documents: page count, page size, text landmarks | 3 of 18 (all 3 PDF defects) | 0 |
| records: is the message actually in the database | 2 of 18 (both database defects) | 0 |

That is the product in one table: a weak plan is not a lie, it is a promise about less. The
tool's job is to make that difference visible before someone signs off on it.

**4. The inspection caught its own author.**
The first version of that check was mine, and it passed. The stricter check disproved my
own claim. That is the behaviour you want from a verifier: it is not loyal to the person
who wrote it.

---

## Why this matters commercially

- **Evidence for customers and auditors.** "It's deployed" becomes a record with a
  timestamp, the checks run, and their results.
- **Insurance against silent failure.** It catches the class of error that costs days of
  revenue and credibility — the one that looks fine until it isn't.
- **Cheap to adopt.** Plans are plain text files. No new infrastructure, no vendor, no
  agents installed on customer machines.
- **Works with any system.** It asks a system what it claims, and checks the claim.

---

## What the demonstration shows (about 80 seconds)

1. A healthy system passes inspection — a green receipt.
2. We break one value. The service still answers **"everything is fine" (200 OK)**.
3. ProofOps fails it anyway, and the receipt shows *expected* versus *observed*.
4. We repair the fault using ordinary tools. ProofOps repaired nothing — it verified.
5. The re-run passes with the **same** inspection fingerprint, proving the test was not
   loosened to get a green light.
6. We read the limitations aloud: what this receipt does **not** prove.

---

## Honest limits

- It only proves what a plan describes. It is not a guarantee of correctness.
- It does not yet cover logged-in user journeys or payment flows; those are the next step
  and are stated as gaps rather than papered over.
- It produces evidence; people still decide what to do with it.

Stating these is deliberate. A verification tool that overstates its coverage is worse
than none, because it buys false confidence.

---

## Status

Working software: fourteen check types (live services, process, deliverables such as CSV shape
and image dimensions, and documents such as PDF page count and text landmarks), five inspection
plans, a receipt for every run, a defect-injection benchmark with published detection and
false-alarm rates, and its own suite of 102 automated tests. Development so far has been applied to our live SaaS platform: deployments,
configuration, database rebuilds and schema fidelity.

The immediate next step is extending coverage to the workflows where a premature "done"
is most expensive: customer provisioning, authentication, and billing.
