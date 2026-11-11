---
name: verify-before-done
description: "Use before saying a task is complete: run the proofops plan and quote the receipt."
version: 1.0.0
---

# Verify before done

An agent's "done" is a claim. This skill is how to turn it into evidence before the user
reads it.

## When to use

- The task ended with a deployment, a restart, a migration, a rebuild, a config change, or
  a "it's live now".
- You are about to write "done", "fixed", "deployed", "migrated", "verified", "all tests
  pass", or "everything works".
- A previous attempt already failed and you believe it is repaired — the re-run is the
  proof, not your confidence.

## Procedure

1. **Find the plan.** `proofops_plans(plans_dir="plans")` — if a plan already covers the
   outcome you are about to claim, use it. Do not write a fresh plan whose only purpose is
   to pass.
2. **Run it.** `proofops_run(plan="plans/<name>.json", target="https://…")`.
   - Command checks come back `NOT RUN` unless the plan lists the command verbatim
     **and** the operator approved that exact command — pre-approved in the plugin's
     settings, or by answering the approval prompt that shows the exact command.
     That is deliberate: a refusal is not a failure and not a pass.
3. **Read the verdict.**
   - `PASS` — every check passed. Say exactly which checks, by id.
   - `FAIL` — quote the failing check's `observed` value. Repair, then re-run the **same
     plan file**; a changed plan is a new revision and the before/after is no longer a
     comparison.
   - `INCOMPLETE` — nothing may be claimed, **including the checks that passed**. The
     receipt carries `claimable: false` and a `not_verified` list naming every check that did
     not run and the reason. Quote that list verbatim; do not summarise it as "mostly fine".
4. **Check the seal before quoting it.** `proofops_verify(receipt="PO-…")`. If it returns
   `tampered`, the file was edited after it was written — quote nothing from it and re-run
   the plan. `valid` means only that the file is unchanged; it does **not** mean the checks
   were adequate or honest, and the tool prints that limit itself.
5. **Quote the receipt.** Use `report_line`, or:

   ```
   ProofOps run <run_id> passed: <the checks that passed>.
   Not verified: <does_not_prove items that matter here>.
   ```

## Rules

- Never summarise a receipt as "everything works". The `does_not_prove` list is part of the
  result, not a disclaimer to drop.
- Never widen a plan's `allowed_origins` or `allowed_commands` to make a run go green.
- Branch on `claimable`, not on the count of green ticks. `claimable: false` means you may not
  write "done", "deployed", "fixed" or "verified", even if every check that did run passed.
- Never describe a `NOT RUN` check as passed, or a refused check as failed.
- Never quote a receipt whose seal does not verify, and never present "sealed" as "true":
  sealing proves the file is unchanged, not that the inspection was adequate.
- ProofOps verifies; it never repairs. Do the repair with ordinary tools, then re-run.
- If no plan covers the outcome, say so plainly — "no verification exists for this claim"
  is an honest answer, and a stronger one than an unverified success message.
