"""Artifact checks — verifying claims about files, not just live services.

Why this exists: half of the expensive "done" claims are about deliverables, not endpoints.
"A thousand images were exported." "The CSV has every row." "The manifest matches what
shipped." Until now ProofOps could only answer questions about HTTP and about a command's
exit code, so the honest answer to all three was "no verification exists".

Safety model, mirroring the origin allowlist: a plan may only read inside directories it
declares in ``allowed_paths``. Paths are resolved (symlinks included) and refused if they
escape, so a copied plan cannot be pointed at ``/etc`` or at a home directory by editing one
string. Reads are bounded and never write.

All parsing is stdlib: no Pillow, no pandas — a verifier that drags a dependency tree into
someone's install is a worse trade than a 40-line PNG header reader.
"""

from __future__ import annotations

import csv
import hashlib
import os
import pathlib
import struct

MAX_FILE = 256 * 1024 * 1024      # refuse to hash more than 256 MB in one check
MAX_CSV_ROWS = 5_000_000


class PathPolicy:
    """Set by the runner before any check runs. Deny by default."""

    def __init__(self, roots: tuple[str, ...] = ()):
        self.roots = tuple(os.path.realpath(r) for r in roots)

    def resolve(self, rel: str) -> tuple[str | None, str]:
        if not rel:
            return None, "empty path"
        if os.path.isabs(rel):
            return None, f"refusing absolute path: {rel}"
        if not self.roots:
            return None, "plan declares no allowed_paths"
        candidate = os.path.realpath(os.path.join(self.roots[0], rel))
        for root in self.roots:
            if candidate == root or candidate.startswith(root + os.sep):
                return candidate, ""
        return None, (
            f"refusing {rel}: resolves outside allowed_paths "
            f"({candidate} is not under any declared root)"
        )


POLICY = PathPolicy()


def set_policy(policy: PathPolicy) -> None:
    global POLICY
    POLICY = policy


def _evidence(path: str, extra: dict | None = None) -> dict:
    ev = {"path": path}
    try:
        st = os.stat(path)
        ev["bytes"] = st.st_size
        ev["mtime"] = int(st.st_mtime)
    except OSError:
        pass
    ev.update(extra or {})
    return ev


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def file_sha256(spec: dict, _target: str) -> tuple[bool, dict]:
    path, why = POLICY.resolve(spec["path"])
    if path is None:
        return False, {"path": spec["path"], "error": why}
    if not os.path.isfile(path):
        return False, {"path": path, "error": "file does not exist"}
    if os.path.getsize(path) > MAX_FILE:
        return False, {"path": path, "error": f"file larger than the {MAX_FILE} byte cap"}
    observed = _sha256_file(path)
    want = str(spec["equals"]).lower().removeprefix("sha256:")
    return observed == want, _evidence(path, {"expected_sha256": want, "observed_sha256": observed})


def file_exists(spec: dict, _target: str) -> tuple[bool, dict]:
    path, why = POLICY.resolve(spec["path"])
    if path is None:
        return False, {"path": spec["path"], "error": why}
    exists = os.path.isfile(path)
    min_bytes = int(spec.get("min_bytes", 0))
    size = os.path.getsize(path) if exists else 0
    ok = exists and size >= min_bytes
    return ok, _evidence(path, {"exists": exists, "min_bytes": min_bytes,
                                "observed_bytes": size})


def _dir_listing(path: str, hash_files: bool) -> tuple[list[dict], str]:
    rows = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        if not os.path.isfile(full):
            continue
        row = {"name": name, "bytes": os.path.getsize(full)}
        if hash_files:
            row["sha256"] = _sha256_file(full)
        rows.append(row)
    body = "\n".join(
        f"{r['name']}\t{r['bytes']}\t{r.get('sha256', '')}" for r in rows
    )
    return rows, hashlib.sha256(body.encode()).hexdigest()


def dir_manifest(spec: dict, _target: str) -> tuple[bool, dict]:
    """Assert a directory's contents: how many files, how many bytes, and (optionally) that
    every file's bytes are the expected ones.

    The listing digest is over sorted name+size(+hash), so a renamed file, an extra file or
    a changed file all move it — which is the point: "the export contains what we shipped".
    """
    path, why = POLICY.resolve(spec["path"])
    if path is None:
        return False, {"path": spec["path"], "error": why}
    if not os.path.isdir(path):
        return False, {"path": path, "error": "directory does not exist"}
    expect = spec.get("expect") or {}
    rows, listing = _dir_listing(path, bool(expect.get("sha256")))
    actual = {"files": len(rows), "bytes": sum(r["bytes"] for r in rows), "sha256": listing}
    checks = []
    for key in ("files", "bytes", "sha256"):
        if key in expect:
            checks.append((key, expect[key], actual[key]))
    ok = all(str(a) == str(b) for _, b, a in checks)
    return ok, {
        "path": path,
        "expected": {k: v for k, _, v in checks} or "any",
        "observed": actual,
        "mismatches": [{"field": k, "expected": b, "observed": a}
                       for k, b, a in checks if str(a) != str(b)],
        "sample": rows[:5],
    }


