"""Held-out eval: 20 cases proofops was not tuned against.

The dev benchmark (bench/run_bench.py) measures detection over injected defects in
one corpus. This eval asks the question a buyer asks instead: given a fresh claim —
true or false — does the verifier return the right verdict? Twenty cases, each a
(plan, fixture-state) pair with ground truth known by construction:

  * 10 expected PASS: the claim is true, the plan should return PASS.
  * 10 expected FAIL: the claim is false, the plan should return FAIL.

Fixtures are all generated here (CSV / PNG / PDF / SQLite / a loopback HTTP server),
so the run is deterministic and offline-safe: no network fetches, no public datasets,
nothing the tool was tuned against. The PNG/PDF generators are copied from
bench/run_bench.py — the fixture mechanics, not its defects.

Metrics are framed like check-please's published eval (precision / recall), so the
numbers are directly comparable:

  * TP: true claim, PASS.  FP: false claim, PASS (the dangerous one).
  * FN: true claim, FAIL (cry wolf).  TN: false claim, FAIL.
  * precision = TP / (TP + FP), recall = TP / (TP + FN), accuracy = (TP + TN) / 20.

    python3 bench/run_eval.py

Exit code 0 only when all 20 verdicts match ground truth (precision and recall both
1.0). Any mismatch — including a check that could not run (INCOMPLETE) — exits
non-zero and names the case.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.server
import io
import json
import pathlib
import shutil
import sqlite3
import struct
import sys
import tempfile
import threading
import time
import zlib
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import proofops  # noqa: E402
from proofops import artifacts, runner  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "eval-latest.json"
REPORT = HERE / "EVAL.md"


# ----------------------------------------------------------------- fixture generators
# (copied from bench/run_bench.py: the deterministic fixture mechanics)
def png_bytes(w: int, h: int, seed: int = 0) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    rows = []
    for y in range(h):
        row = bytearray(b"\x00")
        for x in range(w):
            row += bytes(((x * 7 + seed) % 256, (y * 5 + seed) % 256, 90))
        rows.append(bytes(row))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def make_pdf(pages: list[str], size: tuple[int, int] = (595, 842)) -> bytes:
    """A minimal well-formed PDF, so the document plan has deterministic ground truth."""
    w, h = size
    objs: dict[int, bytes] = {}
    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode()
    objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for i, text in enumerate(pages):
        body = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
        objs[4 + 2 * i] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] "
                           f"/Resources << /Font << /F1 3 0 R >> >> "
                           f"/Contents {5 + 2 * i} 0 R >>").encode()
        objs[5 + 2 * i] = (f"<< /Length {len(body)} >>".encode()
                           + b"\nstream\n" + body + b"\nendstream")
    out = bytearray(b"%PDF-1.7\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref_at = len(out)
    total = max(objs) + 1
    out += f"xref\n0 {total}\n".encode() + b"0000000000 65535 f \n"
    for num in range(1, total):
        out += f"{offsets.get(num, 0):010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n").encode()
    return bytes(out)


# ----------------------------------------------------------------- the corpus
# A small roster CSV. Nulls are real and counted: age blank in 2 rows, city in 2.
CSV_HEADER = ["id", "name", "age", "city"]
CSV_ROWS = [
    ["1", "ana", "34", "raleigh"],
    ["2", "ben", "", "durham"],      # age null
    ["3", "cid", "29", ""],          # city null
    ["4", "dan", "41", "cary"],
    ["5", "eve", "", ""],            # age null, city null
    ["6", "fay", "52", "apex"],      # complete row: dropping it changes only the count
]
CSV_NULLS = {"id": 0, "name": 0, "age": 2, "city": 2}

# The export directory: four small files with distinct contents.
EXPORT_FILES = {
    "a.txt": b"alpha export 001\n",
    "b.txt": b"beta export 002\n",
    "c.txt": b"gamma export 003\n",
    "d.txt": b"delta export 004\n",
}

# The release artifact: one file whose bytes the plan pins by SHA-256.
ARTIFACT_NAME = "release.bin"
ARTIFACT_BYTES = bytes(range(256)) * 4  # 1 KiB of deterministic bytes
ARTIFACT_BYTES_CHANGED = bytes(range(256)) * 3 + b"\x00" * 256  # same size, one block differs

# The report: three A4 pages, the landmark string on page one.
PDF_PAGES = ["Quarterly Report 2026", "Revenue by region", "Risks and outlook"]
PDF_LANDMARK = "Quarterly Report 2026"

# The system of record: message ids and their sent flag.
DB_ROWS_PASS = [(66, 1), (143, 1), (200, 1)]   # 143 was sent
DB_ROWS_FAIL = [(66, 1), (200, 1)]             # 143 was never recorded
DB_QUERY = "select count(*) from messages where id = ? and sent = 1"
DB_MSG_ID = 143


def _write_csv(path: pathlib.Path, header: list[str], rows: list[list[str]]) -> None:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows([header] + rows)
    path.write_text(buf.getvalue())


def _seed_db(path: pathlib.Path, rows: list[tuple[int, int]]) -> None:
    conn = sqlite3.connect(path)
    conn.execute("create table messages (id integer primary key, sent integer, body text)")
    for i, sent in rows:
        conn.execute("insert into messages (id, sent, body) values (?,?,?)",
                     (i, sent, f"message {i}"))
    conn.commit()
    conn.close()


def _listing_digest(export_dir: pathlib.Path) -> str:
    """The dir_manifest sha256 for a directory, as the check itself computes it."""
    _, listing = artifacts._dir_listing(str(export_dir), True)
    return listing


# ----------------------------------------------------------------- loopback HTTP server
class _Handler(http.server.BaseHTTPRequestHandler):
    """One server, one route per claim, so no case shares mutable state with another."""

    def _send(self, code: int, body: bytes, ctype: str = "text/plain",
              extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        if self.path == "/health":
            self._send(200, b'{"status": "ok", "uptime_s": 3600}', "application/json")
        elif self.path == "/health-degraded":
            self._send(200, b'{"status": "degraded", "uptime_s": 3600}', "application/json")
        elif self.path == "/ready":
            self._send(200, b"service ready: all systems nominal \xe2\x80\x94 version 2.4.1")
        elif self.path == "/version":
            self._send(200, b"ok", extra={"X-App-Version": "1.2.3"})
        elif self.path == "/missing":
            self._send(404, b"not found")
        else:
            self._send(404, b"no such route")

    def log_message(self, *args) -> None:  # keep the eval output clean
        pass


def start_server() -> tuple[http.server.ThreadingHTTPServer, str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}"


# ----------------------------------------------------------------- cases
# Each case: id, claim, expected verdict, what it proves, the checks, and a
# builder that writes the fixture state into the case's temp dir. The plan is
# built from the checks at run time so the fixture's true values (hashes, the
# listing digest, the server origin) are pinned from what was actually built.
def plan_body(name: str, checks: list[dict], root: pathlib.Path,
              origin: str | None = None,
              allowed_commands: list[str] | None = None) -> dict:
    body: dict = {
        "name": name,
        "target_kind": "http-service" if origin else "local-artifacts",
        "allowed_origins": [origin] if origin else [],
        "allowed_paths": [str(root)],
        "checks": checks,
        "does_not_prove": ["anything the plan does not assert"],
    }
    if allowed_commands:
        body["allowed_commands"] = allowed_commands
    return body


def _check(cid: str, ctype: str, proves: str, **fields) -> dict:
    return {"id": cid, "type": ctype, "proves": proves, **fields}


CASES: list[dict] = []


def case(cid: str, claim: str, expected: str, proves: str):
    def deco(fn):
        CASES.append({"id": cid, "claim": claim, "expected": expected,
                      "proves": proves, "build": fn})
        return fn
    return deco


# --- expected PASS (the claim is true) ------------------------------------
@case("E01", "the service is up and reports status ok", "PASS",
      "a 200 plus a healthy status field together mean 'up', not just 'reachable'")
def _e01(root: pathlib.Path, origin: str):
    return plan_body("eval E01: HTTP 200 and status ok", [
        _check("status-200", "http_status", "the endpoint answers 200",
               path="/health", expect=200),
        _check("status-ok", "http_json_field", "the app reports status ok",
               path="/health", field="status", equals="ok"),
    ], root, origin=origin)


@case("E02", "the readiness page says all systems nominal", "PASS",
      "the body carries the expected readiness string")
def _e02(root: pathlib.Path, origin: str):
    return plan_body("eval E02: HTTP body contains the readiness string", [
        _check("ready-text", "http_body_contains", "the body says all systems nominal",
               path="/ready", contains="all systems nominal"),
    ], root, origin=origin)


@case("E03", "the service reports version 1.2.3", "PASS",
      "the response header carries the expected version")
def _e03(root: pathlib.Path, origin: str):
    return plan_body("eval E03: HTTP header has the expected version", [
        _check("version-header", "http_header", "the version header is 1.2.3",
               path="/version", header="X-App-Version", equals="1.2.3"),
    ], root, origin=origin)


@case("E04", "the release artifact exists with the expected SHA-256", "PASS",
      "existence plus exact bytes pins the artifact, not just its name")
def _e04(root: pathlib.Path, origin: str):
    (root / ARTIFACT_NAME).write_bytes(ARTIFACT_BYTES)
    digest = hashlib.sha256(ARTIFACT_BYTES).hexdigest()
    return plan_body("eval E04: release artifact exists with the expected hash", [
        _check("exists", "file_exists", "the artifact file is present",
               path=ARTIFACT_NAME),
        _check("hash", "file_sha256", "the artifact bytes are the expected ones",
               path=ARTIFACT_NAME, equals=digest),
    ], root)


@case("E05", "the roster CSV has 6 rows, the expected header and null counts", "PASS",
      "row count, header and per-column nulls match the source")
def _e05(root: pathlib.Path, origin: str):
    _write_csv(root / "roster.csv", CSV_HEADER, CSV_ROWS)
    return plan_body("eval E05: roster CSV shape and nulls", [
        _check("roster", "csv_stats", "rows, header and nulls match",
               path="roster.csv",
               expect={"rows": 6, "columns": CSV_HEADER, "nulls": CSV_NULLS}),
    ], root)


@case("E06", "the export directory holds 4 files with the expected listing", "PASS",
      "file count plus the listing digest pins the whole export")
def _e06(root: pathlib.Path, origin: str):
    export = root / "export"
    export.mkdir()
    for name, data in EXPORT_FILES.items():
        (export / name).write_bytes(data)
    return plan_body("eval E06: export directory manifest", [
        _check("manifest", "dir_manifest", "four files, listing digest matches",
               path="export",
               expect={"files": 4, "sha256": _listing_digest(export)}),
    ], root)


@case("E07", "the thumbnail is 320x240", "PASS",
      "the image dimensions are the expected ones")
def _e07(root: pathlib.Path, origin: str):
    (root / "thumb.png").write_bytes(png_bytes(320, 240, seed=7))
    return plan_body("eval E07: thumbnail dimensions", [
        _check("dims", "image_size", "the thumbnail is 320x240",
               path="thumb.png", width=320, height=240),
    ], root)


@case("E08", "the report is 3 A4 pages and carries its landmark heading", "PASS",
      "page count, page size and the landmark string together describe the document")
def _e08(root: pathlib.Path, origin: str):
    (root / "report.pdf").write_bytes(make_pdf(PDF_PAGES))
    return plan_body("eval E08: report pages, size and landmark", [
        _check("pages", "pdf_pages", "the report has three pages",
               path="report.pdf", equals=3),
        _check("page-size", "pdf_page_size", "the page is A4",
               path="report.pdf", width=595, height=842),
        _check("landmark", "pdf_text_contains", "the report carries its heading",
               path="report.pdf", contains=PDF_LANDMARK),
    ], root)


@case("E09", "message 143 is recorded as sent", "PASS",
      "the system of record holds the claimed row with sent=1")
def _e09(root: pathlib.Path, origin: str):
    _seed_db(root / "dc.db", DB_ROWS_PASS)
    return plan_body("eval E09: message 143 in the system of record", [
        _check("message-143", "sqlite_query", "message 143 exists and is marked sent",
               path="dc.db", query=DB_QUERY, params=[DB_MSG_ID],
               expect={"equals": 1}),
    ], root)


@case("E10", "the smoke-test command exits 0", "PASS",
      "a declared command, run with operator approval, exits cleanly")
def _e10(root: pathlib.Path, origin: str):
    return plan_body("eval E10: smoke-test command exits 0", [
        _check("smoke", "command_exit", "the smoke test exits 0",
               command="true", expect_exit=0),
    ], root, allowed_commands=["true"])


# --- expected FAIL (the claim is false) ------------------------------------
@case("E11", "the service is up and reports status ok (it reports degraded)", "FAIL",
      "a 200 with a degraded status field must not pass as healthy")
def _e11(root: pathlib.Path, origin: str):
    return plan_body("eval E11: HTTP 200 but status degraded", [
        _check("status-200", "http_status", "the endpoint answers 200",
               path="/health-degraded", expect=200),
        _check("status-ok", "http_json_field", "the app reports status ok",
               path="/health-degraded", field="status", equals="ok"),
    ], root, origin=origin)


@case("E12", "the endpoint answers 200 (it answers 404)", "FAIL",
      "a missing endpoint must not pass a 200 assertion")
def _e12(root: pathlib.Path, origin: str):
    return plan_body("eval E12: endpoint returns 404", [
        _check("status-200", "http_status", "the endpoint answers 200",
               path="/missing", expect=200),
    ], root, origin=origin)


@case("E13", "the release artifact exists with the expected SHA-256 (bytes differ)", "FAIL",
      "a changed artifact must fail its hash assertion even though it exists")
def _e13(root: pathlib.Path, origin: str):
    (root / ARTIFACT_NAME).write_bytes(ARTIFACT_BYTES_CHANGED)
    digest = hashlib.sha256(ARTIFACT_BYTES).hexdigest()  # the bytes it *should* have
    return plan_body("eval E13: release artifact hash mismatch", [
        _check("hash", "file_sha256", "the artifact bytes are the expected ones",
               path=ARTIFACT_NAME, equals=digest),
    ], root)


@case("E14", "the roster CSV has 6 rows (it has 5)", "FAIL",
      "a CSV short by one row must fail its row-count assertion")
def _e14(root: pathlib.Path, origin: str):
    # Drop the last row: it is complete, so only the count changes, not the nulls.
    _write_csv(root / "roster.csv", CSV_HEADER, CSV_ROWS[:-1])
    return plan_body("eval E14: roster CSV short by one row", [
        _check("roster", "csv_stats", "rows, header and nulls match",
               path="roster.csv",
               expect={"rows": 6, "columns": CSV_HEADER, "nulls": CSV_NULLS}),
    ], root)


@case("E15", "the export directory holds 4 files (one is missing)", "FAIL",
      "a manifest missing a file must fail on count and on the listing digest")
def _e15(root: pathlib.Path, origin: str):
    export = root / "export"
    export.mkdir()
    for name, data in list(EXPORT_FILES.items())[:-1]:  # d.txt is missing
        (export / name).write_bytes(data)
    # The plan asserts the *complete* export: 4 files and its listing digest.
    complete = root / "complete"
    complete.mkdir()
    for name, data in EXPORT_FILES.items():
        (complete / name).write_bytes(data)
    return plan_body("eval E15: export directory missing one file", [
        _check("manifest", "dir_manifest", "four files, listing digest matches",
               path="export",
               expect={"files": 4, "sha256": _listing_digest(complete)}),
    ], root)


@case("E16", "the thumbnail is 320x240 (it is 640x480)", "FAIL",
      "an image with the wrong dimensions must fail its size assertion")
def _e16(root: pathlib.Path, origin: str):
    (root / "thumb.png").write_bytes(png_bytes(640, 480, seed=7))
    return plan_body("eval E16: thumbnail wrong dimensions", [
        _check("dims", "image_size", "the thumbnail is 320x240",
               path="thumb.png", width=320, height=240),
    ], root)


@case("E17", "the report is 3 A4 pages (it has 2)", "FAIL",
      "a report with fewer pages must fail its page-count assertion")
def _e17(root: pathlib.Path, origin: str):
    (root / "report.pdf").write_bytes(make_pdf(PDF_PAGES[:2]))
    return plan_body("eval E17: report has fewer pages than expected", [
        _check("pages", "pdf_pages", "the report has three pages",
               path="report.pdf", equals=3),
        _check("page-size", "pdf_page_size", "the page is A4",
               path="report.pdf", width=595, height=842),
        _check("landmark", "pdf_text_contains", "the report carries its heading",
               path="report.pdf", contains=PDF_LANDMARK),
    ], root)


@case("E18", "the report carries its landmark heading (it does not)", "FAIL",
      "a report missing its landmark text must fail its text assertion")
def _e18(root: pathlib.Path, origin: str):
    (root / "report.pdf").write_bytes(
        make_pdf(["Quarterly Summary", "Revenue by region", "Risks and outlook"]))
    return plan_body("eval E18: report missing its landmark text", [
        _check("pages", "pdf_pages", "the report has three pages",
               path="report.pdf", equals=3),
        _check("page-size", "pdf_page_size", "the page is A4",
               path="report.pdf", width=595, height=842),
        _check("landmark", "pdf_text_contains", "the report carries its heading",
               path="report.pdf", contains=PDF_LANDMARK),
    ], root)


@case("E19", "message 143 is recorded as sent (no such row)", "FAIL",
      "a message id with no row in the system of record must not pass")
def _e19(root: pathlib.Path, origin: str):
    _seed_db(root / "dc.db", DB_ROWS_FAIL)
    return plan_body("eval E19: message 143 has no row", [
        _check("message-143", "sqlite_query", "message 143 exists and is marked sent",
               path="dc.db", query=DB_QUERY, params=[DB_MSG_ID],
               expect={"equals": 1}),
    ], root)


@case("E20", "the smoke-test command exits 0 (it exits 1)", "FAIL",
      "a declared command that exits non-zero must fail its exit assertion")
def _e20(root: pathlib.Path, origin: str):
    return plan_body("eval E20: smoke-test command exits non-zero", [
        _check("smoke", "command_exit", "the smoke test exits 0",
               command="false", expect_exit=0),
    ], root, allowed_commands=["false"])


# ----------------------------------------------------------------- runner
def run_case(case: dict, origin: str, workdir: pathlib.Path) -> dict:
    root = workdir / case["id"]
    root.mkdir(parents=True, exist_ok=True)
    plan = case["build"](root, origin)
    plan_file = workdir / f"{case['id']}-plan.json"
    plan_file.write_text(json.dumps(plan, indent=2))
    checks = [c["type"] for c in plan["checks"]]
    has_http = any(c.startswith("http_") for c in checks)
    allow_commands = bool(plan.get("allowed_commands"))
    target = origin if has_http else "local"
    started = time.monotonic()
    try:
        rec, _ = runner.execute(
            str(plan_file), target, out=str(workdir / f"{case['id']}-receipts"),
            allow_commands=allow_commands, allow_local_targets=has_http)
        verdict = rec["summary"]["verdict"]
        failed = [c["id"] for c in rec["checks"] if c["passed"] is False]
        not_run = [c["id"] for c in rec["checks"] if c["passed"] is None]
        evidence = {c["id"]: {"passed": c["passed"], "evidence": c["evidence"]}
                    for c in rec["checks"]}
    except Exception as e:  # a broken run must not read as a verdict either way
        verdict = "ERROR"
        failed, not_run = [], []
        evidence = {"error": f"{type(e).__name__}: {e}"}
    return {
        "id": case["id"],
        "claim": case["claim"],
        "expected": case["expected"],
        "actual": verdict,
        "match": verdict == case["expected"],
        "checks": checks,
        "failed_checks": failed,
        "not_run_checks": not_run,
        "check_evidence": evidence,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "proves": case["proves"],
    }


def write_report(results: list[dict], metrics: dict, generated_at: str) -> None:
    lines = [
        "# proofops held-out eval — 20 cases",
        "",
        "Twenty fresh (plan, fixture) pairs proofops was not tuned against: 10 true",
        "claims that should PASS, 10 false claims that should FAIL. Fixtures are all",
        "generated locally (CSV / PNG / PDF / SQLite / a loopback HTTP server), so the",
        "run is deterministic and offline-safe. Run with `python3 bench/run_eval.py`; the",
        "full per-case results are in `bench/eval-latest.json`.",
        "",
        f"Generated {generated_at} · proofops {proofops.__version__} · "
        f"script {metrics['eval_script_sha256']}",
        "",
        "## Results",
        "",
        f"- **Precision {metrics['precision']:.3f}** "
        f"({metrics['tp']} true passes / {metrics['tp'] + metrics['fp']} passes returned)",
        f"- **Recall {metrics['recall']:.3f}** "
        f"({metrics['tp']} true passes / {metrics['tp'] + metrics['fn']} true claims)",
        f"- **Accuracy {metrics['accuracy']:.3f}** "
        f"({metrics['matches']} / 20 verdicts match ground truth)",
        f"- TP {metrics['tp']} · FP {metrics['fp']} · FN {metrics['fn']} · "
        f"TN {metrics['tn']}"
        + (f" · other (INCOMPLETE/ERROR) {metrics['other']}" if metrics["other"] else ""),
        "",
        "## Cases",
        "",
        "| case | claim | expected | actual | what it proves |",
        "|------|-------|----------|--------|----------------|",
    ]
    for r in results:
        mark = "✓" if r["match"] else "✗ MISMATCH"
        lines.append(f"| {r['id']} | {r['claim']} | {r['expected']} | {r['actual']} "
                     f"{mark} | {r['proves']} |")
    lines.append("")
    lines.append("## Reading the numbers")
    lines.append("")
    lines.append("Precision is the dangerous direction: a false claim that returns PASS is a")
    lines.append("verifier telling you a lie is true. Recall is the noisy direction: a true")
    lines.append("claim that returns FAIL is a verifier crying wolf.")
    if metrics["fp"] == 0 and metrics["fn"] == 0:
        lines.append("This run has neither — every true claim passed and every false claim")
        lines.append("failed — so both are 1.000.")
    else:
        lines.append(f"This run has {metrics['fp']} false pass(es) and "
                     f"{metrics['fn']} false alarm(s); the mismatching cases are marked "
                     "✗ MISMATCH in the table above and detailed in eval-latest.json.")
    lines.append("The two headline cases are E11 (HTTP 200 but the app reports degraded) and")
    lines.append("E19 (message 143 claimed sent, no row in the system of record): the two")
    lines.append("shapes of overclaim the tool exists to catch.")
    lines.append("")
    lines.append("## What this does not prove")
    lines.append("")
    lines.append("Twenty cases on generated fixtures, not production traffic. It measures")
    lines.append("whether the checks return the right verdict on claims whose truth is known")
    lines.append("by construction — not whether a plan written by a model asserts the right")
    lines.append("things in the first place. A plan that never checks the database can still")
    lines.append("pass a claim that is false in the database; that failure is in the plan,")
    lines.append("not in the checks, and this eval does not cover it.")
    lines.append("")
    REPORT.write_text("\n".join(lines))
    print(f"report: {REPORT}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-workdir", action="store_true",
                    help="keep the temp fixtures instead of deleting them")
    args = ap.parse_args()

    print(f"proofops held-out eval · {len(CASES)} cases · proofops {proofops.__version__}\n")
    server, origin = start_server()
    print(f"loopback server: {origin} (no external network)\n")
    work = pathlib.Path(tempfile.mkdtemp(prefix="proofops-eval-"))
    results: list[dict] = []
    try:
        for case in CASES:
            results.append(run_case(case, origin, work))
            r = results[-1]
            mark = "✓" if r["match"] else "✗ MISMATCH"
            print(f"  {r['id']}  expected {r['expected']:<4} actual {r['actual']:<10} "
                  f"{mark}  {r['claim']}")
    finally:
        server.shutdown()
        server.server_close()
        if not args.keep_workdir:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"\nworkdir kept: {work}")

    tp = sum(1 for r in results if r["expected"] == "PASS" and r["actual"] == "PASS")
    fp = sum(1 for r in results if r["expected"] == "FAIL" and r["actual"] == "PASS")
    fn = sum(1 for r in results if r["expected"] == "PASS" and r["actual"] == "FAIL")
    tn = sum(1 for r in results if r["expected"] == "FAIL" and r["actual"] == "FAIL")
    other = sum(1 for r in results if r["actual"] not in ("PASS", "FAIL"))
    matches = sum(1 for r in results if r["match"])
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    accuracy = matches / len(results)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metrics = {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn, "other": other,
        "matches": matches, "total": len(results),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "accuracy": round(accuracy, 4),
    }

    print(f"\nTP {tp} · FP {fp} · FN {fn} · TN {tn}"
          + (f" · other {other}" if other else ""))
    print(f"precision {precision:.3f} · recall {recall:.3f} · accuracy {accuracy:.3f} "
          f"({matches}/{len(results)} match)")
    mismatches = [r for r in results if not r["match"]]
    if mismatches:
        print("\nmismatches:")
        for r in mismatches:
            print(f"  {r['id']}: expected {r['expected']}, got {r['actual']} — {r['claim']}")

    summary = {
        "generated_at": generated_at,
        "eval_script_sha256": hashlib.sha256(
            pathlib.Path(__file__).read_bytes()).hexdigest()[:16],
        "proofops_version": proofops.__version__,
        "python": sys.version.split()[0],
        "cases": len(results),
        "metrics": metrics,
        "results": results,
    }
    OUT.write_text(json.dumps(summary, indent=2))
    print(f"\nfull results: {OUT}")
    write_report(results, {**metrics,
                           "eval_script_sha256": summary["eval_script_sha256"]},
                 generated_at)

    ok = matches == len(results) and precision == 1.0 and recall == 1.0
    print("\neval:", "PASS" if ok else "REVIEW")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
