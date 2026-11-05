"""PDF checks — "the report shipped, and it says what we said it says".

PDFs are the estate's most common deliverable and its least verified one: a build that emits a
broken page, drops a page, or renders a blank instead of text passes every file-exists check in
the world.

Scope, stated honestly in the evidence of every check:

* **pages** — read from the page tree ``/Count``, falling back to counting page objects. The
  method used is reported, because "counted from the tree" and "counted page objects" are not
  the same evidence.
* **page size** — the first page's ``/MediaBox`` in points. Not DPI, not bleed, not trim.
* **text contains** — decompress content streams and read the literal strings before ``Tj`` /
  ``TJ``. This works for ordinary text PDFs and **does not** work for scanned pages or CID/Type0
  fonts without a ToUnicode map. When it cannot extract text it says so instead of reporting the
  text as missing: "we could not read this" and "this is not there" are different answers, and
  conflating them is exactly the overclaim this tool exists to prevent.

No third-party parser: pypdf and friends are a dependency tree in someone's install, and the
three questions above are answerable from the bytes.
"""

from __future__ import annotations

import re
import zlib

from . import artifacts
# Deliberately attribute access, not `from .artifacts import POLICY`: the runner installs the
# plan's policy by rebinding artifacts.POLICY, and a name imported at module load keeps the
# old object — every PDF check would then be refused with "plan declares no allowed_paths".
MAX_FILE = artifacts.MAX_FILE
_evidence = artifacts._evidence



_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_TJ_ARRAY = re.compile(rb"\[(.*?)\]\s*TJ", re.S)
_TJ_SINGLE = re.compile(rb"\((.*?)\)\s*Tj", re.S)
_STRING = re.compile(rb"\((?:\\.|[^\\()])*\)")


def _read(spec: dict) -> tuple[bytes | None, dict]:
    path, why = artifacts.POLICY.resolve(spec["path"])
    if path is None:
        return None, {"path": spec["path"], "error": why}
    try:
        import os

        if not os.path.isfile(path):
            return None, {"path": path, "error": "file does not exist"}
        if os.path.getsize(path) > MAX_FILE:
            return None, {"path": path, "error": f"file larger than the {MAX_FILE} byte cap"}
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        return None, {"path": path, "error": f"{type(e).__name__}: {e}"}
    if not data.startswith(b"%PDF-"):
        return None, {"path": path, "error": "not a PDF (missing %PDF- header)"}
    return data, _evidence(path)


def _page_count(data: bytes) -> tuple[int | None, str]:
    tree = re.search(rb"/Type\s*/Pages\b.{0,200}?/Count\s+(\d+)", data, re.S)
    if tree:
        return int(tree.group(1)), "page tree /Count"
    rev = re.search(rb"/Count\s+(\d+).{0,200}?/Type\s*/Pages\b", data, re.S)
    if rev:
        return int(rev.group(1)), "page tree /Count (reverse order)"
    loose = len(re.findall(rb"/Type\s*/Page\b(?!s)", data))
    if loose:
        return loose, "counted /Type /Page objects"
    return None, "no page tree found (compressed object streams are not supported)"


def pdf_pages(spec: dict, _target: str) -> tuple[bool, dict]:
    data, ev = _read(spec)
    if data is None:
        return False, ev
    observed, method = _page_count(data)
    want = int(spec["equals"])
    if observed is None:
        return False, {**ev, "error": method}
    return observed == want, {**ev, "expected_pages": want, "observed_pages": observed,
                              "method": method}


def pdf_page_size(spec: dict, _target: str) -> tuple[bool, dict]:
    data, ev = _read(spec)
    if data is None:
        return False, ev
    m = re.search(rb"/MediaBox\s*\[\s*([\d.+-]+)\s+([\d.+-]+)\s+([\d.+-]+)\s+([\d.+-]+)\s*\]",
                  data)
    if not m:
        return False, {**ev, "error": "no /MediaBox found on the first page"}
    x0, y0, x1, y1 = (float(v) for v in m.groups())
    w, h = round(x1 - x0, 2), round(y1 - y0, 2)
    want_w, want_h = float(spec["width"]), float(spec["height"])
    ok = (round(w, 2), round(h, 2)) == (round(want_w, 2), round(want_h, 2))
    return ok, {**ev, "expected": f"{want_w}x{want_h}pt", "observed": f"{w}x{h}pt"}


def _extract_text(data: bytes) -> tuple[str, dict]:
    chunks: list[str] = []
    decoded_streams = 0
    for raw in _STREAM.findall(data):
        # A stream without /Filter is already plain text; only try inflating it (and only
        # fall back to the raw bytes when inflating fails) — the first version skipped every
        # uncompressed stream, so an ordinary PDF looked like a scanned page.
        try:
            body = zlib.decompress(raw)
            decoded_streams += 1
        except zlib.error:
            body = raw
        for blob in _TJ_ARRAY.findall(body) + [body]:
            for s in _STRING.findall(blob):
                inner = s[1:-1].replace(b"\\(", b"(").replace(b"\\)", b")")
                chunks.append(inner.decode("latin-1"))
    return " ".join(chunks), {"decoded_streams": decoded_streams}


def pdf_text_contains(spec: dict, _target: str) -> tuple[bool, dict]:
    data, ev = _read(spec)
    if data is None:
        return False, ev
    text, meta = _extract_text(data)
    needle = spec["contains"]
    found = needle in text
    evidence = {
        **ev,
        **meta,
        "contains": needle,
        "characters_extracted": len(text),
        "snippet": text[:200],
    }
    if not text.strip():
        # Not the same answer as "the text is missing": we could not read this document.
        evidence["error"] = (
            "no extractable text — scanned page, or a font encoding without ToUnicode. "
            "This check cannot answer the question for this PDF."
        )
        return False, evidence
    return found, evidence
