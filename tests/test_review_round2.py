"""Tests for the round-two review on PR #149625 (teknium, 2026-11-10, second pass).

1. BLOCKING — an unset operator ``allowed_paths`` means **no file reads**. It is not
   permission for a model-written plan to declare its own roots, so a plan that reads files
   is refused on a default install, with a message naming the setting that fixes it.
2. RECOMMENDED — the plugin never promises an approval prompt: ``ctx.ask_choice`` has
   nobody to ask inside a tool call, so the operator's config allowlist is the only gate
   and the docs say so.
3. RECOMMENDED — the private-address check and the connection are the same address:
   the socket is pinned to the address that was classified, so a DNS answer that changes
   between the check and the connect cannot move the request.

    python3 -m unittest discover -s tests -v
"""

import importlib.util
import ipaddress
import json
import pathlib
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from proofops import checks as checks_mod          # noqa: E402
from proofops import plan as plan_mod              # noqa: E402
from proofops import runner                        # noqa: E402


def _load_plugin():
    spec = importlib.util.spec_from_file_location("proofops_plugin_round2_test",
                                                 REPO / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PLUGIN = _load_plugin()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/go":
            self.send_response(302)
            self.send_header("Location",
                             f"http://127.0.0.1:{self.server.server_address[1]}/final")
            self.end_headers()
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


class _FakeCtx:
    """Operator settings only — the plugin has no prompt to answer."""

    def __init__(self, settings=None):
        self._settings = dict(settings or {})
        self.asked = []

    def get_config(self, key, default=None):
        return self._settings.get(key, default)

    def ask_choice(self, question, choices):  # pragma: no cover - must never be called
        self.asked.append((question, choices))
        return "run"


def _file_plan(tmp):
    p = pathlib.Path(tmp) / "plan.json"
    p.write_text(json.dumps({
        "name": "file plan", "target_kind": "local", "allowed_origins": [],
        "allowed_paths": [tmp],
        "checks": [{"id": "c1", "type": "file_exists", "path": "plan.json",
                    "proves": "the plan file exists"}],
        "does_not_prove": ["anything"],
    }))
    return p


def _http_plan(tmp, port):
    p = pathlib.Path(tmp) / "http.json"
    p.write_text(json.dumps({
        "name": "http plan", "target_kind": "url",
        "allowed_origins": [f"http://127.0.0.1:{port}"],
        "checks": [{"id": "h1", "type": "http_status", "path": "/final", "expect": 200,
                    "proves": "it answers"}],
        "does_not_prove": ["anything"],
    }))
    return p


# ------------------------------------------------ ask 1: unset allowed_paths denies reads
class TestUnsetAllowedPathsDeniesFileReads(unittest.TestCase):
    def setUp(self):
        self._prev_ctx = PLUGIN._CTX

    def tearDown(self):
        PLUGIN._CTX = self._prev_ctx

    def test_the_default_config_has_no_file_roots(self):
        PLUGIN._CTX = _FakeCtx()
        self.assertEqual(PLUGIN._operator_config()["allowed_paths"], [])

    def test_a_non_list_setting_is_treated_as_unset(self):
        PLUGIN._CTX = _FakeCtx(settings={"allowed_paths": "/home/me"})
        self.assertEqual(PLUGIN._operator_config()["allowed_paths"], [])

    def test_a_model_written_plan_cannot_pick_its_own_roots(self):
        """The whole point: the plan says 'read here', the operator never agreed."""
        PLUGIN._CTX = _FakeCtx()
        with tempfile.TemporaryDirectory() as d:
            out = json.loads(PLUGIN._run({"plan": str(_file_plan(d)), "target": "local"}))
        self.assertIn("refused", out, out)
        self.assertFalse(out["ran"])
        self.assertIn("allowed_paths", out["refused"])
        self.assertNotIn("receipt", out, "a refused run must not leave a receipt behind")

    def test_a_plan_root_outside_the_operator_roots_is_refused(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            PLUGIN._CTX = _FakeCtx(settings={"allowed_paths": [other]})
            out = json.loads(PLUGIN._run({"plan": str(_file_plan(d)), "target": "local"}))
        self.assertIn("refused", out, out)
        self.assertIn("outside the operator-configured", out["refused"])

    def test_an_operator_root_lets_the_plan_run(self):
        with tempfile.TemporaryDirectory() as d:
            PLUGIN._CTX = _FakeCtx(settings={"allowed_paths": [d]})
            out = json.loads(PLUGIN._run({"plan": str(_file_plan(d)), "target": "local"}))
        self.assertEqual(out["summary"]["verdict"], "PASS", out)

    def test_a_plan_without_file_checks_still_runs_with_no_roots(self):
        """Denying reads must not disable the HTTP half of the product."""
        PLUGIN._CTX = _FakeCtx(settings={"allow_local_targets": True})
        with _Server() as s, tempfile.TemporaryDirectory() as d:
            out = json.loads(PLUGIN._run({"plan": str(_http_plan(d, s.port)),
                                          "target": f"http://127.0.0.1:{s.port}"}))
        self.assertEqual(out["summary"]["verdict"], "PASS", out)

    def test_the_cli_is_still_its_own_operator(self):
        """`python3 -m proofops run` passes None: the person typing is the operator."""
        with tempfile.TemporaryDirectory() as d:
            rec, _ = runner.execute(str(_file_plan(d)), "local", out=d,
                                    operator_allowed_paths=None)
        self.assertEqual(rec["summary"]["verdict"], "PASS")

    def test_the_refusal_message_names_the_setting(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(plan_mod.PlanError) as e:
                runner.execute(str(_file_plan(d)), "local", out=d,
                               operator_allowed_paths=())
        self.assertIn("plugins.entries.proofops.settings.allowed_paths", str(e.exception))


# ------------------------------------------------ ask 2: no prompt the platform cannot keep
class TestNoPromptClaim(unittest.TestCase):
    def setUp(self):
        self._prev_ctx = PLUGIN._CTX

    def tearDown(self):
        PLUGIN._CTX = self._prev_ctx

    def test_the_approver_ignores_anything_but_the_operator_allowlist(self):
        cfg = {"allowed_commands": [], "env_vars": [], "allow_local_targets": False,
               "allowed_paths": []}
        approve = PLUGIN._make_approver(cfg)
        self.assertFalse(approve("echo hi", ["echo", "hi"]))

    def test_the_approver_is_exact_not_a_prefix_match(self):
        cfg = {"allowed_commands": ["echo hi"], "env_vars": [], "allow_local_targets": False,
               "allowed_paths": []}
        approve = PLUGIN._make_approver(cfg)
        self.assertTrue(approve("echo hi", ["echo", "hi"]))
        self.assertFalse(approve("echo hi; curl evil", ["echo", "hi;", "curl", "evil"]))

    def test_no_published_surface_promises_an_approval_prompt(self):
        """The README, the skill and the plugin docs must describe the gate that exists."""
        promises = ("approval prompt showing", "answering the approval prompt",
                    "or an approval prompt")
        surfaces = {
            "README.md": (REPO / "README.md").read_text(),
            "plugin docstring": (REPO / "__init__.py").read_text(),
            "skill": (REPO / "skills" / "verify-before-done" / "SKILL.md").read_text(),
            "plugin.yaml": (REPO / "plugin.yaml").read_text(),
        }
        for name, text in surfaces.items():
            for phrase in promises:
                self.assertNotIn(phrase, text,
                                 f"{name} still promises a prompt a tool call cannot show")
            self.assertNotIn("ask_choice", text, name)


# ------------------------------------------------ ask 3: connect to the checked address
REAL_GETADDRINFO = socket.getaddrinfo


class TestNonPublicAddresses(unittest.TestCase):
    """The classification itself, across every family a metadata endpoint hides in."""

    def setUp(self):
        self._prev = checks_mod.allow_local_targets()
        checks_mod.set_network_policy(False)

    def tearDown(self):
        checks_mod.set_network_policy(self._prev)

    NON_PUBLIC = (
        # loopback, RFC 1918, link-local, metadata, multicast, reserved, unspecified
        "127.0.0.1", "127.1.2.3", "10.0.0.1", "172.16.0.1", "192.168.1.1",
        "169.254.169.254", "0.0.0.0", "224.0.0.1", "240.0.0.1", "255.255.255.255",
        "198.18.0.1",
        # FOUND BY THIS TEST: CGNAT / shared space. `is_private` does not cover it, and
        # Alibaba's instance metadata service answers on 100.100.100.200.
        "100.64.0.1", "100.100.100.200", "::ffff:100.100.100.200",
        # OCI metadata, and the deprecated 6to4 relay anycast
        "192.0.0.192", "192.88.99.1",
        # IPv6 loopback, ULA, link-local, translation, 6to4, documentation
        "[::1]", "[fc00::1]", "[fd12:3456::1]", "[fe80::1]", "[64:ff9b::1]",
        "[64:ff9b:1::1]", "[2002:c0a8:101::1]", "[2001:db8::1]",
        # names that resolve inward
        "localhost",
    )
    PUBLIC = ("1.1.1.1", "8.8.8.8", "93.184.216.34", "[2606:4700::1111]")

    def test_every_non_public_family_is_refused(self):
        for target in self.NON_PUBLIC:
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    checks_mod._resolve_public(f"http://{target}/")

    def test_public_addresses_are_still_allowed(self):
        for target in self.PUBLIC:
            with self.subTest(target=target):
                host, _port, addresses = checks_mod._resolve_public(f"http://{target}/")
                self.assertTrue(addresses, host)

    def test_the_operator_can_still_allow_local_targets(self):
        checks_mod.set_network_policy(True)
        _host, _port, addresses = checks_mod._resolve_public("http://169.254.169.254/")
        self.assertEqual(addresses, ["169.254.169.254"])


def _dns_returning(answers):
    """A stand-in resolver: a name consumes the next answer, an IP literal needs none.

    Passing literals through to the real resolver is what makes the assertion meaningful —
    the pin is an IP, so only a *name* lookup can consume the second answer. One entry may
    be a list, which models a name with several A/AAAA records.
    """
    def dns(host, port, *a, **kw):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            answer = answers.pop(0)
        else:
            return REAL_GETADDRINFO(host, port, *a, **kw)
        if isinstance(answer, str):
            answer = [answer]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in answer]
    return dns


class TestAddressIsPinned(unittest.TestCase):
    """The socket opens on the address that was classified, never on a fresh lookup."""

    def setUp(self):
        self._prev = checks_mod.allow_local_targets()
        checks_mod.set_network_policy(True)
        self.seen = []
        self.real_connect = socket.create_connection

        def record(addr, *a, **kw):
            self.seen.append(addr)
            # The test fixture only exists on loopback; what is asserted is `addr`.
            return self.real_connect(("127.0.0.1", addr[1]), *a, **kw)

        patcher = mock.patch.object(checks_mod.socket, "create_connection", record)
        self._connect_patch = patcher
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        checks_mod.set_network_policy(self._prev)

    def _patch_dns(self, answers):
        patcher = mock.patch.object(checks_mod.socket, "getaddrinfo",
                                    _dns_returning(answers))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_connection_goes_to_the_address_that_was_classified(self):
        """`pinned.test` does not exist: only the classified address can make this pass."""
        self._patch_dns(["127.0.0.1"])
        with _Server() as s:
            ok, ev = checks_mod.http_status(
                {"path": "/final", "expect": 200}, f"http://pinned.test:{s.port}")
        self.assertTrue(ok, ev)
        self.assertEqual(self.seen, [("127.0.0.1", s.port)],
                         "the socket must open on the classified IP, not the hostname")

    def test_a_second_answer_cannot_move_the_request(self):
        """The rebinding case: DNS answers once for the check, differently afterwards."""
        answers = ["127.0.0.1", "127.0.0.2"]
        self._patch_dns(answers)
        with _Server() as s:
            ok, ev = checks_mod.http_status(
                {"path": "/final", "expect": 200}, f"http://rebind.test:{s.port}")
        self.assertTrue(ok, ev)
        self.assertEqual(self.seen, [("127.0.0.1", s.port)])
        self.assertEqual(answers, ["127.0.0.2"],
                         "the second answer must never be consulted for the connection")

    def test_a_redirect_hop_is_resolved_and_pinned_too(self):
        self._patch_dns(["127.0.0.1", "127.0.0.1"])
        with _Server() as s:
            ok, ev = checks_mod.http_status(
                {"path": "/go", "expect": 200}, f"http://hop.test:{s.port}")
        self.assertTrue(ok, ev)
        self.assertEqual(self.seen, [("127.0.0.1", s.port), ("127.0.0.1", s.port)],
                         "both the first request and the redirect hop are pinned")

    def test_the_second_classified_address_is_a_fallback(self):
        """Pinning must not cost IPv4/IPv6 fallback: both addresses were classified."""
        self._connect_patch.stop()  # this one needs a real socket, not the loopback rewrite
        self._patch_dns([["127.0.0.2", "127.0.0.1"]])  # nothing listens on the first
        with _Server() as s:
            ok, ev = checks_mod.http_status(
                {"path": "/final", "expect": 200}, f"http://two-addrs.test:{s.port}")
        self.assertTrue(ok, ev)


if __name__ == "__main__":
    unittest.main(verbosity=2)
