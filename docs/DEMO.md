# Demo — 90 seconds

Run `./demo/run_demo.sh` and record the terminal. Every frame is loopback-only: no host to
blur, no customer data, no receipts from a live system.

## Shot list

| time | on screen | say |
|---|---|---|
| 0:00 | terminal, `ProofOps` title, `python3 -m proofops list --plans plans` | "Agents say done. This checks whether that's true." |
| 0:10 | the plan JSON, its revision | "A plan is a file. This one asks four things of a readiness endpoint, and declares what passing won't prove." |
| 0:20 | `run_demo.sh` act 1 → **PASS 4/4** | "The system is healthy. Green receipt, four checks named." |
| 0:35 | inject `degraded` — `sed` line visible | "Now one realistic defect: the app reports *degraded*, while the endpoint still answers HTTP 200." |
| 0:45 | **FAIL 3/4**, the `observed` line on screen | "A status-code monitor calls that healthy. ProofOps fails it — expected ok, observed degraded, HTTP 200." |
| 1:05 | repair line, re-run → **PASS 4/4** | "We repair it with ordinary tools. ProofOps repairs nothing — it verifies." |
| 1:15 | the three receipts, identical revision | "Same plan revision all three runs. The test wasn't loosened to get the green." |
| 1:22 | a real receipt's `Not verified:` block | "And every receipt says what it did not check. That's the product: not 'everything works' — what was verified, and what wasn't." |

## Two rules for the recording

1. **Do not show a production receipt on camera.** The command check in
   `auth-endpoint-suite.json` contains an internal host and user. The fixture receipts in
   this demo contain none. If the auth result is mentioned, say the numbers (235 passed, 6
   failed) and show the redacted line, not the receipt.
2. **Do not say "everything works"** anywhere, including in jest. The submission's whole
   claim is that this sentence is the failure mode.

## The failing-auth beat (optional, 15s)

If you want the harder, less flattering beat — it is the strongest evidence in the
submission:

> "Here's the same tool pointed at our own product. 241 tests. 235 pass, 6 fail. One of them
> fails because it expects to SSH to a host that has no DNS record. An agent would have told
> me authentication was fixed. The receipt says otherwise."

Show the summary line `6 failed, 235 passed in 562.22s`, not the command.
