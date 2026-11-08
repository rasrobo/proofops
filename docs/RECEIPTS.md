# Receipts against real, third-party services

Every other receipt in this repo came from a fixture we built, so "does it work on anything
real?" is a fair question. These three were run once, read-only, against public endpoints on
2026-11-08, and the observed values are published verbatim.

Regenerate with `python3 scripts/real_receipts.py` — it uses the same code path as any plan, so a
pass here is not a special demo mode.

## httpbin responds correctly

`https://httpbin.org` · verdict **PASS** · plan revision `sha256:b7f9853593719ea5` · sealed `sha256:1abea4b1034f42e2…`

| check | type | result | observed |
|---|---|---|---|
| `status` | `http_status` | PASS | `200` |
| `json-field` | `http_json_field` | PASS | `Yours Truly` |
| `body` | `http_body_contains` | PASS | `` |

Does not prove: that the service is useful, only that it answers as documented

## github api is up and rate-limited as documented

`https://api.github.com` · verdict **PASS** · plan revision `sha256:3badf6a8e6fa174e` · sealed `sha256:0a7dcd2994008233…`

| check | type | result | observed |
|---|---|---|---|
| `root-200` | `http_status` | PASS | `200` |
| `no-auth-required-for-root` | `http_status` | PASS | `200` |
| `ratelimit-header-declared` | `http_header` | PASS | `60` |

Does not prove: that any repository or user data is reachable

## a static site serves the page it claims

`https://example.com` · verdict **PASS** · plan revision `sha256:e28d3dbc57857e03` · sealed `sha256:a2be8b281757ac6b…`

| check | type | result | observed |
|---|---|---|---|
| `200` | `http_status` | PASS | `200` |
| `content-type` | `http_header` | PASS | `text/html; charset=utf-8` |
| `has-title` | `http_body_contains` | PASS | `` |

Does not prove: that the site is reachable from anywhere but here

## The first attempt, and why it is the better story

Two of these three plans failed on the first run - not because the services were down, but
because the plans were wrong: `http_header` needs `equals`, and I had written `contains`.
The receipt said so, per check (this is the output as it was, before the engine fix described below):

```
[FAIL] ratelimit-header-declared: check is missing required key 'equals'
[FAIL] content-type: check is missing required key 'equals'
```

That output also exposed a real defect in the engine: a malformed check was counted as a
**failure**, which reads as "your service is broken" when in fact nothing was ever tested.
It now reports NOT RUN, carries a `how_to_fix` line, and the run exits 2 (nothing tested)
instead of 1 (something failed). Both states are in the test suite.
