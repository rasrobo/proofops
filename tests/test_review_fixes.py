"""Tests for the four review fixes on PR #149625 (teknium, 2026-11-10).

1. The model no longer controls the command gates: `allow_commands` is gone from the
   tool schema, and a command check runs only if the plan lists it verbatim AND the
   operator listed that exact command in the plugin's own settings (there is no approval
   prompt inside a tool call — a round-two finding: `ctx.ask_choice` has nobody to ask).
   The working directory's ./plans is never the default.
2. A command check's child gets a minimal environment (PATH, HOME, LANG, plus only the
   variable names the operator lists).
3. HTTP checks refuse loopback/private/link-local addresses by default, on the first
   request and on every redirect hop, unless the operator allows local targets.
4. Receipts always go under the plugin's data directory (the `out` tool argument is
   gone), and a plan's file roots may not widen the operator-configured allowed_paths.

    python3 -m unittest discover -s tests -v
"""

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from proofops import checks as checks_mod          # noqa: E402
from proofops import commands as commands_mod      # noqa: E402
from proofops import plan as plan_mod              # noqa: E402
from proofops import runner                        # noqa: E402


def _load_plugin():
    spec = importlib.util.spec_from_file_location("proofops_plugin_review_test",
                                                 REPO / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PLUGIN = _load_plugin()


# ---------------------------------------------------------------- fixture server
class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/go":
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{self.server.server_address[1]}/final")
            self.end_headers()
        elif self.path == "/final":
            body = b'{"status": "ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/missing":
            body = b"nope"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = b'{"status": "ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *a):
        pass


class _Server:
    def __enter__(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"


def _command_plan(tmp, command="echo hi"):
    p = pathlib.Path(tmp) / "plan.json"
    p.write_text(json.dumps({
        "name": "cmd plan", "target_kind": "local", "allowed_origins": [],
        "checks": [{"id": "c1", "type": "command_exit", "command": command,
                    "proves": "runs"}],
        "allowed_commands": [command],
        "does_not_prove": ["anything"],
    }))
    return p


class _FakeCtx:
    """A stand-in PluginContext: operator settings + an approval prompt."""

    def __init__(self, settings=None, choice=None):
        self._settings = dict(settings or {})
        self._choice = choice
        self.asked = []

    def get_config(self, key, default=None):
        return self._settings.get(key, default)

    def ask_choice(self, question, choices):
        self.asked.append((question, choices))
        return self._choice


# ---------------------------------------------------------------- item 3: SSRF
class TestSsrfRefusal(unittest.TestCase):
    def setUp(self):
        self._prev = checks_mod.allow_local_targets()
        checks_mod.set_network_policy(False)

    def tearDown(self):
        checks_mod.set_network_policy(self._prev)

    def test_loopback_is_refused_by_default(self):
        with _Server() as s:
            ok, ev = checks_mod.http_status({"path": "/final", "expect": 200}, s.base)
        self.assertFalse(ok)
        self.assertIn("refusing", ev["error"])

    def test_metadata_address_is_refused_without_any_connection(self):
        ok, ev = checks_mod.http_status(
            {"path": "/", "expect": 200}, "http://169.254.169.254/")
        self.assertFalse(ok)
        self.assertIn("refusing", ev["error"])
        self.assertIn("169.254.169.254", ev["error"])

    def test_redirect_to_loopback_is_refused(self):
        with _Server() as s:
            ok, ev = checks_mod.http_status({"path": "/go", "expect": 200}, s.base)
        self.assertFalse(ok, "a public URL must not bounce the fetch onto loopback")
        self.assertIn("refusing", ev["error"])

    def test_redirect_is_followed_when_the_operator_allows_local_targets(self):
        checks_mod.set_network_policy(True)
        with _Server() as s:
            ok, ev = checks_mod.http_status({"path": "/go", "expect": 200}, s.base)
        self.assertTrue(ok, ev)
        self.assertEqual(ev["observed_status"], 200)

    def test_error_statuses_still_come_back_as_statuses(self):
        """The redirect handler must not change HTTPError behaviour."""
        checks_mod.set_network_policy(True)
        with _Server() as s:
            ok, ev = checks_mod.http_status({"path": "/missing", "expect": 200}, s.base)
        self.assertFalse(ok)
        self.assertEqual(ev["observed_status"], 404)

    def test_an_unresolvable_host_is_evidence_not_an_exception(self):
        ok, ev = checks_mod.http_status(
            {"path": "/", "expect": 200}, "http://nonexistent.invalid/")
        self.assertFalse(ok)
        self.assertTrue(ev["error"])


# ---------------------------------------------------------------- items 1+2: commands
class TestCommandApproval(unittest.TestCase):
    def test_approver_yes_runs_the_command(self):
        commands_mod.set_policy(commands_mod.CommandPolicy(
            enabled=True, allowed=("echo hi",), approver=lambda c, a: True))
        ok, ev = commands_mod.command_exit({"command": "echo hi"}, "local")
        self.assertTrue(ok)
        self.assertIn("hi", ev["stdout_tail"])

    def test_approver_no_is_not_run_not_fail(self):
        commands_mod.set_policy(commands_mod.CommandPolicy(
            enabled=True, allowed=("echo hi",), approver=lambda c, a: False))
        ok, ev = commands_mod.command_exit({"command": "echo hi"}, "local")
        self.assertIsNone(ok)
        self.assertEqual(ev["status"], "not_run")
        self.assertIn("allowed_commands", ev["refused"], "the refusal must name the setting")
        self.assertIn("how_to_fix", ev, "and carry the repair")

    def test_approver_that_raises_fails_closed(self):
        def boom(command, argv):
            raise RuntimeError("no asker bound")
        commands_mod.set_policy(commands_mod.CommandPolicy(
            enabled=True, allowed=("echo hi",), approver=boom))
        ok, ev = commands_mod.command_exit({"command": "echo hi"}, "local")
        self.assertIsNone(ok)
        self.assertIn("allowed_commands", ev["refused"], "the refusal must name the setting")
        self.assertIn("how_to_fix", ev, "and carry the repair")

    def test_approver_sees_the_exact_argv(self):
        seen = []
        commands_mod.set_policy(commands_mod.CommandPolicy(
            enabled=True, allowed=("echo hi there",),
            approver=lambda c, a: seen.append((c, a)) or True))
        commands_mod.command_exit({"command": "echo hi there"}, "local")
        self.assertEqual(seen, [("echo hi there", ["echo", "hi", "there"])])

    def test_child_gets_a_minimal_environment(self):
        os.environ["PROOFOPS_TEST_SECRET"] = "s3cr3t-value"
        try:
            commands_mod.set_policy(commands_mod.CommandPolicy(
                enabled=True, allowed=("env",)))
            ok, ev = commands_mod.command_exit({"command": "env"}, "local")
            self.assertTrue(ok)
            self.assertNotIn("s3cr3t-value", ev["stdout_tail"],
                             "the operator's full environment must not reach the child")
            self.assertIn("PATH=", ev["stdout_tail"])
            self.assertEqual(sorted(ev["env_keys"]), ["HOME", "LANG", "PATH"])
        finally:
            del os.environ["PROOFOPS_TEST_SECRET"]

    def test_operator_listed_variable_is_passed_through(self):
        os.environ["PROOFOPS_TEST_SECRET"] = "s3cr3t-value"
        try:
            commands_mod.set_policy(commands_mod.CommandPolicy(
                enabled=True, allowed=("env",), env_vars=("PROOFOPS_TEST_SECRET",)))
            ok, ev = commands_mod.command_exit({"command": "env"}, "local")
            self.assertTrue(ok)
            self.assertIn("PROOFOPS_TEST_SECRET=s3cr3t-value", ev["stdout_tail"])
        finally:
            del os.environ["PROOFOPS_TEST_SECRET"]


# ---------------------------------------------------------------- items 1+4: plugin surface
class TestPluginSurface(unittest.TestCase):
    def setUp(self):
        self._prev_ctx = PLUGIN._CTX
        self._prev_allow_local = checks_mod.allow_local_targets()
        checks_mod.set_network_policy(False)

    def tearDown(self):
        PLUGIN._CTX = self._prev_ctx
        checks_mod.set_network_policy(self._prev_allow_local)

    def test_the_tool_schema_has_no_allow_commands_and_no_out(self):
        schemas = {name: schema for name, schema, _fn in PLUGIN._TOOLS}
        props = set(schemas["proofops_run"]["parameters"]["properties"])
        self.assertEqual(props, {"plan", "target"}, f"unexpected parameters: {props}")

    def test_the_working_directory_plans_are_never_the_default(self):
        """A plan dropped into ./plans must not become what a model call picks up."""
        here = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "plans").mkdir()
            (pathlib.Path(d) / "plans" / "decoy.json").write_text(json.dumps({
                "name": "decoy", "target_kind": "local", "allowed_origins": [],
                "checks": [{"id": "c", "type": "command_exit", "command": "echo decoy",
                            "proves": "x"}],
                "allowed_commands": ["echo decoy"], "does_not_prove": ["x"]}))
            os.chdir(d)
            try:
                out = json.loads(PLUGIN._plans({}))
            finally:
                os.chdir(here)
        names = [p["file"] for p in out["plans"]]
        self.assertFalse(any(n.endswith("decoy.json") for n in names), names)
        self.assertGreaterEqual(len(out["plans"]), 5, "shipped plans are the default")

    def test_a_command_plan_is_not_run_without_operator_approval(self):
        PLUGIN._CTX = _FakeCtx(choice=None)  # no asker answer, nothing pre-approved
        with tempfile.TemporaryDirectory() as d:
            out = json.loads(PLUGIN._run(
                {"plan": str(_command_plan(d)), "target": "local"}))
        self.assertEqual(out["summary"]["verdict"], "INCOMPLETE")
        self.assertFalse(out["summary"]["claimable"])
        self.assertIn("allowed_commands", out["not_verified"][0]["reason"])

    def test_a_pre_approved_command_runs(self):
        PLUGIN._CTX = _FakeCtx(settings={"allowed_commands": ["echo hi"]})
        with tempfile.TemporaryDirectory() as d:
            out = json.loads(PLUGIN._run(
                {"plan": str(_command_plan(d)), "target": "local"}))
        self.assertEqual(out["summary"]["verdict"], "PASS", out)
        self.assertTrue(out["summary"]["claimable"])

    def test_an_unlisted_command_is_not_run_even_if_something_answers_yes(self):
        """Round two: there is no approval prompt to answer, so a `yes` cannot exist."""
        PLUGIN._CTX = _FakeCtx(choice="run")
        with tempfile.TemporaryDirectory() as d:
            out = json.loads(PLUGIN._run(
                {"plan": str(_command_plan(d)), "target": "local"}))
        self.assertEqual(out["summary"]["verdict"], "INCOMPLETE", out)
        self.assertEqual(PLUGIN._CTX.asked, [],
                         "the plugin must not pretend to ask an operator it cannot reach")

    def test_the_plugin_never_calls_ask_choice(self):
        source = (REPO / "__init__.py").read_text()
        self.assertNotIn("ask_choice", source,
                         "a tool call has nobody to ask; the config allowlist is the gate")

    def test_receipts_go_under_the_plugin_data_dir_not_where_the_model_says(self):
        with tempfile.TemporaryDirectory() as d:
            data = pathlib.Path(d) / "data"
            storage = types.ModuleType("plugins.plugin_storage")
            storage.plugin_data_dir = lambda name: str(data / name)
            plugins_pkg = types.ModuleType("plugins")
            plugins_pkg.plugin_storage = storage
            sys.modules["plugins"] = plugins_pkg
            sys.modules["plugins.plugin_storage"] = storage
            try:
                self.assertEqual(PLUGIN._receipt_dir(), data / "proofops" / "receipts")
                PLUGIN._CTX = _FakeCtx(settings={"allowed_paths": [d]})
                plan = pathlib.Path(d) / "plan.json"
                plan.write_text(json.dumps({
                    "name": "file plan", "target_kind": "local",
                    "allowed_origins": [], "allowed_paths": [d],
                    "checks": [{"id": "c", "type": "file_exists", "path": "plan.json",
                                "proves": "the plan file exists"}],
                    "does_not_prove": ["x"]}))
                out = json.loads(PLUGIN._run(
                    {"plan": str(plan), "target": "local", "out": "/tmp/evil"}))
                self.assertTrue(out["receipt"].startswith(str(data / "proofops")),
                                out["receipt"])
                self.assertFalse(out["receipt"].startswith("/tmp/evil"))
            finally:
                del sys.modules["plugins"]
                del sys.modules["plugins.plugin_storage"]


# ---------------------------------------------------------------- item 4: operator roots
class TestOperatorAllowedPaths(unittest.TestCase):
    def test_a_plan_root_outside_the_operator_roots_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root_a = pathlib.Path(d) / "a"
            root_b = pathlib.Path(d) / "b"
            root_a.mkdir()
            root_b.mkdir()
            (root_b / "f.txt").write_text("x")
            plan = pathlib.Path(d) / "plan.json"
            plan.write_text(json.dumps({
                "name": "p", "target_kind": "local", "allowed_origins": [],
                "allowed_paths": [str(root_b)],
                "checks": [{"id": "c", "type": "file_exists", "path": "f.txt",
                            "proves": "x"}],
                "does_not_prove": ["x"]}))
            with self.assertRaises(plan_mod.PlanError) as e:
                runner.execute(str(plan), "local", out=d,
                               operator_allowed_paths=(str(root_a),))
            self.assertIn("outside the operator-configured", str(e.exception))

    def test_a_plan_root_inside_the_operator_roots_runs(self):
        with tempfile.TemporaryDirectory() as d:
            root_b = pathlib.Path(d) / "b"
            root_b.mkdir()
            (root_b / "f.txt").write_text("x")
            plan = pathlib.Path(d) / "plan.json"
            plan.write_text(json.dumps({
                "name": "p", "target_kind": "local", "allowed_origins": [],
                "allowed_paths": [str(root_b)],
                "checks": [{"id": "c", "type": "file_exists", "path": "f.txt",
                            "proves": "x"}],
                "does_not_prove": ["x"]}))
            rec, _ = runner.execute(str(plan), "local", out=d,
                                    operator_allowed_paths=(d,))
            self.assertEqual(rec["summary"]["verdict"], "PASS")

    def test_an_empty_operator_list_allows_no_file_reads(self):
        with tempfile.TemporaryDirectory() as d:
            root_b = pathlib.Path(d) / "b"
            root_b.mkdir()
            (root_b / "f.txt").write_text("x")
            plan = pathlib.Path(d) / "plan.json"
            plan.write_text(json.dumps({
                "name": "p", "target_kind": "local", "allowed_origins": [],
                "allowed_paths": [str(root_b)],
                "checks": [{"id": "c", "type": "file_exists", "path": "f.txt",
                            "proves": "x"}],
                "does_not_prove": ["x"]}))
            with self.assertRaises(plan_mod.PlanError):
                runner.execute(str(plan), "local", out=d, operator_allowed_paths=())


if __name__ == "__main__":
    unittest.main(verbosity=2)
