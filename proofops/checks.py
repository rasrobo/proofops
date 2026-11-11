"""Check implementations.

Every check is read-only by construction: the only network verb is GET. A plan cannot
ask ProofOps to POST, PUT, DELETE or run a shell command — those belong to the tools that
perform repairs, not to the thing that verifies them.

Each check returns (passed: bool, evidence: dict). Evidence is what a reader needs to
judge the claim without trusting the verdict: the value observed, where it came from,
and how long it took.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 15
MAX_BODY = 2 * 1024 * 1024  # never pull more than 2 MB into a receipt

# HTTP checks reach public addresses only, unless the operator explicitly allows local
# targets (a local dev server). The default is deny: a plan — or a redirect it triggers —
# must not be able to reach loopback, private (RFC 1918) or link-local addresses,
# including the cloud metadata address, from a machine that may hold credentials.
_ALLOW_LOCAL = False


def set_network_policy(allow_local: bool) -> None:
    """Set by the runner for each run. Default False: local targets are refused."""
    global _ALLOW_LOCAL
    _ALLOW_LOCAL = bool(allow_local)


def allow_local_targets() -> bool:
    return _ALLOW_LOCAL


def _resolve_public(url: str) -> tuple[str, int, list[str]]:
    """Classify every address a URL names and return them to connect to.

    Raises ValueError with the reason. The hostname is resolved and *every* answer is
    classified: a name that resolves to both a public and a private address is refused,
    because the private answer may be the one used.

    The addresses returned are the ones the request is actually made to — `_get` pins the
    connection to this list. Checking a name and then letting urllib resolve it again leaves
    a DNS-rebinding window in which the second answer is the internal host; connecting only
    to addresses that were classified is what closes it.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"refusing non-HTTP(S) URL: {url}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"refusing URL with no host: {url}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve {host}: {e}")
    addresses: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if str(ip) in addresses:
            continue
        if not _ALLOW_LOCAL and (ip.is_private or ip.is_loopback or ip.is_link_local
                                 or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            raise ValueError(
                f"refusing {url}: {host} resolves to non-public address {ip}")
        addresses.append(str(ip))
    if not addresses:
        raise ValueError(f"cannot resolve {host}: no addresses")
    return host, port, addresses


def _pin(req: urllib.request.Request, host: str, addresses: list[str]) -> urllib.request.Request:
    """Attach the classified addresses to the request the connection classes read.

    Carried on the request rather than in a module global because a redirect hop is a
    different request with a different address.
    """
    setattr(req, "_proofops_host", host)           # name TLS checks the certificate against
    setattr(req, "_proofops_addresses", addresses)  # the addresses already classified
    return req


def _pinned(req: urllib.request.Request, name: str):
    """Read what `_pin` attached; a missing pin is a bug, and must not read as 'no host'."""
    return getattr(req, name)


def _open_socket(addresses: list[str], port: int, timeout):
    """Connect to one of the classified addresses, in order, with no new name lookup.

    All of them were classified, so trying the second after the first refuses cannot reach
    anything the check did not approve — and it keeps IPv4/IPv6 fallback working.
    """
    failure: OSError | None = None
    for address in addresses:
        try:
            return socket.create_connection((address, port), timeout)
        except OSError as e:  # refused, unreachable, timed out on this address only
            failure = e
    raise failure if failure is not None else OSError("no address to connect to")


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Plain HTTP to the classified addresses instead of a fresh lookup of the name."""

    def __init__(self, *args, pins: list[str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._pins = pins or []

    def connect(self):
        self.sock = _open_socket(self._pins, self.port, self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TLS to a classified address, certificate still checked against the hostname."""

    def __init__(self, *args, pins: list[str] | None = None,
                 server_hostname: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._pins = pins or []
        self._server_hostname = server_hostname

    def connect(self):
        # No proxy tunnel is possible: _get disables proxies, so a tunnel here would be a
        # hop nothing validated.
        sock = _open_socket(self._pins, self.port, self.timeout)
        context = getattr(self, "_context")  # set by HTTPSConnection.__init__
        self.sock = context.wrap_socket(sock, server_hostname=self._server_hostname)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(
            lambda *a, **kw: _PinnedHTTPConnection(
                *a, pins=_pinned(req, "_proofops_addresses"), **kw), req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(
            lambda *a, **kw: _PinnedHTTPSConnection(
                *a, pins=_pinned(req, "_proofops_addresses"),
                server_hostname=_pinned(req, "_proofops_host"),
                context=getattr(self, "_context"), **kw), req)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validate every redirect hop the same way as the first request, and pin it too."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host, _port, addresses = _resolve_public(newurl)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            _pin(new, host, addresses)
        return new


def _get(url: str) -> tuple[int | None, bytes, dict, float, str]:
    started = time.monotonic()
    try:
        host, _port, addresses = _resolve_public(url)
    except ValueError as e:
        return None, b"", {}, time.monotonic() - started, str(e)
    req = _pin(urllib.request.Request(url, method="GET",
                                      headers={"User-Agent": "proofops/0.1"}),
               host, addresses)
    # build_opener keeps the default handlers (including HTTPErrorProcessor, so error
    # statuses still come back as HTTPError below); ours replace only the connection and
    # redirect handlers. Environment proxies are disabled on purpose: through a proxy the
    # address we classified is not the address that is reached, so there is nothing to pin.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _SafeRedirectHandler(), _PinnedHTTPHandler(), _PinnedHTTPSHandler())
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            body = r.read(MAX_BODY)
            return r.status, body, dict(r.headers), time.monotonic() - started, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read(MAX_BODY), dict(e.headers or {}), time.monotonic() - started, ""
    except Exception as e:  # DNS, TLS, timeout, refusal, redirect to a private address
        return None, b"", {}, time.monotonic() - started, f"{type(e).__name__}: {e}"


def http_status(spec: dict, target: str) -> tuple[bool, dict]:
    url = target.rstrip("/") + spec["path"]
    status, _, _, elapsed, err = _get(url)
    want = int(spec["expect"])
    ok = status == want
    return ok, {
        "url": url,
        "expected_status": want,
        "observed_status": status,
        "elapsed_ms": round(elapsed * 1000),
        "error": err,
    }


def http_json_field(spec: dict, target: str) -> tuple[bool, dict]:
    """Assert one field of a JSON response.

    'equals' is exact (string compare after json parsing); 'contains' is a substring test
    for prose fields. Use 'equals' whenever the value is enumerable — a substring match
    on a status field would accept "not_ok".
    """
    url = target.rstrip("/") + spec["path"]
    field = spec["field"]
    status, body, _, elapsed, err = _get(url)
    observed = None
    parsed = False
    if body:
        try:
            doc = json.loads(body)
            parsed = True
            cur = doc
            for part in field.split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            observed = cur
        except Exception:
            parsed = False

    if "equals" in spec:
        ok = parsed and observed == spec["equals"]
        mode = "equals"
        want = spec["equals"]
    else:
        ok = parsed and observed is not None and str(spec["contains"]) in str(observed)
        mode = "contains"
        want = spec["contains"]

    return ok, {
        "url": url,
        "field": field,
        "mode": mode,
        "expected": want,
        "observed": observed,
        "body_parsed_as_json": parsed,
        "http_status": status,
        "elapsed_ms": round(elapsed * 1000),
        "error": err,
    }


def http_body_contains(spec: dict, target: str) -> tuple[bool, dict]:
    url = target.rstrip("/") + spec["path"]
    status, body, _, elapsed, err = _get(url)
    text = body.decode("utf-8", "replace")
    needle = spec["contains"]
    ok = needle in text
    return ok, {
        "url": url,
        "contains": needle,
        "http_status": status,
        "body_bytes": len(body),
        "observed_snippet": text[max(0, text.find(needle) - 40): text.find(needle) + len(needle) + 40]
        if needle in text else text[:120],
        "elapsed_ms": round(elapsed * 1000),
        "error": err,
    }


def http_header_equals(spec: dict, target: str) -> tuple[bool, dict]:
    url = target.rstrip("/") + spec["path"]
    status, _, headers, elapsed, err = _get(url)
    name = spec["header"]
    observed = None
    for k, v in headers.items():
        if k.lower() == name.lower():
            observed = v
    ok = observed is not None and str(spec["equals"]).lower() in str(observed).lower()
    return ok, {
        "url": url,
        "header": name,
        "expected_contains": spec["equals"],
        "observed": observed,
        "http_status": status,
        "elapsed_ms": round(elapsed * 1000),
        "error": err,
    }


from . import artifacts  # noqa: E402  (registered below)
from . import commands  # noqa: E402  (registered below)
from . import dbx  # noqa: E402  (registered below)
from . import pdfdoc  # noqa: E402  (registered below)

FILE_CHECK_TYPES = (
    "file_sha256", "file_exists", "dir_manifest", "csv_stats", "image_size",
    "pdf_pages", "pdf_page_size", "pdf_text_contains", "sqlite_query",
)

REGISTRY = {
    "command_exit": commands.command_exit,
    "file_sha256": artifacts.file_sha256,
    "file_exists": artifacts.file_exists,
    "dir_manifest": artifacts.dir_manifest,
    "csv_stats": artifacts.csv_stats,
    "image_size": artifacts.image_size,
    "pdf_pages": pdfdoc.pdf_pages,
    "pdf_page_size": pdfdoc.pdf_page_size,
    "pdf_text_contains": pdfdoc.pdf_text_contains,
    "sqlite_query": dbx.sqlite_query,
    "http_status": http_status,
    "http_json_field": http_json_field,
    "http_body_contains": http_body_contains,
    "http_header": http_header_equals,
}
