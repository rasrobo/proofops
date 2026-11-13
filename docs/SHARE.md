# Ready-to-post copy

The product is not the bottleneck any more: one install is a distribution fact, not a quality signal.
These are written to be pasted, and every one of them lands on `proofops demo` rather than a README,
because the demo is the argument.

---

## Discord — hackathon channel (highest value: judges and other entrants are already there)

> **ProofOps — the receipt for "done".**
>
> Every agent plugin makes an agent *do* more. This one makes it *prove* it.
>
> 20 seconds, no config, no account:
> ```
> pipx install git+https://github.com/rasrobo/proofops && proofops demo
> ```
> It builds a fixture that answers **200** while reporting `status: degraded`. One check passes (the
> status code), the next fails (the claim). Then it edits the receipt and shows verification catch
> the edit: `valid` → `tampered`.
>
> That gap — a green tick that is technically true and operationally wrong — is what it exists for.
>
> 74 s demo: youtu.be/3ee1VbHZpXo · repo: github.com/rasrobo/proofops · catalogue PR: #149625
> Numbers, failures included: rasrobo.github.io/proofops/metrics

---

## X — main post (attach the video)

```
ProofOps: a Hermes plugin that checks whether "done" is true.

20 seconds, no config:
pipx install git+https://github.com/rasrobo/proofops && proofops demo

It shows a service answering 200 while reporting "degraded" — one check passes, the claim fails.

74s: youtu.be/3ee1VbHZpXo #HermesAgent
```

**Reply:**

```
The numbers ship with the tool: a row-count plan catches 3 of 22 injected defects, checksums catch
13 of 22 and raise 3 false alarms on files that were only reformatted.

181 tests, CI green. Usage dashboard, failures included:
rasrobo.github.io/proofops/metrics
@NousResearch catalogue PR: github.com/NousResearch/hermes-agent/pull/149625
```

---

## Hacker News — title + first comment

**Title:** Show HN: ProofOps – receipts for an AI agent's "done"

**Comment:**

> I kept getting "done" from agents where nothing was done: a database rebuild reported identical
> with 39 structural drifts, and three "sent" messages that never left the box. Neither was an error;
> both were well-formed claims that were wrong.
>
> ProofOps runs a declared plan of read-only checks against the real system and writes a receipt:
> each check's observed value, what it proves, and — on every receipt — what passing does *not*
> prove. A check that cannot run is reported NOT RUN, never a green tick.
>
> `pipx install git+https://github.com/rasrobo/proofops && proofops demo` shows a 200 that lies in
> about twenty seconds, then forges the receipt and shows verification catch it.
>
> 14 check types (HTTP, files, checksums, CSV, images, PDF, read-only SQLite), 181 tests, and a
> benchmark with 22 injected defects that publishes its own false-alarm rate.

---

## Reddit — r/LocalLLaMA or r/AI_Agents

Same body as HN, with the title: *"I built a verifier for agent 'done' claims — it prints what
passing does not prove"*.

---

## One-line versions, for a bio or a DM

- ProofOps turns "the agent said done" into a sealed receipt of what was actually checked.
- A verifier that prints, on every receipt, what passing does not prove.
- Twenty seconds to see a 200 that lies: `proofops demo`.

---

## What not to say

- Do not claim it prevents bad work: it makes bad work **visible**.
- Do not claim adoption: the dashboard says one install, and the page says the first one is the
  author's.
- Do not call it telemetry: it is opt-in anonymous diagnostics, and the bytes are printable first.
