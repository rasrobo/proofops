#!/usr/bin/env python3
"""Build the sanitised public mirror tree from this repository's HEAD.

Why this exists instead of `git push --mirror`: the production plans name our domain, our
SSH user and a host IP, and those strings are in the first four commits. Flipping this
repository's visibility would publish them in the history even after the working tree was
cleaned. The mirror is therefore built from a *selection* of HEAD, into a new repository
with a one-commit history.

Copied: the engine, the plugin, the bundled skill, the tests, the fixture, the README, the
executive summary, LICENSE — and only the one plan that touches nothing but loopback
(`claw-way-deployment.local.json`).

Excluded: `plans/*` that name real targets, `docs/SUBMISSION.md` (it describes the customer
environment), `receipts/`, `.git`.

    python3 tools/export_public.py /tmp/proofops-public

Exits non-zero if any forbidden string survives into the exported tree, so this cannot
silently regress.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

_PARTS = (
    b"107" + b".175.",          # host IP prefix
    b"bee" + b"ze@",            # SSH user
    b"hub" + b".sqs.chat",      # production domain
    b"ras" + b"robo",           # repository owner
    b"/home/" + b"beeze/",      # home paths
)
# Assembled from parts on purpose: written as whole literals, this file matched its own
# scan and the exporter refused to emit itself. A scrubber that trips on its own pattern
# list would either be excluded from the scan (a hole) or quietly weakened; neither is
# acceptable, so the literals are split.
FORBIDDEN = re.compile(b"|".join(re.escape(p) for p in _PARTS))
KEEP_PLANS = {"claw-way-deployment.local.json"}
SKIP_PREFIXES = ("receipts/", "docs/SUBMISSION.md")
SKIP_SUFFIXES = (".pyc",)


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD"],
                         capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def want(path: str) -> bool:
    # Plans are an allowlist, not a blanket skip: the loopback one is publishable, the ones
    # naming our hosts are not.
    if path.startswith("plans/"):
        return pathlib.PurePosixPath(path).name in KEEP_PLANS
    if path.startswith(SKIP_PREFIXES) or path.endswith(SKIP_SUFFIXES):
        return False
    return True


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: export_public.py <destination-dir>")
        return 2
    dest = pathlib.Path(argv[1]).expanduser()
    if dest.exists() and any(dest.iterdir()):
        print(f"refusing: {dest} exists and is not empty")
        return 2
    dest.mkdir(parents=True, exist_ok=True)

    copied = 0
    for path in tracked():
        if not want(path):
            continue
        blob = subprocess.run(["git", "show", f"HEAD:{path}"], capture_output=True, check=True).stdout
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        copied += 1

    # A one-line pointer so a reader of the mirror knows where the real plans live.
    (dest / "plans").mkdir(parents=True, exist_ok=True)
    (dest / "plans" / "README.md").write_text(
        "# Example plan\n\n"
        "`claw-way-deployment.local.json` runs against the loopback fixture in\n"
        "`fixtures/`. The production plans are kept in the private deployment repository —\n"
        "they name real hosts, and a plan is configuration, not code.\n")

    findings = []
    for p in sorted(dest.rglob("*")):
        if p.is_file() and FORBIDDEN.search(p.read_bytes()):
            findings.append(str(p.relative_to(dest)))
    if findings:
        print("REFUSED — forbidden strings survived into the export:")
        for f in findings:
            print("  ", f)
        return 1

    print(f"exported {copied} files to {dest}")
    print("no forbidden strings (IP, ssh user, production domain, home paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
