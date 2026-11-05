"""Tests for the destination-of-record check.

The scenario comes from a real failure: an agent reported `sentMessageId 66` and `143` while no
account database held the message. The claim was well-formed, the API said yes, and the only
thing that could have caught it was reading the store.

Two properties matter beyond the happy path:

1. **It cannot write.** A DELETE dressed as a comment, or two statements in one string, must be
   refused — and the database must be byte-identical afterwards.
2. **A missing row is a FAIL with the observed count**, not an exception and not a pass.
"""

import pathlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from proofops import artifacts as art   # noqa: E402
from proofops import dbx                # noqa: E402


def seed(path: pathlib.Path, accounts: int = 3) -> None:
    conn = sqlite3.connect(path)
    conn.execute("create table messages (id integer primary key, sent integer, body text)")
    for i in range(1, 10):
        conn.execute("insert into messages (id, sent, body) values (?,?,?)",
                     (i, 1 if i != 143 else 0, f"message {i}"))
    conn.commit()
    conn.close()


class Corpus:
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        seed(self.root / "dc.db")
        art.set_policy(art.PathPolicy((str(self.root),)))
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()


class TestReadBack(unittest.TestCase):
    def test_a_present_row_is_proved(self):
        with Corpus() as c:
            ok, ev = dbx.sqlite_query({"path": "dc.db",
                                       "query": "select count(*) from messages where id = ?",
                                       "params": [7], "expect": {"equals": 1}}, "local")
            self.assertTrue(ok, ev)
            self.assertEqual(ev["first_row"][0], "1")
            self.assertIn("read-only", ev["mode"])

    def test_a_message_that_never_landed_fails_with_the_count(self):
        """The exact claim from the incident: sentMessageId 143, absent from the store."""
        with Corpus() as c:
            ok, ev = dbx.sqlite_query({"path": "dc.db",
                                       "query": "select count(*) from messages where id = ?",
                                       "params": [143], "expect": {"equals": 1}}, "local")
            self.assertFalse(ok)
            self.assertEqual(ev["mismatches"][0]["field"], "first_value")
            self.assertEqual(ev["mismatches"][0]["observed"], 0)

    def test_row_count_assertion(self):
        with Corpus() as c:
            ok, ev = dbx.sqlite_query({"path": "dc.db", "query": "select id from messages",
                                       "expect": {"rows": 9}}, "local")
            self.assertTrue(ok, ev)
            self.assertEqual(ev["rows_returned"], 9)


class TestReadOnlyFence(unittest.TestCase):
    def _assert_refused_and_unchanged(self, query: str, params=None):
        with Corpus() as c:
            before = (c.root / "dc.db").read_bytes()
            ok, ev = dbx.sqlite_query({"path": "dc.db", "query": query,
                                       "params": params or []}, "local")
            self.assertFalse(ok, f"should refuse: {query}")
            self.assertIn("read-only", ev["error"].lower())
            self.assertEqual(before, (c.root / "dc.db").read_bytes(),
                             "a refused check must not have written anything")

    def test_delete_is_refused(self):
        self._assert_refused_and_unchanged("delete from messages")

    def test_a_commented_delete_cannot_slip_through(self):
        self._assert_refused_and_unchanged("-- select\n delete from messages")

    def test_two_statements_are_refused(self):
        self._assert_refused_and_unchanged("select 1; drop table messages")

    def test_drop_is_refused(self):
        self._assert_refused_and_unchanged("drop table messages")


class TestPathFence(unittest.TestCase):
    def test_a_database_outside_the_declared_roots_is_refused(self):
        with Corpus() as c:
            ok, ev = dbx.sqlite_query({"path": "../elsewhere.db", "query": "select 1"},
                                      "local")
            self.assertFalse(ok)
            self.assertIn("allowed_paths", ev["error"])

    def test_a_missing_database_is_reported_not_crashed(self):
        with Corpus() as c:
            ok, ev = dbx.sqlite_query({"path": "nope.db", "query": "select 1"}, "local")
            self.assertFalse(ok)
            self.assertIn("cannot open", ev["error"])

    def test_a_broken_query_reports_the_sqlite_error(self):
        with Corpus() as c:
            ok, ev = dbx.sqlite_query({"path": "dc.db", "query": "select nope from messages"},
                                      "local")
            self.assertFalse(ok)
            self.assertIn("OperationalError", ev["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
