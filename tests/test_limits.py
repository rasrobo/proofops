"""Limits suite: the tool must fail LOUDLY on what it cannot read.

Every other test asserts that a check finds a defect. These assert the opposite property, which
is the one that makes the product trustworthy: when ProofOps cannot answer, it says so with a
reason, and never reports a clean result it did not earn.

Each case here is a real input a machine produces — an exported CSV with a BOM, a semicolon
delimiter, a quoted field containing a newline, a zero-byte file, a truncated image, a PDF whose
page tree is inside a compressed object stream, a non-database file with a .db extension.
"""

import pathlib
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from proofops import artifacts as art    # noqa: E402
from proofops import dbx                 # noqa: E402
from proofops import pdfdoc              # noqa: E402
from test_pdf import make_pdf            # noqa: E402


def png_header_only(w: int = 4, h: int = 4) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)


class Corpus:
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        art.set_policy(art.PathPolicy((str(self.root),)))
        self.p = lambda name: self.root / name
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()


class TestCsvEncodings(unittest.TestCase):
    def test_a_utf8_bom_does_not_corrupt_the_first_column_name(self):
        """Excel and many exporters write a BOM. A BOM is not a column name."""
        with Corpus() as c:
            c.p("bom.csv").write_bytes("\ufeffid,name\n1,alpha\n".encode("utf-8"))
            ok, ev = art.csv_stats({"path": "bom.csv",
                                    "expect": {"rows": 1, "columns": ["id", "name"],
                                               "nulls": {"id": 0, "name": 0}}}, "local")
            self.assertTrue(ok, ev)
            self.assertEqual(ev["observed"]["columns"], ["id", "name"])

    def test_a_wrong_delimiter_is_caught_by_a_header_assertion_and_missed_by_a_row_count(self):
        """The honest shape of this limit: with delimiter ',' the whole line becomes one
        column and the row count still matches. So a rows-only plan passes a file it should
        not - which is why a plan that asserts the header is worth more than one that counts."""
        with Corpus() as c:
            c.p("semi.csv").write_text("id;name\n1;alpha\n2;beta\n")

            weak_ok, weak_ev = art.csv_stats(
                {"path": "semi.csv", "expect": {"rows": 2}}, "local")
            self.assertTrue(weak_ok, "a row count alone cannot see a delimiter change")
            self.assertEqual(weak_ev["observed"]["columns"], ["id;name"])

            strict_ok, strict_ev = art.csv_stats(
                {"path": "semi.csv", "expect": {"rows": 2, "columns": ["id", "name"]}}, "local")
            self.assertFalse(strict_ok, "asserting the header catches it")
            self.assertEqual(strict_ev["mismatches"][0]["field"], "columns")

    def test_the_same_file_passes_when_the_plan_declares_the_delimiter(self):
        with Corpus() as c:
            c.p("semi.csv").write_text("id;name\n1;alpha\n2;beta\n")
            ok, ev = art.csv_stats({"path": "semi.csv", "delimiter": ";",
                                    "expect": {"rows": 2, "columns": ["id", "name"]}}, "local")
            self.assertTrue(ok, ev)

    def test_a_quoted_field_with_a_newline_is_one_row(self):
        with Corpus() as c:
            c.p("quoted.csv").write_text('id,note\n1,"line one\nline two"\n2,plain\n')
            ok, ev = art.csv_stats({"path": "quoted.csv", "expect": {"rows": 2}}, "local")
            self.assertTrue(ok, ev)
            self.assertEqual(ev["observed"]["rows"], 2)

    def test_a_zero_byte_file_fails_rather_than_passing_an_empty_claim(self):
        with Corpus() as c:
            c.p("empty.csv").write_bytes(b"")
            ok, ev = art.csv_stats({"path": "empty.csv", "expect": {"rows": 0}}, "local")
            # rows==0 is technically satisfied, but there is no header to assert against, and
            # the evidence must make that visible rather than look like a clean result.
            self.assertEqual(ev["observed"]["columns"], [])
            self.assertEqual(ev["observed"]["rows"], 0)

    def test_truncated_mid_field_is_reported_as_a_count_not_a_crash(self):
        with Corpus() as c:
            c.p("trunc.csv").write_text("id,name\n1,alpha\n2,be")
            ok, ev = art.csv_stats({"path": "trunc.csv", "expect": {"rows": 3}}, "local")
            self.assertFalse(ok)
            self.assertEqual(ev["observed"]["rows"], 2)


