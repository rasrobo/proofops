"""Command checks — the one place ProofOps can cause side effects, so it is fenced twice.

A plan may only run a command that it lists **verbatim** in `allowed_commands`, and the
CLI must be invoked with `--allow-commands`. Both must hold:

  * the plan author opted in by naming the exact command string
  * the operator opted in for this run

Neither alone is enough, so a plan copied from elsewhere cannot execute anything, and a
careless `--allow-commands` cannot run a command the plan never declared. There is no
shell: the command is split with shlex and executed without a shell, so pipes, `&&` and
redirection are not available to a plan.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import time

TIMEOUT = 300
MAX_OUTPUT = 4000


class CommandPolicy:
    """Set by the CLI before any check runs. Deny by default."""

    def __init__(self, enabled: bool = False, allowed: tuple[str, ...] = ()):
        self.enabled = enabled
        self.allowed = tuple(allowed)

    def permits(self, command: str) -> tuple[bool, str]:
        if not self.enabled:
            return False, "commands are disabled for this run (pass --allow-commands)"
        if command not in self.allowed:
            return False, (
                "command is not declared in the plan's allowed_commands — add it verbatim "
                "if this is intended"
            )
        return True, ""


POLICY = CommandPolicy()
# Values are (verdict, evidence), where verdict is True (passed), False (failed) or None
# (refused — the command never ran). A refusal is a third outcome, not a failure; see
# ``command_exit``.
_RESULTS: dict[str, tuple[bool | None, dict]] = {}


def set_policy(policy: CommandPolicy) -> None:
    """Install the policy for this run and clear the per-run result cache."""
    global POLICY, _RESULTS
    POLICY = policy
    _RESULTS = {}


def _extract(spec: dict, text: str, evidence: dict) -> dict:
    """Pull a declared value out of the output as readable evidence.

    A failing check whose evidence is a 4,000-character truncated tail makes the reader
    re-run the command to learn how bad the failure is. ``extract`` names the number the
    receipt should show — ``schema drift: 39`` rather than "exit 1".

    Extraction is enrichment, never an assertion: a pattern that does not match records
    ``extract_error`` and leaves the check's pass/fail verdict untouched. Silently
    inventing a value, or failing a check because a log line changed, would both be lies
    about what was tested.
    """
    ex = spec.get("extract")
    if not ex:
        return evidence
    # One extract block or a list of them: a drift report carries both the count and the
    # table total, and a receipt should show both without a second 35-second run.
    items = ex if isinstance(ex, list) else [ex]
    out = dict(evidence)
    values: dict[str, str | None] = {}
    errors: list[str] = []
    for item in items:
        name = item.get("name", "value")
        pattern = item["regex"]
        group = int(item.get("group", 1))
        match = re.search(pattern, text, re.MULTILINE)
        values[name] = match.group(group) if match else None
        if match is None:
            errors.append(f"{name}: pattern not found in output: {pattern!r}")
    out["extracted"] = values
    if errors:
        out["extract_error"] = "; ".join(errors)
    return out


def command_exit(spec: dict, target: str) -> tuple[bool | None, dict]:
    command = spec["command"]
    # Two checks may assert different things about the same command. Run it once and
    # evaluate each check's assertions against the cached output — a 90-second migration
    # replay should not execute twice because it is asserted twice.
    cached = _RESULTS.get(command)
    if cached is not None:
        ok_all, cached_evidence = cached
        # Extraction is per-check, so it must not ride along from whichever check happened
        # to run the command first.
        evidence = {k: v for k, v in cached_evidence.items()
                    if k not in ("extracted", "extract_error")}
        ok = ok_all
        if "stdout_contains" in spec:
            contained = spec["stdout_contains"] in evidence["stdout_tail"]
            ok = ok and contained
            evidence["expected_stdout_contains"] = spec["stdout_contains"]
            evidence["stdout_contained"] = contained
        evidence["reused_from_cache"] = True
        return ok, _extract(spec, evidence["stdout_tail"], evidence)

    permitted, why = POLICY.permits(command)
    if not permitted:
        # A refusal is NOT a failed assertion. Recording it as one writes "the deployed
        # configuration failed validation" into a receipt for a command that never ran —
        # the exact overclaim this tool exists to prevent. It is a third outcome, and the
        # CLI exits 2 for it (the run could not be performed).
        return None, {"command": command, "status": "not_run", "refused": why}

    argv = shlex.split(command)
    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, no shell, allowlisted verbatim
            argv, capture_output=True, text=True, timeout=spec.get("timeout", TIMEOUT)
        )
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        stdout, stderr, code, timed_out = "", "", None, True

    elapsed = round((time.monotonic() - started) * 1000)
    want_code = int(spec.get("expect_exit", 0))
    ok = (code == want_code) and not timed_out

    if ok and "stdout_contains" in spec:
        ok = spec["stdout_contains"] in stdout

    evidence = {
        "command": command,
        "argv": argv,
        "expected_exit": want_code,
        "observed_exit": code,
        "timed_out": timed_out,
        "elapsed_ms": elapsed,
        "stdout_tail": stdout[-MAX_OUTPUT:],
        "stderr_tail": stderr[-MAX_OUTPUT:],
    }
    if "stdout_contains" in spec:
        evidence["expected_stdout_contains"] = spec["stdout_contains"]
        evidence["stdout_contained"] = spec["stdout_contains"] in stdout
    # Cache the exit-level verdict; per-check stdout assertions are re-evaluated above.
    _RESULTS[command] = (code == want_code and not timed_out, dict(evidence))
    return ok, _extract(spec, stdout + "\n" + stderr, evidence)
