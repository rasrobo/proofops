"""Tests for artifact checks: the deliverable side of "done".

The claims these cover are the ones a demo never shows: the export that lost three files, the
CSV that parses but is short, the image set that is the wrong size. Two properties matter more
than any single assertion:

1. **A plan cannot read outside the roots it declares** — otherwise a copied plan is a file
   exfiltration tool with a verification UI.
2. **An empty or truncated artifact must fail loudly**, not count as "no rows to complain
   about". A verifier that passes a zero-byte file is worse than none.
"""

import hashlib
import pathlib
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from proofops import artifacts as art          # noqa: E402
from proofops import plan as plan_mod         # noqa: E402


def png_bytes(w: int, h: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Corpus:
    """A throwaway artifact tree with a known shape."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "export").mkdir()
        (self.root / "data.csv").write_text("Country,Continent\nIreland,Europe\nKenya,Africa\n")
        (self.root / "pic.png").write_bytes(png_bytes(2, 3))
        (self.root / "export" / "a.txt").write_text("a")
        (self.root / "export" / "b.txt").write_text("bb")
        art.set_policy(art.PathPolicy((str(self.root),)))
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()


class TestPathFence(unittest.TestCase):
    def test_a_path_escaping_the_roots_is_refused(self):
        with Corpus() as c:
            outside = pathlib.Path(c.tmp.name).parent / "elsewhere.txt"
            outside.write_text("secret")
            try:
                ok, ev = art.file_exists({"path": "../elsewhere.txt"}, "local")
                self.assertFalse(ok)
                self.assertIn("allowed_paths", ev["error"])
            finally:
                outside.unlink()

    def test_an_absolute_path_is_refused(self):
        with Corpus() as c:
            ok, ev = art.file_exists({"path": "/etc/passwd"}, "local")
            self.assertFalse(ok)
            self.assertIn("absolute", ev["error"])

    def test_no_roots_means_every_read_is_refused(self):
        art.set_policy(art.PathPolicy(()))
        ok, ev = art.file_exists({"path": "anything"}, "local")
        self.assertFalse(ok)
        self.assertIn("allowed_paths", ev["error"])

    def test_a_symlink_pointing_outside_the_root_is_refused(self):
        with Corpus() as c:
            outside = pathlib.Path(c.tmp.name).parent / "linked-secret.txt"
            outside.write_text("secret")
            link = c.root / "link.txt"
            link.symlink_to(outside)
            try:
                ok, ev = art.file_exists({"path": "link.txt"}, "local")
                self.assertFalse(ok, "a symlink must not launder an out-of-root read")
                self.assertIn("allowed_paths", ev["error"])
            finally:
                link.unlink()
                outside.unlink()


class TestFileChecks(unittest.TestCase):
    def test_sha256_matches_and_then_detects_a_change(self):
        with Corpus() as c:
            want = hashlib.sha256((c.root / "data.csv").read_bytes()).hexdigest()
            ok, ev = art.file_sha256({"path": "data.csv", "equals": want}, "local")
            self.assertTrue(ok)
            self.assertEqual(ev["observed_sha256"], want)
            (c.root / "data.csv").write_text("Country,Continent\nIreland,Europe\n")
            ok, ev = art.file_sha256({"path": "data.csv", "equals": want}, "local")
            self.assertFalse(ok)
            self.assertNotEqual(ev["observed_sha256"], want)

    def test_missing_file_fails_rather_than_erroring_out(self):
        with Corpus() as c:
            ok, ev = art.file_exists({"path": "nope.bin", "min_bytes": 1}, "local")
            self.assertFalse(ok)
            self.assertFalse(ev["exists"])

    def test_a_zero_byte_deliverable_fails_a_min_bytes_claim(self):
        with Corpus() as c:
            (c.root / "empty.txt").write_bytes(b"")
            ok, ev = art.file_exists({"path": "empty.txt", "min_bytes": 10}, "local")
            self.assertFalse(ok)
            self.assertEqual(ev["observed_bytes"], 0)


class TestCsvStats(unittest.TestCase):
    def test_rows_columns_and_nulls_are_asserted(self):
        with Corpus() as c:
            ok, ev = art.csv_stats({"path": "data.csv",
                                    "expect": {"rows": 2,
                                               "columns": ["Country", "Continent"],
                                               "nulls": {"Country": 0}}}, "local")
            self.assertTrue(ok, ev)
            self.assertEqual(ev["observed"]["rows"], 2)

    def test_a_truncated_export_is_caught_by_the_row_count(self):
        """The failure that matters: a CSV that parses perfectly and is missing rows."""
        with Corpus() as c:
            (c.root / "data.csv").write_text("Country,Continent\nIreland,Europe\n")
            ok, ev = art.csv_stats({"path": "data.csv", "expect": {"rows": 2}}, "local")
            self.assertFalse(ok)
            self.assertEqual(ev["mismatches"][0]["observed"], 1)

    def test_a_blank_cell_counts_as_a_null(self):
        with Corpus() as c:
            (c.root / "data.csv").write_text("Country,Continent\n,Europe\nKenya,Africa\n")
            ok, ev = art.csv_stats({"path": "data.csv",
                                    "expect": {"nulls": {"Country": 0}}}, "local")
            self.assertFalse(ok)
            self.assertEqual(ev["observed"]["nulls"]["Country"], 1)


    def test_a_trailing_blank_line_is_not_a_data_row(self):
        """Found by the benchmark: a reformatted file must not fail a row-count claim."""
        with Corpus() as c:
            (c.root / "data.csv").write_text(
                "Country,Continent\nIreland,Europe\nKenya,Africa\n\n")
            ok, ev = art.csv_stats({"path": "data.csv", "expect": {"rows": 2}}, "local")
            self.assertTrue(ok, ev)
            self.assertEqual(ev["observed"]["blank_rows"], 1)


class TestImageAndManifest(unittest.TestCase):
    def test_png_dimensions_are_read_from_the_header(self):
        with Corpus() as c:
            ok, ev = art.image_size({"path": "pic.png", "width": 2, "height": 3}, "local")
            self.assertTrue(ok, ev)
            self.assertEqual(ev["observed"], "2x3")

    def test_wrong_dimensions_fail(self):
        with Corpus() as c:
            ok, ev = art.image_size({"path": "pic.png", "width": 100, "height": 3}, "local")
            self.assertFalse(ok)
            self.assertEqual(ev["observed"], "2x3")

    def test_a_non_image_is_reported_not_crashed(self):
        with Corpus() as c:
            ok, ev = art.image_size({"path": "data.csv", "width": 1, "height": 1}, "local")
            self.assertFalse(ok)
            self.assertIn("not a PNG", ev["error"])

    def test_manifest_catches_an_extra_file(self):
        with Corpus() as c:
            ok, ev = art.dir_manifest({"path": "export", "expect": {"files": 2}}, "local")
            self.assertTrue(ok, ev)
            (c.root / "export" / "c.txt").write_text("ccc")
            ok, ev = art.dir_manifest({"path": "export", "expect": {"files": 2}}, "local")
            self.assertFalse(ok)
            self.assertEqual(ev["observed"]["files"], 3)

    def test_manifest_digest_changes_when_a_file_changes(self):
        with Corpus() as c:
            _, first = art.dir_manifest({"path": "export", "expect": {"sha256": "x"}}, "local")
            (c.root / "export" / "b.txt").write_text("different")
            _, second = art.dir_manifest({"path": "export", "expect": {"sha256": "x"}}, "local")
            self.assertNotEqual(first["observed"]["sha256"], second["observed"]["sha256"])


class TestPlanValidation(unittest.TestCase):
    def _plan(self, **over):
        import json
        base = {"name": "p", "target_kind": "local", "allowed_origins": [],
                "checks": [{"id": "c", "type": "file_exists", "path": "data.csv",
                            "proves": "the export shipped"}],
                "does_not_prove": ["anything about content"]}
        base.update(over)
        d = tempfile.mkdtemp()
        p = pathlib.Path(d) / "plan.json"
        p.write_text(json.dumps(base))
        return p

    def test_file_checks_require_allowed_paths(self):
        with self.assertRaises(plan_mod.PlanError) as e:
            plan_mod.load(self._plan())
        self.assertIn("allowed_paths", str(e.exception))

    def test_traversal_in_a_check_path_is_rejected_at_load(self):
        with self.assertRaises(plan_mod.PlanError):
            plan_mod.load(self._plan(allowed_paths=["/tmp"],
                                     checks=[{"id": "c", "type": "file_exists",
                                              "path": "../etc/passwd",
                                              "proves": "x"}]))

    def test_absolute_paths_are_rejected_at_load(self):
        with self.assertRaises(plan_mod.PlanError):
            plan_mod.load(self._plan(allowed_paths=["/tmp"],
                                     checks=[{"id": "c", "type": "file_exists",
                                              "path": "/etc/passwd", "proves": "x"}]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