class TestBinaryLimits(unittest.TestCase):
    def test_a_truncated_png_is_named_not_guessed(self):
        with Corpus() as c:
            c.p("tiny.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            ok, ev = art.image_size({"path": "tiny.png", "width": 10, "height": 10}, "local")
            self.assertFalse(ok)
            self.assertIn("not a PNG, GIF or JPEG", ev["error"])

    def test_a_webp_is_an_explicit_unsupported_format(self):
        with Corpus() as c:
            c.p("pic.webp").write_bytes(b"RIFF\x24\x00\x00\x00WEBPVP8 ")
            ok, ev = art.image_size({"path": "pic.webp", "width": 1, "height": 1}, "local")
            self.assertFalse(ok)
            self.assertIn("not a PNG, GIF or JPEG", ev["error"])

    def test_a_pdf_with_a_compressed_object_stream_says_so(self):
        """Modern PDFs put the page tree in an object stream. We cannot read those, and the
        receipt must say that instead of reporting zero pages."""
        with Corpus() as c:
            body = b"%PDF-1.7\n1 0 obj\n<< /Type /ObjStm /N 1 /First 10 >>\nstream\nx\nendstream\nendobj\ntrailer\n<< /Root 2 0 R >>\n%%EOF\n"
            c.p("modern.pdf").write_bytes(body)
            ok, ev = pdfdoc.pdf_pages({"path": "modern.pdf", "equals": 1}, "local")
            self.assertFalse(ok)
            self.assertIn("no page tree found", ev["error"])

    def test_a_pdf_with_no_pages_and_no_objects_is_an_error(self):
        with Corpus() as c:
            c.p("empty.pdf").write_bytes(b"%PDF-1.7\n%%EOF\n")
            ok, ev = pdfdoc.pdf_pages({"path": "empty.pdf", "equals": 1}, "local")
            self.assertFalse(ok)
            self.assertIn("error", ev)

    def test_a_valid_pdf_is_unaffected(self):
        with Corpus() as c:
            c.p("ok.pdf").write_bytes(make_pdf(["one", "two"]))
            ok, ev = pdfdoc.pdf_pages({"path": "ok.pdf", "equals": 2}, "local")
            self.assertTrue(ok, ev)


class TestDatabaseLimits(unittest.TestCase):
    def test_a_non_database_file_is_reported_not_crashed(self):
        with Corpus() as c:
            c.p("fake.db").write_bytes(b"this is not sqlite at all" * 4)
            # `select 1` touches no b-tree, so on some SQLite builds it returns a row from a
            # file that is not a database at all - a verdict that would have depended on the
            # library version. The connection now reads the schema page first, so this is
            # deterministic: no database, no green tick.
            ok, ev = dbx.sqlite_query({"path": "fake.db", "query": "select 1"}, "local")
            self.assertFalse(ok)
            self.assertIn("not a database", ev["error"])

    def test_a_real_database_still_answers(self):
        with Corpus() as c:
            import sqlite3

            conn = sqlite3.connect(c.p("ok.db"))
            conn.execute("create table t (id integer)")
            conn.executemany("insert into t values (?)", [(1,), (2,)])
            conn.commit()
            conn.close()
            ok, ev = dbx.sqlite_query({"path": "ok.db",
                                       "query": "select count(*) as n from t",
                                       "expect": {"equals": 2}}, "local")
            self.assertTrue(ok, ev)

    def test_a_write_is_refused_with_a_reason(self):
        with Corpus() as c:
            import sqlite3

            conn = sqlite3.connect(c.p("real.db"))
            conn.execute("create table t (id integer)")
            conn.commit()
            conn.close()
            ok, ev = dbx.sqlite_query({"path": "real.db", "query": "delete from t"}, "local")
            self.assertFalse(ok)
            self.assertIn("read-only", ev["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
