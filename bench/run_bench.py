"""Benchmark: how many *real* defects does a plan actually catch?

The question a verifier should answer about itself is not "do my checks pass" but "what is my
detection rate, and what do I flag when nothing is wrong". This harness measures both against
a corpus where the ground truth is known by construction:

  * a real public dataset (a CSV of countries/continents, fetched, not invented), and
  * a deterministic synthetic image export (PNGs generated here, labelled as synthetic).

Each defect is applied to a *copy*, one at a time, and every plan is run against it. A defect
counts as caught when the plan's verdict is FAIL. A benign change counts as a false alarm when
the verdict is FAIL — flagging a reformatted file is not a catch, it is noise that trains
people to ignore the tool.

Three plans of increasing strictness are measured, because the interesting result is not
"strict is best": a checksum catches everything and also flags a file that was merely
re-saved. The trade-off is the product.

    python3 bench/run_bench.py [--offline]

Exit code 0 only when the strict plan catches every defect and the structural plan raises no
false alarm on the benign variants.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import pathlib
import shutil
import struct
import sys
import tempfile
import urllib.request
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from proofops import artifacts, runner  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
CORPUS = HERE / "corpus"
CSV_URL = "https://raw.githubusercontent.com/cs109/2014_data/master/countries.csv"
CSV_NAME = "countries.csv"
# A second, independently published dataset whose real missing values make the null assertions
# non-trivial: countries.csv has none, titanic.csv has 177 / 687 / 2.
CSV2_URL = "https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv"
CSV2_NAME = "titanic.csv"
OUT = HERE / "latest.json"


# ----------------------------------------------------------------- corpus
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


def fetch_csv(offline: bool, url: str = CSV_URL, name: str = CSV_NAME
              ) -> tuple[pathlib.Path, str]:
    CORPUS.mkdir(parents=True, exist_ok=True)
    dest = CORPUS / name
    if dest.exists():
        return dest, f"cached {dest.relative_to(HERE.parent)}"
    if offline:
        raise SystemExit(f"--offline and no cached {name}; run once with network")
    with urllib.request.urlopen(url, timeout=30) as r:
        dest.write_bytes(r.read())
    return dest, url


def csv_shape(text: str) -> tuple[list[str], int, dict[str, int]]:
    """Rows, header and per-column nulls, counted from the file itself."""
    rows = list(csv.reader(io.StringIO(text)))
    header, body = rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]
    nulls = {h: sum(1 for r in body if i >= len(r) or r[i].strip() == "")
             for i, h in enumerate(header)}
    return header, len(body), nulls


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


def seed_mail_db(path: pathlib.Path) -> None:
    """A system-of-record with a known state: the claim 'sent 66 and 143' can be tested."""
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("create table messages (id integer primary key, sent integer, body text)")
    for i in (66, 143, 200):
        conn.execute("insert into messages (id, sent, body) values (?,?,?)",
                     (i, 1, f"message {i}"))
    conn.commit()
    conn.close()


def build_base(root: pathlib.Path, csv_src: pathlib.Path,
               csv2_src: pathlib.Path | None = None) -> None:
    """The pristine deliverable: public data, a synthetic image export, a PDF, a database."""
    (root / "export").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(csv_src, root / CSV_NAME)
    if csv2_src is not None:
        shutil.copyfile(csv2_src, root / CSV2_NAME)
    for i, (w, h) in enumerate([(8, 6), (12, 9), (4, 4), (16, 12), (10, 10), (6, 8)]):
        (root / "export" / f"img_{i}.png").write_bytes(png_bytes(w, h, seed=i))
    (root / "report.pdf").write_bytes(make_pdf(["Invoice 2026-11", "Terms and conditions"]))
    seed_mail_db(root / "dc.db")


# ----------------------------------------------------------------- plans
def plan_body(root: pathlib.Path, name: str, checks: list[dict]) -> dict:
    return {
        "name": name,
        "target_kind": "local-artifacts",
        "allowed_origins": [],
        "allowed_paths": [str(root)],
        "checks": checks,
        "does_not_prove": ["anything the plan does not assert"],
    }


def export_digest(base: pathlib.Path) -> str:
    """Digest of the pristine export, so 'exact bytes' has something true to compare against."""
    _, listing = artifacts._dir_listing(str(base / "export"), True)
    return listing


def plans_for(root: pathlib.Path, header: list[str], rows: int, digest: str,
              export_sha: str = "pinned", passengers: dict | None = None) -> dict[str, dict]:
    rows_only = plan_body(root, "narrow: row count only", [
        {"id": "rows", "type": "csv_stats", "path": CSV_NAME,
         "expect": {"rows": rows}, "proves": "the export has the expected number of rows"},
    ])
    structural = plan_body(root, "structural: shape + nulls + export inventory", [
        {"id": "rows-columns-nulls", "type": "csv_stats", "path": CSV_NAME,
         "expect": {"rows": rows, "columns": header,
                    "nulls": {c: 0 for c in header}},
         "proves": "row count, header and per-column nulls match the source"},
        {"id": "export-inventory", "type": "dir_manifest", "path": "export",
         "expect": {"files": 6}, "proves": "the image export contains six files"},
        {"id": "first-image-dims", "type": "image_size", "path": "export/img_0.png",
         "width": 8, "height": 6, "proves": "the first image is 8x6"},
    ])
    strict = plan_body(root, "strict: adds exact bytes", [
        {"id": "csv-exact-bytes", "type": "file_sha256", "path": CSV_NAME,
         "equals": digest, "proves": "the CSV is byte-identical to the source"},
        {"id": "export-exact-bytes", "type": "dir_manifest", "path": "export",
         "expect": {"files": 6, "sha256": export_sha},
         "proves": "every exported image is unchanged, byte for byte"},
    ])
    documents = plan_body(root, "documents: the report's shape and its words", [
        {"id": "pages", "type": "pdf_pages", "path": "report.pdf", "equals": 2,
         "proves": "the report has two pages"},
        {"id": "page-size", "type": "pdf_page_size", "path": "report.pdf",
         "width": 595, "height": 842, "proves": "the page is A4"},
        {"id": "has-invoice", "type": "pdf_text_contains", "path": "report.pdf",
         "contains": "Invoice", "proves": "the document contains its invoice heading"},
    ])
    records = plan_body(root, "records: the message is actually in the system of record", [
        {"id": "message-66", "type": "sqlite_query", "path": "dc.db",
         "query": "select count(*) from messages where id = ? and sent = 1",
         "params": [66], "expect": {"equals": 1},
         "proves": "message 66 exists and is marked sent"},
        {"id": "message-143", "type": "sqlite_query", "path": "dc.db",
         "query": "select count(*) from messages where id = ? and sent = 1",
         "params": [143], "expect": {"equals": 1},
         "proves": "message 143 exists and is marked sent"},
    ])
    # Second dataset: its own plan, because its null counts are real (177 / 687 / 2) and a
    # zero-null assertion would be meaningless on it.
    passengers_plan = None
    if passengers:
        passengers_plan = plan_body(
            root, "passengers: a second public dataset's shape and real nulls", [
                {"id": "rows-columns-nulls", "type": "csv_stats", "path": CSV2_NAME,
                 "expect": {"rows": passengers["rows"], "columns": passengers["header"],
                            "nulls": passengers["nulls"]},
                 "proves": "row count, header and the real per-column null counts are unchanged"},
            ])
    out = {"narrow": rows_only, "structural": structural, "strict": strict,
           "documents": documents, "records": records}
    if passengers_plan:
        out["passengers"] = passengers_plan
    return out


# ----------------------------------------------------------------- defects
def _parse(csv_text: str) -> list[list[str]]:
    """Parse with the csv module, not split(","): this dataset quotes fields that contain
    commas ("Congo, Democratic Republic of"), and a naive split turns a valid CSV into a
    mangled one — which would let a row-count plan claim a catch it did not make."""
    import io

    return list(csv.reader(io.StringIO(csv_text)))


def _write(path: pathlib.Path, rows: list[list[str]]) -> None:
    import io

    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    path.write_text(buf.getvalue())


def defects(csv_text: str, header: list[str]) -> dict[str, callable]:
    lines = csv_text.rstrip("\n").split("\n")
    rows = _parse(csv_text)

    def drop_last_row(r: pathlib.Path) -> None:
        _write(r / CSV_NAME, rows[:-1])

    def duplicate_row(r: pathlib.Path) -> None:
        _write(r / CSV_NAME, rows + [rows[-1]])

    def blank_cell(r: pathlib.Path) -> None:
        mutated = [list(x) for x in rows]
        mutated[1][0] = ""
        _write(r / CSV_NAME, mutated)

    def truncate_mid_row(r: pathlib.Path) -> None:
        (r / CSV_NAME).write_text("\n".join(lines[:-1]) + "\n" + lines[-1][:3])

    def wrong_delimiter(r: pathlib.Path) -> None:
        import io

        buf = io.StringIO()
        csv.writer(buf, delimiter=";", lineterminator="\n").writerows(rows)
        (r / CSV_NAME).write_text(buf.getvalue())

    def reorder_columns(r: pathlib.Path) -> None:
        _write(r / CSV_NAME, [list(reversed(x)) for x in rows])

    def rename_header(r: pathlib.Path) -> None:
        mutated = [list(x) for x in rows]
        mutated[0][0] = "Nation"
        _write(r / CSV_NAME, mutated)

    def extra_column(r: pathlib.Path) -> None:
        _write(r / CSV_NAME, [x + ["x"] for x in rows])

    def header_only(r: pathlib.Path) -> None:
        _write(r / CSV_NAME, [rows[0]])

    def image_removed(r: pathlib.Path) -> None:
        (r / "export" / "img_5.png").unlink()

    def image_added(r: pathlib.Path) -> None:
        (r / "export" / "img_extra.png").write_bytes(png_bytes(3, 3, seed=99))

    def image_pixels_changed(r: pathlib.Path) -> None:
        (r / "export" / "img_3.png").write_bytes(png_bytes(16, 12, seed=1234))

    def image_wrong_dims(r: pathlib.Path) -> None:
        (r / "export" / "img_0.png").write_bytes(png_bytes(80, 60, seed=0))

    def pdf_drop_page(r: pathlib.Path) -> None:
        (r / "report.pdf").write_bytes(make_pdf(["Invoice 2026-11"]))

    def pdf_lose_text(r: pathlib.Path) -> None:
        # Remove the heading everywhere: the first version only changed page two, so the
        # text the plan asserts was still present and the "defect" caught nothing.
        (r / "report.pdf").write_bytes(make_pdf(["Quarterly summary", "Terms and conditions"]))

    def db_row_missing(r: pathlib.Path) -> None:
        import sqlite3

        conn = sqlite3.connect(r / "dc.db")
        conn.execute("delete from messages where id = 66")
        conn.commit()
        conn.close()

    def db_flag_never_set(r: pathlib.Path) -> None:
        import sqlite3

        conn = sqlite3.connect(r / "dc.db")
        conn.execute("update messages set sent = 0 where id = 143")
        conn.commit()
        conn.close()

    def pdf_wrong_page_size(r: pathlib.Path) -> None:
        (r / "report.pdf").write_bytes(make_pdf(["Invoice 2026-11", "Terms and conditions"],
                                                size=(612, 792)))

    return {
        "csv: drop last row": drop_last_row,
        "csv: duplicate a row": duplicate_row,
        "csv: blank a required cell": blank_cell,
        "csv: truncate mid-row": truncate_mid_row,
        "csv: wrong delimiter": wrong_delimiter,
        "csv: columns reordered": reorder_columns,
        "csv: header renamed": rename_header,
        "csv: extra column": extra_column,
        "csv: header only, no rows": header_only,
        "export: image missing": image_removed,
        "export: extra image": image_added,
        "export: pixels changed, same dims": image_pixels_changed,
        "export: wrong dimensions": image_wrong_dims,
        "db: message row missing": db_row_missing,
        "db: sent flag never set": db_flag_never_set,
        "pdf: page dropped": pdf_drop_page,
        "pdf: heading text missing": pdf_lose_text,
        "pdf: wrong page size (Letter, not A4)": pdf_wrong_page_size,
    }


def defects2(csv2_text: str) -> dict[str, callable]:
    """Defects on the second public dataset. Its real nulls make these different in kind:
    filling a blank changes a count that a zero-null assertion could never express."""
    rows = list(csv.reader(io.StringIO(csv2_text)))

    def _w(r: pathlib.Path, body: list[list[str]]) -> None:
        (r / CSV2_NAME).write_text(_dump(body))

    def drop_row(r: pathlib.Path) -> None:
        _w(r, rows[:-1])

    def duplicate_row(r: pathlib.Path) -> None:
        _w(r, rows + [rows[-1]])

    def fill_a_blank_age(r: pathlib.Path) -> None:
        mutated = [list(x) for x in rows]
        age = rows[0].index("Age")
        for row in mutated[1:]:
            if age < len(row) and row[age].strip() == "":
                row[age] = "30"
                break
        _w(r, mutated)

    def drop_cabin_column(r: pathlib.Path) -> None:
        idx = rows[0].index("Cabin")
        _w(r, [[c for i, c in enumerate(row) if i != idx] for row in rows])

    return {
        "csv2: drop a passenger row": drop_row,
        "csv2: duplicate a passenger row": duplicate_row,
        "csv2: fill a blank Age (null count drops)": fill_a_blank_age,
        "csv2: drop the Cabin column": drop_cabin_column,
    }


def _dump(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def benign(csv_text: str):
    lines = csv_text.rstrip("\n").split("\n")
    rows = _parse(csv_text)

    def crlf(r: pathlib.Path) -> None:
        (r / CSV_NAME).write_text("\r\n".join(lines) + "\r\n")

    def shuffled_rows(r: pathlib.Path) -> None:
        _write(r / CSV_NAME, [rows[0]] + list(reversed(rows[1:])))

    def trailing_blank_line(r: pathlib.Path) -> None:
        (r / CSV_NAME).write_text(csv_text.rstrip("\n") + "\n\n")

    def db_unrelated_message(r: pathlib.Path) -> None:
        import sqlite3

        conn = sqlite3.connect(r / "dc.db")
        conn.execute("insert into messages (id, sent, body) values (999, 1, 'unrelated')")
        conn.commit()
        conn.close()

    return {
        "db: unrelated message added": db_unrelated_message,
        "csv: CRLF line endings": crlf,
        "csv: same rows, reversed order": shuffled_rows,
        "csv: trailing blank line": trailing_blank_line,
    }


def benign2(csv2_text: str) -> dict[str, callable]:
    rows = list(csv.reader(io.StringIO(csv2_text)))

    def crlf(r: pathlib.Path) -> None:
        (r / CSV2_NAME).write_text(_dump(rows).replace("\n", "\r\n"))

    return {"csv2: CRLF line endings": crlf}


# ----------------------------------------------------------------- runner
def run_plan(body: dict, base: pathlib.Path, workdir: pathlib.Path) -> tuple[str, list[str]]:
    workdir.mkdir(parents=True, exist_ok=True)
    plan_file = workdir / "plan.json"
    plan_file.write_text(json.dumps(body, indent=2))
    try:
        rec, _ = runner.execute(str(plan_file), "local", out=str(workdir / "receipts"))
    except Exception as e:  # a broken plan must not read as a catch
        return "ERROR", [f"{type(e).__name__}: {e}"]
    failed = [c["id"] for c in rec["checks"] if c["passed"] is False]
    return rec["summary"]["verdict"], failed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    csv_path, source = fetch_csv(args.offline)
    csv2_path, source2 = fetch_csv(args.offline, CSV2_URL, CSV2_NAME)
    csv_text = csv_path.read_text()
    csv2_text = csv2_path.read_text()
    header, n_rows, nulls = csv_shape(csv_text)
    header2, n_rows2, nulls2 = csv_shape(csv2_text)
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    print(f"corpus: {source}")
    print(f"        {CSV_NAME}: {n_rows} rows, {len(header)} columns "
          f"({', '.join(header)}), sha256 {digest[:16]}…")
    print(f"corpus: {source2}")
    print(f"        {CSV2_NAME}: {n_rows2} rows, {len(header2)} columns, real nulls "
          + ", ".join(f"{k}={v}" for k, v in nulls2.items() if v))
    print("        export/: 6 generated PNGs (synthetic, deterministic)\n")

    passengers = {"rows": n_rows2, "header": header2, "nulls": nulls2}
    work = pathlib.Path(tempfile.mkdtemp(prefix="proofops-bench-"))
    base = work / "pristine"
    build_base(base, csv_path, csv2_path)
    export_sha = export_digest(base)

    results: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as scratch:
        scratch_p = pathlib.Path(scratch)
        plans = plans_for(base, header, n_rows, digest, export_sha, passengers)

        # baseline: a clean corpus must not be flagged
        baseline = {}
        for key, body in plans.items():
            verdict, failed = run_plan(body, base, scratch_p / f"base-{key}")
            baseline[key] = verdict
        print("false alarms on the pristine corpus:")
        for key, verdict in baseline.items():
            print(f"  {key:<11} {verdict}")
        print()

        # defects
        catch = {k: 0 for k in plans}
        per_defect = []
        all_defects = {**defects(csv_text, header), **defects2(csv2_text)}
        for i, (label, apply) in enumerate(all_defects.items()):
            variant = work / f"defect-{i}"
            shutil.copytree(base, variant)
            apply(variant)
            body_for = plans_for(variant, header, n_rows, digest, export_sha, passengers)
            row = {"defect": label, "caught_by": {}}
            for key in plans:
                verdict, failed = run_plan(body_for[key], variant, scratch_p / f"d-{i}-{key}")
                got = verdict == "FAIL"
                row["caught_by"][key] = {"caught": got, "verdict": verdict, "failed": failed}
                if got:
                    catch[key] += 1
            per_defect.append(row)

        # benign changes
        false_alarm = {k: 0 for k in plans}
        benign_rows = []
        all_benign = {**benign(csv_text), **benign2(csv2_text)}
        for i, (label, apply) in enumerate(all_benign.items()):
            variant = work / f"benign-{i}"
            shutil.copytree(base, variant)
            apply(variant)
            body_for = plans_for(variant, header, n_rows, digest, export_sha, passengers)
            row = {"change": label, "flagged_by": {}}
            for key in plans:
                verdict, failed = run_plan(body_for[key], variant, scratch_p / f"b-{i}-{key}")
                flagged = verdict == "FAIL"
                row["flagged_by"][key] = {"flagged": flagged, "verdict": verdict, "failed": failed}
                if flagged:
                    false_alarm[key] += 1
            benign_rows.append(row)

    n_defects, n_benign = len(per_defect), len(benign_rows)
    print(f"detection over {n_defects} injected defects, false alarms over {n_benign} benign changes:\n")
    print(f"  {'plan':<11} {'caught':>12} {'false alarms':>14}")
    for key in plans:
        print(f"  {key:<11} {catch[key]:>7}/{n_defects:<4} {false_alarm[key]:>10}/{n_benign}")

    print("\nwhat the narrow plan misses:")
    for row in per_defect:
        if not row["caught_by"]["narrow"]["caught"]:
            print(f"  - {row['defect']}")

    # Stamp what produced this file. A results artefact that cannot say which run and which
    # code made it is exactly the ambiguity this tool exists to remove - a stale background
    # job once reported pre-fix numbers that looked like a fresh result.
    summary = {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "bench_script_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()[:16],
        "proofops_version": __import__("proofops").__version__,
        "python": __import__("platform").python_version(),
        "defect_count": n_defects,
        "benign_count": n_benign,
        "corpus": {"source": source, "rows": n_rows, "columns": header, "sha256": digest},
        "plans": list(plans),
        "baseline_verdicts": baseline,
        "detected": catch,
        "false_alarms": false_alarm,
        "defects": per_defect,
        "benign": benign_rows,
    }
    OUT.write_text(json.dumps(summary, indent=2))
    print(f"\nfull results: {OUT}")
    print(f"  generated at {summary['generated_at']} · {n_defects} defects · "
          f"proofops {summary['proofops_version']} · bench {summary['bench_script_sha256']}")

    # Each defect is expected to be caught by the plan that actually asserts something about
    # it. A defect no plan asserts on is not "caught" by another plan's luck.
    owners = {
        "strict": [r for r in per_defect if r["defect"].startswith(("csv:", "export:"))],
        "documents": [r for r in per_defect if r["defect"].startswith("pdf:")],
        "records": [r for r in per_defect if r["defect"].startswith("db:")],
        "passengers": [r for r in per_defect if r["defect"].startswith("csv2:")],
    }
    ok = (all(v == "PASS" for v in baseline.values())
          and all(all(r["caught_by"][plan]["caught"] for r in rows)
                  for plan, rows in owners.items())
          and all(false_alarm[p] == 0
                  for p in ("narrow", "structural", "documents", "records", "passengers")))
    print("\nbench:", "PASS" if ok else "REVIEW")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
