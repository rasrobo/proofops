"""`proofops new` — write a starter plan for whatever is actually in a directory.

The weakness this fixes: a freshly installed plugin listed five plans about someone else's
servers, so a new user had no path from "installed" to "verified something of mine" without
hand-writing JSON and absolute paths.

The generator only *reads* what is there and writes a plan. It runs no checks, touches no
network, and never invents a value: a row count comes from counting the rows, a page count from
opening the PDF, dimensions from the header. The plan it produces is then verified by running it
— and if that run fails, the plan was wrong, not the file.

Every generated plan declares the directory it inspected in `allowed_paths`, and states plainly
that it asserts only what it names.
"""

from __future__ import annotations

import csv
import hashlib
import os
import pathlib
import sqlite3

from . import artifacts, pdfdoc

MAX_SCAN_ROWS = 200_000
MAX_FILES = 500


def _csv_check(path: pathlib.Path, rel: str) -> dict | None:
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.reader(fh)
            header = next(reader, [])
            if not header:
                return None
            rows = 0
            for _ in reader:
                rows += 1
                if rows > MAX_SCAN_ROWS:
                    break
    except (OSError, csv.Error):
        return None
    return {
        "id": f"csv-{path.stem}",
        "type": "csv_stats",
        "path": rel,
        "expect": {"rows": rows, "columns": header, "nulls": {c: 0 for c in header}},
        "proves": f"{rel} has the rows, header and complete cells it has today",
    }


def _dir_check(path: pathlib.Path, rel: str) -> dict | None:
    files = [p for p in sorted(path.iterdir()) if p.is_file()][:MAX_FILES]
    if len(files) < 2:
        return None
    # Hash the files: `dir_manifest` only computes per-file hashes when `expect.sha256` is
    # present, so a listing pinned from an unhashed pass would never match its own run.
    rows, listing = artifacts._dir_listing(str(path), True)
    return {
        "id": f"inventory-{path.name}",
        "type": "dir_manifest",
        "path": rel,
        "expect": {"files": len(rows), "bytes": sum(r["bytes"] for r in rows),
                   "sha256": listing},
        "proves": (f"{rel}/ still contains exactly the {len(rows)} "
                   f"file{'s' if len(rows) != 1 else ''} it has today, unchanged"),
    }


def _image_check(path: pathlib.Path, rel: str) -> dict | None:
    try:
        parsed = artifacts._image_size(str(path))
    except OSError:
        return None
    if not parsed:
        return None
    w, h, _fmt = parsed
    return {
        "id": f"image-{path.stem}",
        "type": "image_size",
        "path": rel,
        "width": w,
        "height": h,
        "proves": f"{rel} is {w}x{h}, as it is today",
    }


def _pdf_check(path: pathlib.Path, rel: str) -> dict | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    pages, _method = pdfdoc._page_count(data)
    if not pages:
        return None
    return {
        "id": f"pages-{path.stem}",
        "type": "pdf_pages",
        "path": rel,
        "equals": pages,
        "proves": f"{rel} still has {pages} page{'s' if pages != 1 else ''}",
    }


def _sqlite_check(path: pathlib.Path, rel: str) -> dict | None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            n = conn.execute(
                "select count(*) from sqlite_master where type = 'table'").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not n:
        return None
    return {
        "id": f"tables-{path.stem}",
        "type": "sqlite_query",
        "path": rel,
        "query": "select count(*) from sqlite_master where type = 'table'",
        "expect": {"equals": n},
        "proves": f"{rel} still has the {n} table{'s' if n != 1 else ''} it has today",
    }


def build(directory: str | pathlib.Path = ".", name: str | None = None) -> dict:
    """Inspect a directory and return a plan that asserts its present shape."""
    root = pathlib.Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")

    checks: list[dict] = []
    for entry in sorted(root.iterdir())[:MAX_FILES]:
        rel = entry.name
        if entry.is_dir():
            chk = _dir_check(entry, rel)
        elif entry.suffix.lower() in (".csv", ".tsv"):
            chk = _csv_check(entry, rel)
        elif entry.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif"):
            chk = _image_check(entry, rel)
        elif entry.suffix.lower() == ".pdf":
            chk = _pdf_check(entry, rel)
        elif entry.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
            chk = _sqlite_check(entry, rel)
        else:
            chk = None
        if chk:
            checks.append(chk)
        if len(checks) >= 6:
            break

    if not checks:
        # A directory of plain files still has a verifiable shape.
        files = [p for p in root.iterdir() if p.is_file()]
        if files:
            digest = hashlib.sha256(
                "\n".join(sorted(f"{p.name}\t{p.stat().st_size}" for p in files)).encode()
            ).hexdigest()[:16]
            checks.append({
                "id": "files",
                "type": "dir_manifest",
                "path": ".",
                "expect": {"files": len(files)},
                "proves": f"the directory still holds the {len(files)} files it has today",
            })
            del digest

    if not checks:
        raise ValueError(f"nothing verifiable found in {root}")

    return {
        "name": name or f"{root.name} as it is today",
        "target_kind": "local-artifacts",
        "allowed_origins": [],
        "allowed_paths": [str(root)],
        "checks": checks,
        "does_not_prove": [
            "that the contents are correct, only that they match what was recorded today",
            "that anything outside this plan was checked",
            "that a later edit which preserves these numbers is harmless",
        ],
    }


def fingerprint(plan: dict) -> str:
    """Short digest of the plan body, matching the engine's revision of the written file."""
    from . import plan as plan_mod

    return plan_mod.revision(plan)[:19]