def csv_stats(spec: dict, _target: str) -> tuple[bool, dict]:
    """Assert the shape of a CSV: row count, header, and nulls in named columns.

    Row count and nulls are the two numbers a "the data loaded fine" claim glosses over:
    a truncated export still parses, and an empty string is not a missing row.
    """
    path, why = POLICY.resolve(spec["path"])
    if path is None:
        return False, {"path": spec["path"], "error": why}
    if not os.path.isfile(path):
        return False, {"path": path, "error": "file does not exist"}
    expect = spec.get("expect") or {}
    delimiter = spec.get("delimiter", ",")
    # Count nulls for every column, not just the ones an expectation names: the first
    # version only tracked `expect["columns"]`, so a plan asserting `nulls` without also
    # listing `columns` counted nothing and passed. A blank is a blank.
    nulls: dict[str, int] = {}
    rows = 0
    blank_rows = 0
    header: list[str] = []
    try:
        # utf-8-sig, not utf-8: a BOM at the head of an exported CSV otherwise becomes part of
        # the first column's name, so an honest file fails a header assertion for a cosmetic
        # reason. (Found by the adversarial-encoding tests.)
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
            reader = csv.reader(fh, delimiter=delimiter)
            header = next(reader, [])
            nulls = {c: 0 for c in header}
            for row in reader:
                # A trailing newline is not a data row. Counting empty rows made a file
                # that merely ends with a blank line fail a row-count claim - the kind of
                # false alarm that teaches people to ignore the tool.
                if not any(cell.strip() for cell in row):
                    blank_rows += 1
                    continue
                rows += 1
                if rows > MAX_CSV_ROWS:
                    return False, {"path": path, "error": f"more than {MAX_CSV_ROWS} rows"}
                for i, col in enumerate(header):
                    if i >= len(row) or row[i].strip() == "":
                        nulls[col] += 1
    except (OSError, csv.Error) as e:
        return False, {"path": path, "error": f"{type(e).__name__}: {e}"}

    observed = {"rows": rows, "columns": header, "nulls": nulls, "blank_rows": blank_rows}
    mismatches = []
    if "rows" in expect and rows != int(expect["rows"]):
        mismatches.append({"field": "rows", "expected": expect["rows"], "observed": rows})
    if "columns" in expect and header != list(expect["columns"]):
        mismatches.append({"field": "columns", "expected": expect["columns"], "observed": header})
    for col, want in (expect.get("nulls") or {}).items():
        if col not in header:
            mismatches.append({"field": f"nulls.{col}", "expected": want,
                               "observed": "column missing"})
        elif nulls.get(col, 0) != int(want):
            mismatches.append({"field": f"nulls.{col}", "expected": want,
                               "observed": nulls[col]})
    return not mismatches, {"path": path, "observed": observed, "mismatches": mismatches}


def _image_size(path: str) -> tuple[int, int, str] | None:
    """Read width/height from PNG, GIF or JPEG headers without decoding pixels."""
    with open(path, "rb") as fh:
        head = fh.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
            w, h = struct.unpack(">II", head[16:24])
            return w, h, "png"
        if head[:6] in (b"GIF87a", b"GIF89a"):
            w, h = struct.unpack("<HH", head[6:10])
            return w, h, "gif"
        if head[:2] == b"\xff\xd8":
            fh.seek(2)
            while True:
                marker = fh.read(2)
                if len(marker) < 2:
                    return None
                if marker[0] != 0xFF:
                    return None
                code = marker[1]
                if code in (0xD8, 0xD9) or 0xD0 <= code <= 0xD7:
                    continue
                raw = fh.read(2)
                if len(raw) < 2:
                    return None
                seg_len = struct.unpack(">H", raw)[0]
                if code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    body = fh.read(5)
                    h, w = struct.unpack(">HH", body[1:5])
                    return w, h, "jpeg"
                fh.seek(seg_len - 2, 1)
    return None


def image_size(spec: dict, _target: str) -> tuple[bool, dict]:
    path, why = POLICY.resolve(spec["path"])
    if path is None:
        return False, {"path": spec["path"], "error": why}
    if not os.path.isfile(path):
        return False, {"path": path, "error": "file does not exist"}
    try:
        parsed = _image_size(path)
    except OSError as e:
        return False, {"path": path, "error": f"{type(e).__name__}: {e}"}
    if parsed is None:
        return False, {"path": path, "error": "not a PNG, GIF or JPEG (header not recognised)"}
    w, h, fmt = parsed
    want_w, want_h = int(spec["width"]), int(spec["height"])
    ok = (w, h) == (want_w, want_h)
    return ok, {"path": path, "format": fmt, "expected": f"{want_w}x{want_h}",
                "observed": f"{w}x{h}"}
