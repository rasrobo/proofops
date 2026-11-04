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
_RESULTS: dict[str, tuple[bool, dict]] = {}


def set_policy(policy: CommandPolicy) -> None:
    """Install the policy for this run and clear the per-run result cache."""
    global POLICY, _RESULTS
    POLICY = policy
    _RESULTS = {}


def command_exit(spec: dict, target: str) -> tuple[bool, dict]:
    command = spec["command"]
    # Two checks may assert different things about the same command. Run it once and
    # evaluate each check's assertions against the cached output — a 90-second migration
    # replay should not execute twice because it is asserted twice.
    cached = _RESULTS.get(command)
    if cached is not None:
        ok_all, evidence = cached
        ok = ok_all
        if "stdout_contains" in spec:
            ok = ok and spec["stdout_contains"] in evidence["stdout_tail"]
        return ok, {**evidence, "reused_from_cache": True,
                    **({"expected_stdout_contains": spec["stdout_contains"],
                        "stdout_contained": spec["stdout_contains"] in evidence["stdout_tail"]}
                       if "stdout_contains" in spec else {})}

    permitted, why = POLICY.permits(command)
    if not permitted:
        return False, {"command": command, "refused": why}

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
    _RESULTS[command] = (code == want_code and not timed_out, evidence)
    return ok, evidence
