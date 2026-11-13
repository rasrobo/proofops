"""Compare two receipts of the same plan: did the repair work, and did anything regress?

The question a receipt cannot answer on its own is the one people actually ask next: "I fixed it —
is it better now, or did I break something else?" Two runs of the same plan revision make that
answerable without re-running anything, and without trusting a summary.

Deliberately comparable-only: a diff between different plan revisions is refused by default, because
"this check passed before and fails now" means nothing if the check itself changed.
"""
from __future__ import annotations

import json
from pathlib import Path


class DiffError(Exception):
    """The two receipts cannot be meaningfully compared."""


def _load(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise DiffError(f"no such receipt: {p}")
    try:
        rec = json.loads(p.read_text())
    except ValueError as e:
        raise DiffError(f"{p} is not valid JSON: {e}") from e
    if "checks" not in rec or "plan_revision" not in rec:
        raise DiffError(f"{p} does not look like a ProofOps receipt")
    return rec


def _state(check: dict) -> str:
    """NOT RUN is its own state: collapsed into pass/fail it hides what actually happened."""
    if check.get("passed") is None:
        return "not_run"
    return "pass" if check.get("passed") else "fail"


def _observed(check: dict) -> str:
    ev = check.get("evidence") or {}
    for key in ("observed", "observed_status", "observed_rows", "observed_sha256", "error"):
        if key in ev and ev[key] not in (None, "", []):
            return str(ev[key])
    return ""


def compare(old: dict, new: dict, *, allow_revision_change: bool = False) -> dict:
    """Return a structure describing what changed between two receipts."""
    if not allow_revision_change and old.get("plan_revision") != new.get("plan_revision"):
        raise DiffError(
            "the two receipts come from different plan revisions "
            f"({old.get('plan_revision')} vs {new.get('plan_revision')}); "
            "a changed check is not a changed result — pass --allow-revision-change to compare anyway")

    o = {c["id"]: c for c in old.get("checks", [])}
    n = {c["id"]: c for c in new.get("checks", [])}

    rows = []
    for cid in [*o.keys(), *(k for k in n if k not in o)]:
        before, after = o.get(cid), n.get(cid)
        if before is None:
            assert after is not None  # the id came from `n`
            rows.append({"id": cid, "change": "added", "from": None, "to": _state(after),
                         "observed_before": "", "observed_after": _observed(after)})
        elif after is None:
            rows.append({"id": cid, "change": "removed", "from": _state(before), "to": None,
                         "observed_before": _observed(before), "observed_after": ""})
        else:
            s0, s1 = _state(before), _state(after)
            if s0 == "fail" and s1 == "pass":
                change = "fixed"
            elif s0 == "pass" and s1 == "fail":
                change = "regressed"
            elif s0 == "fail" and s1 == "fail":
                change = "still_failing"
            elif s0 == "not_run" and s1 != "not_run":
                change = "now_ran"
            elif s0 != "not_run" and s1 == "not_run":
                change = "no_longer_runs"
            else:
                change = "unchanged"
            rows.append({"id": cid, "change": change, "from": s0, "to": s1,
                         "observed_before": _observed(before), "observed_after": _observed(after)})

    order = {"regressed": 0, "still_failing": 1, "no_longer_runs": 2, "added": 3,
             "removed": 4, "fixed": 5, "now_ran": 6, "unchanged": 7}
    rows.sort(key=lambda r: (order[r["change"]], r["id"]))

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["change"]] = counts.get(r["change"], 0) + 1

    return {
        "plan": new.get("plan") or old.get("plan"),
        "plan_revision": new.get("plan_revision"),
        "old_run": old.get("run_id"),
        "new_run": new.get("run_id"),
        "verdict_before": (old.get("summary") or {}).get("verdict"),
        "verdict_after": (new.get("summary") or {}).get("verdict"),
        "counts": counts,
        "checks": rows,
        # A regression is the only thing a repair can do that is worse than nothing.
        "regressed": [r for r in rows if r["change"] == "regressed"],
    }


def render(result: dict) -> str:
    c = result["counts"]
    lines = [
        f"{result['plan']}  ({result['plan_revision']})",
        f"  before: {result['old_run']}  {result['verdict_before']}",
        f"  after:  {result['new_run']}  {result['verdict_after']}",
        "",
    ]
    summary = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(c.items()))
    lines.append(f"  {summary}")
    lines.append("")

    if result["regressed"]:
        lines.append("  Regressions — these worked before and do not now:")
        for r in result["regressed"]:
            was, now = r["observed_before"], r["observed_after"]
            detail = f" (was {was!r}, now {now!r})" if (was or now) else ""
            lines.append(f"    [REGRESSED] {r['id']}{detail}")
        lines.append("")

    for row in result["checks"]:
        if row["change"] in ("unchanged", "regressed"):
            continue
        if row["change"] == "still_failing":
            lines.append(f"    [FAIL]      {row['id']} — still failing ({row['observed_after']})")
        elif row["change"] == "fixed":
            lines.append(f"    [FIXED]     {row['id']} — was failing ({row['observed_before']})")
        elif row["change"] == "no_longer_runs":
            lines.append(f"    [NOT RUN]   {row['id']} — could not run this time")
        elif row["change"] == "now_ran":
            lines.append(f"    [RUN]       {row['id']} — ran this time ({row['to']})")
        elif row["change"] == "added":
            lines.append(f"    [ADDED]     {row['id']} — {row['to']}")
        elif row["change"] == "removed":
            lines.append(f"    [REMOVED]   {row['id']} — was {row['from']}")

    if not any(r["change"] != "unchanged" for r in result["checks"]):
        lines.append("    nothing changed: same checks, same outcomes")

    lines.append("")
    if result["regressed"]:
        lines.append("  What this does NOT prove: that the regression matters, or that the repair "
                     "caused it — only that this check answered differently on the second run.")
    else:
        lines.append("  What this does NOT prove: that the fix is correct, only that the checks "
                     "that failed now pass. Unchanged checks hide unchanged bugs.")
    return "\n".join(lines)


def exit_code(result: dict) -> int:
    """0 no regression · 1 regression · (2 is reserved for a refused comparison)."""
    return 1 if result["regressed"] else 0
