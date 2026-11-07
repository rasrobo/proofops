"""The metrics tests that matter are the ones about what is NOT sent.

A telemetry module in a verification tool is judged by the same standard as a receipt: it must be
impossible to send something the operator did not see and agree to. So these tests assert absence —
no socket opened without consent, no field that could identify a machine or a plan — rather than
asserting that a happy path posts JSON.
"""
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from proofops import metrics  # noqa: E402


def a_receipt(plan_rev: str, passed: int, failed: int, not_run: int = 0, verdict="FAIL") -> dict:
    checks = [{"passed": True} for _ in range(passed)] + [{"passed": False} for _ in range(failed)]
    checks += [{"passed": None, "status": "not_run"} for _ in range(not_run)]
    return {"run_id": "PO-x", "plan": "a plan about a customer's server", "plan_revision": plan_rev,
            "verdict": verdict, "summary": {"verdict": verdict}, "checks": checks}


class Corpus:
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.receipts = self.root / "receipts"
        self.receipts.mkdir()
        self.home = self.root / "home"
        self._old = metrics.home
        metrics.home = lambda: self.home
        return self

    def __exit__(self, *exc):
        metrics.home = self._old
        self.tmp.cleanup()


class TestNothingLeavesWithoutConsent(unittest.TestCase):
    def test_send_refuses_before_opening_a_socket(self):
        opened = []
        real = metrics.urllib.request.urlopen
        metrics.urllib.request.urlopen = lambda *a, **k: opened.append(a) or real(*a, **k)
        try:
            with Corpus() as c:
                with self.assertRaises(PermissionError):
                    metrics.send(c.receipts)
                self.assertEqual(opened, [], "urlopen must not be reached without consent")
        finally:
            metrics.urllib.request.urlopen = real

    def test_disable_after_enable_stops_sending_again(self):
        with Corpus() as c:
            metrics.set_consent(True)
            self.assertTrue(metrics.consent()["share"])
            metrics.set_consent(False)
            with self.assertRaises(PermissionError):
                metrics.send(c.receipts)

    def test_dry_run_bytes_are_the_real_bytes(self):
        with Corpus() as c:
            (c.receipts / "r1.json").write_text(json.dumps(a_receipt("sha256:aaaa", 3, 1)))
            self.assertEqual(metrics.payload_bytes(c.receipts), metrics.payload_bytes(c.receipts))
            parsed = json.loads(metrics.payload_bytes(c.receipts))
            self.assertEqual(sorted(parsed),
                             ["by_type", "checks", "install_id", "plans", "platform", "runs",
                              "schema", "version"])


class TestPayloadHasNoFingerprint(unittest.TestCase):
    def test_no_paths_hostnames_or_plan_names(self):
        with Corpus() as c:
            (c.receipts / "r1.json").write_text(json.dumps(a_receipt("sha256:aaaa", 2, 1)))
            blob = metrics.payload_bytes(c.receipts).decode().lower()
            for forbidden in ("customer", "server", "plan_revision", "sha256:", "/home/", "hostname"):
                self.assertNotIn(forbidden, blob, f"payload leaked {forbidden!r}")

    def test_install_id_is_a_random_uuid_not_a_machine_fingerprint(self):
        with Corpus() as c:
            first = metrics.build_payload(c.receipts)["install_id"]
            second = metrics.build_payload(c.receipts)["install_id"]
            self.assertEqual(first, second, "install id must be stable across runs")
            self.assertEqual(str(uuid.UUID(first)), first, "must parse as a uuid4")
            self.assertEqual(uuid.UUID(first).version, 4)


class FakeStdin:
    def __init__(self, lines):
        self.lines = list(lines)
    def isatty(self):
        return True
    def readline(self):
        return self.lines.pop(0) if self.lines else ""


