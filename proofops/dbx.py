"""Destination-of-record checks — did the thing actually land where it claims?

The claim that costs the most is the one an agent is most confident about: "sent". A status
code, a message id, an API's 200 — none of them prove a row exists in the system of record.
The only evidence is reading that store.

Scope, deliberately narrow:

* **SQLite only.** It needs no credentials, so a plan can name a database file and the whole
  thing stays inside the path fence. Postgres/MySQL belong behind `command_exit` + `psql`,
  where the two-gate command fence and the operator's own credentials already apply — adding a
  DSN reader here would mean a plugin reading a secret, which the catalogue rules forbid.
* **Read-only by construction.** The connection is opened with `mode=ro`, and the statement must
  begin with SELECT or WITH. One statement only. A check that could write would be a repair
  tool wearing a verifier's badge.

What it does not prove (and prints on every receipt): that the row is *correct*, only that it
matches the assertion; that the write reached any replica; or that the store is the only one
that matters.
"""

from __future__ import annotations

import re
import sqlite3
import time

from . import artifacts

MAX_ROWS = 200
MAX_VALUE = 500


def _readonly_statement(query: str) -> tuple[bool, str]:
    # Strip comments before deciding: "-- select" is not a select statement, and a commented
    # DELETE must not slip through a naive prefix check.
    q = re.sub(r"--[^\n]*", " ", query)
    q = re.sub(r"/\*.*?\*/", " ", q, flags=re.S).strip()
    if not re.match(r"^(select|with)\b", q, re.I):
        return False, "query must start with SELECT or WITH — this check is read-only"
    if ";" in q.rstrip(";").strip():
        return False, "query contains more than one statement — this check is read-only"
    return True, ""


def sqlite_query(spec: dict, _target: str) -> tuple[bool, dict]:
    path, why = artifacts.POLICY.resolve(spec["path"])
    if path is None:
        return False, {"path": spec["path"], "error": why}
    query = spec["query"]
    ok, why = _readonly_statement(query)
    if not ok:
        return False, {"path": path, "query": query, "error": why}

    started = time.monotonic()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error as e:
        return False, {"path": path, "error": f"cannot open database: {e}"}
    try:
        # Prove the file is a database before trusting any answer from it. A query like
        # `select 1` touches no b-tree, so on some SQLite builds it succeeds against a file
        # that is not a database at all - a green tick that depended on the SQLite version.
        # PRAGMA schema_version reads the schema page, which forces the header check.
        conn.execute("PRAGMA schema_version").fetchall()
        cur = conn.execute(query, list(spec.get("params") or []))
        columns = [d[0] for d in (cur.description or [])]
        rows = cur.fetchmany(MAX_ROWS + 1)
    except sqlite3.DatabaseError as e:
        reason = "file is not a database" if "not a database" in str(e).lower() else str(e)
        return False, {"path": path, "query": query,
                       "error": f"{type(e).__name__}: {reason}"}
    except sqlite3.Error as e:
        return False, {"path": path, "query": query, "error": f"{type(e).__name__}: {e}"}
    finally:
        conn.close()
    elapsed = round((time.monotonic() - started) * 1000)

    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    first = rows[0][0] if rows and rows[0] else None
    if isinstance(first, (bytes, bytearray)):
        first = f"<{len(first)} bytes>"
    observed_rows = len(rows)
    expect = spec.get("expect") or {}

    mismatches = []
    if "rows" in expect and observed_rows != int(expect["rows"]):
        mismatches.append({"field": "rows", "expected": expect["rows"], "observed": observed_rows})
    if "min_rows" in expect and observed_rows < int(expect["min_rows"]):
        mismatches.append({"field": "min_rows", "expected": expect["min_rows"],
                           "observed": observed_rows})
    if "equals" in expect and first != expect["equals"]:
        mismatches.append({"field": "first_value", "expected": expect["equals"],
                           "observed": first})

    evidence = {
        "path": path,
        "query": query,
        "params": spec.get("params") or [],
        "mode": "read-only (sqlite mode=ro, single SELECT/WITH)",
        "columns": columns,
        "rows_returned": observed_rows,
        "truncated": truncated,
        "first_row": [str(v)[:MAX_VALUE] for v in rows[0]][:10] if rows else [],
        "elapsed_ms": elapsed,
        "mismatches": mismatches,
    }
    return not mismatches, evidence
