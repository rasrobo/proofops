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


def fetch_csv(offline: bool) -> tuple[pathlib.Path, str]:
    CORPUS.mkdir(parents=True, exist_ok=True)
    dest = CORPUS / CSV_NAME
    if dest.exists():
        return dest, f"cached {dest.relative_to(HERE.parent)}"
    if offline:
        raise SystemExit("--offline and no cached corpus; run once with network")
    with urllib.request.urlopen(CSV_URL, timeout=30) as r:
        dest.write_bytes(r.read())
    return dest, CSV_URL


def build_base(root: pathlib.Path, csv_src: pathlib.Path) -> None:
    """The pristine deliverable: one real CSV plus a synthetic image export."""
    (root / "export").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(csv_src, root / CSV_NAME)
    for i, (w, h) in enumerate([(8, 6), (12, 9), (4, 4), (16, 12), (10, 10), (6, 8)]):
        (root / "export" / f"img_{i}.png").write_bytes(png_bytes(w, h, seed=i))


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
              export_sha: str = "pinned") -> dict[str, dict]:
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
    return {"narrow": rows_only, "structural": structural, "strict": strict}


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
    }


def benign(csv_text: str) -> dict[str, callable]:
    lines = csv_text.rstrip("\n").split("\n")
    rows = _parse(csv_text)

    def crlf(r: pathlib.Path) -> None:
        (r / CSV_NAME).write_text("\r\n".join(lines) + "\r\n")

    def shuffled_rows(r: pathlib.Path) -> None:
        _write(r / CSV_NAME, [rows[0]] + list(reversed(rows[1:])))

    def trailing_blank_line(r: pathlib.Path) -> None:
        (r / CSV_NAME).write_text(csv_text.rstrip("\n") + "\n\n")

    return {
        "csv: CRLF line endings": crlf,
        "csv: same rows, reversed order": shuffled_rows,
        "csv: trailing blank line": trailing_blank_line,
    }


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
    csv_text = csv_path.read_text()
    header = csv_text.splitlines()[0].split(",")
    n_rows = len(csv_text.rstrip("\n").splitlines()) - 1
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    print(f"corpus: {source}")
    print(f"        {CSV_NAME}: {n_rows} rows, {len(header)} columns "
          f"({', '.join(header)}), sha256 {digest[:16]}…")
    print("        export/: 6 generated PNGs (synthetic, deterministic)\n")

    work = pathlib.Path(tempfile.mkdtemp(prefix="proofops-bench-"))
    base = work / "pristine"
    build_base(base, csv_path)
    export_sha = export_digest(base)

    results: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as scratch:
        scratch_p = pathlib.Path(scratch)
        plans = plans_for(base, header, n_rows, digest, export_sha)

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
        for i, (label, apply) in enumerate(defects(csv_text, header).items()):
            variant = work / f"defect-{i}"
            shutil.copytree(base, variant)
            apply(variant)
            body_for = plans_for(variant, header, n_rows, digest, export_sha)
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
        for i, (label, apply) in enumerate(benign(csv_text).items()):
            variant = work / f"benign-{i}"
            shutil.copytree(base, variant)
            apply(variant)
            body_for = plans_for(variant, header, n_rows, digest, export_sha)
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

    summary = {
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

    ok = (all(v == "PASS" for v in baseline.values()) and catch["strict"] == n_defects
          and false_alarm["structural"] == 0 and false_alarm["narrow"] == 0)
    print("\nbench:", "PASS" if ok else "REVIEW")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