class TestConsentPrompt(unittest.TestCase):
    """The install moment: it must convert without ever manufacturing consent."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"PROOPS_HOME": self.td.name})
        self.env.start()
        self.receipts = Path(self.td.name, "receipts")
        self.receipts.mkdir()

    def tearDown(self):
        self.env.stop()
        self.td.cleanup()

    def test_nothing_is_asked_without_a_human_at_a_terminal(self):
        with mock.patch.object(metrics.sys.stdin, "isatty", return_value=False):
            self.assertEqual(metrics.maybe_ask(self.receipts), "undecided")
        self.assertEqual(metrics.consent_status(), "undecided", "must not write a decision")

    def test_enter_means_no_and_it_is_remembered(self):
        with mock.patch.object(metrics, "interactive", return_value=True), \
             mock.patch.object(metrics.sys, "stdin", FakeStdin(["\n"])):
            self.assertEqual(metrics.maybe_ask(self.receipts), "declined")
        self.assertEqual(metrics.consent_status(), "declined")

    def test_a_declined_install_is_never_asked_again(self):
        with mock.patch.object(metrics, "interactive", return_value=True), \
             mock.patch.object(metrics.sys, "stdin", FakeStdin([""])):
            metrics.maybe_ask(self.receipts)
        out = io.StringIO()
        with mock.patch.object(metrics, "ask", side_effect=AssertionError("asked twice")), \
             mock.patch.object(metrics, "interactive", return_value=True):
            self.assertEqual(metrics.maybe_ask(self.receipts), "declined")
        self.assertEqual(out.getvalue(), "")

    def test_yes_enables(self):
        with mock.patch.object(metrics, "interactive", return_value=True), \
             mock.patch.object(metrics.sys, "stdin", FakeStdin(["y\n"])):
            self.assertEqual(metrics.maybe_ask(self.receipts), "enabled")
        self.assertEqual(metrics.consent_status(), "enabled")

    def test_d_shows_the_bytes_then_asks_again(self):
        out = io.StringIO()
        with mock.patch.object(metrics, "interactive", return_value=True), \
             mock.patch.object(metrics.sys, "stdin", FakeStdin(["d\n", "n\n"])):
            status = metrics.ask(self.receipts, stream=out)
        self.assertEqual(status, "declined")
        self.assertIn("install_id", out.getvalue(), "the payload must actually be shown")
        self.assertEqual(out.getvalue().count("One question, once"), 2, "re-asks after showing")

    def test_ci_never_prompts(self):
        with mock.patch.dict(os.environ, {"CI": "1"}):
            self.assertFalse(metrics.interactive())


class TestCheckTypes(unittest.TestCase):
    def test_the_client_type_list_matches_the_registry(self):
        """If a check type is added to REGISTRY and not here, its counts silently vanish from the
        public report. Fail loudly instead."""
        from proofops.checks import REGISTRY
        self.assertEqual(set(metrics.CHECK_TYPES), set(REGISTRY), "CHECK_TYPES drifted from REGISTRY")

    def test_by_type_counts_each_type_separately(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "r1.json").write_text(json.dumps({"plan_revision": "sha256:aa", "checks": [
                {"id": "a", "type": "http_status", "passed": True},
                {"id": "b", "type": "http_status", "passed": False},
                {"id": "c", "type": "pdf_pages", "passed": None},
                {"id": "d", "type": "sqlite_query", "passed": True},
            ]}))
            s = metrics.collect_stats(Path(td))
        self.assertEqual(s["by_type"]["http_status"], {"pass": 1, "fail": 1, "not_run": 0})
        self.assertEqual(s["by_type"]["pdf_pages"], {"pass": 0, "fail": 0, "not_run": 1})
        self.assertEqual(s["checks"], {"pass": 2, "fail": 1, "not_run": 1})

    def test_the_payload_carries_by_type_not_just_the_totals(self):
        """Regression: collect_stats counted types but build_payload dropped them, so the field
        could have shipped empty forever while every test passed."""
        with tempfile.TemporaryDirectory() as td:
            Path(td, "r1.json").write_text(json.dumps({"plan_revision": "sha256:aa", "checks": [
                {"id": "a", "type": "http_status", "passed": True},
                {"id": "b", "type": "pdf_pages", "passed": False},
            ]}))
            payload = json.loads(metrics.payload_bytes(Path(td)))
        self.assertTrue(payload["by_type"], "by_type must reach the wire, not just collect_stats")
        self.assertEqual(payload["by_type"]["http_status"]["pass"], 1)
        self.assertEqual(payload["by_type"]["pdf_pages"]["fail"], 1)

    def test_an_unknown_or_customer_named_type_is_dropped(self):
        out = metrics.sanitise({
            "install_id": "2b1f3f16-1f6f-4b0e-9d3f-5a1c7e2d4b11",
            "version": "0.3.5", "platform": "linux", "runs": 1, "plans": 1,
            "checks": {"pass": 2, "fail": 0, "not_run": 0},
            "by_type": {"http_status": {"pass": 2},
                        "acme_customer_portal": {"pass": 99},
                        "jane.doe@example.com": {"pass": 1}},
        })
        self.assertEqual(list(out["by_type"]), ["http_status"])
        self.assertNotIn("acme", json.dumps(out).lower())


class TestEndpointShape(unittest.TestCase):
    def test_a_slashless_stored_endpoint_still_posts_to_the_slash(self):
        """Regression: Django answers a slashless POST with 405, so a stale consent record must not
        silently break sending. send() normalises instead of trusting the stored value."""
        seen = {}

        class Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            return Resp()

        with mock.patch.object(metrics, "consent", return_value={
                "share": True, "endpoint": "https://example.test/api/x"}), \
             mock.patch.object(metrics.urllib.request, "urlopen", side_effect=fake_urlopen):
            metrics.send(Path("/nonexistent"))
        self.assertEqual(seen["url"], "https://example.test/api/x/")


class TestSanitise(unittest.TestCase):
    def test_pii_in_a_free_text_field_is_stripped_not_forwarded(self):
        """Even if a future bug put a hostname or an email in version/platform, it cannot ship."""
        out = metrics.sanitise({
            "install_id": "2b1f3f16-1f6f-4b0e-9d3f-5a1c7e2d4b11",
            "version": "0.3.4 customer=jane.doe@example.com",
            "platform": "Linux acme-prod-01.internal",
            "runs": 3, "plans": 1,
            "checks": {"pass": 2, "fail": 1, "not_run": 0},
            "customer": "Jane Doe Ltd",
        })
        blob = json.dumps(out).lower()
        for leak in ("jane", "@", "acme", "customer", "internal"):
            self.assertNotIn(leak, blob, f"sanitise leaked {leak!r}")
        self.assertEqual(sorted(out), ["by_type", "checks", "install_id", "plans", "platform",
                                       "runs", "schema", "version"])
        self.assertEqual(out["version"], "unknown", "a version string with junk in it is refused whole")
        self.assertEqual(out["platform"], "other", "an unrecognised platform is 'other', never echoed")

    def test_counts_are_bounded_non_negative_ints(self):
        out = metrics.sanitise({"install_id": str(uuid.uuid4()), "runs": -5,
                                "plans": "12", "checks": {"pass": "7", "fail": None}})
        self.assertEqual(out["runs"], 0)
        self.assertEqual(out["plans"], 12)
        self.assertEqual(out["checks"], {"pass": 7, "fail": 0, "not_run": 0})


class TestLocalStats(unittest.TestCase):
    def test_counts_runs_checks_and_verdicts(self):
        with Corpus() as c:
            (c.receipts / "a.json").write_text(json.dumps(a_receipt("sha256:a", 3, 0, 0, "PASS")))
            (c.receipts / "b.json").write_text(json.dumps(a_receipt("sha256:a", 2, 1, 1, "FAIL")))
            s = metrics.collect_stats(c.receipts)
            self.assertEqual(s["runs"], 2)
            self.assertEqual(s["checks"], {"pass": 5, "fail": 1, "not_run": 1})
            self.assertEqual(s["plans"], 1)

    def test_stats_works_with_no_network_module_available(self):
        """stats must never touch urllib — proven by removing it entirely."""
        with Corpus() as c:
            (c.receipts / "a.json").write_text(json.dumps(a_receipt("sha256:a", 1, 0, 0, "PASS")))
            saved = metrics.urllib
            metrics.urllib = None
            try:
                report = metrics.stats_report(c.receipts)
            finally:
                metrics.urllib = saved
            self.assertIn("runs        1", report)
            self.assertIn("nothing has left this machine", report)

    def test_a_corrupt_receipt_is_skipped_not_counted(self):
        with Corpus() as c:
            (c.receipts / "bad.json").write_text("{not json")
            (c.receipts / "good.json").write_text(json.dumps(a_receipt("sha256:a", 1, 0, 0, "PASS")))
            self.assertEqual(metrics.collect_stats(c.receipts)["runs"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
