"""Sealing: what makes a receipt evidence rather than a text file.

Threat model, stated plainly:

* **What sealing stops.** Someone (a person, or an agent that is "helpfully" tidying up)
  editing a written receipt afterwards — flipping FAIL to PASS, deleting a limitation,
  changing an observed value. Any byte change breaks the digest.
* **What sealing does not stop.** Someone who has the signing key, or who re-runs the tool
  and writes a fresh receipt. A receipt is evidence that *this run observed this*, not a
  proof that the run happened, that the plan was honest, or that the observer is truthful.

Two levels, because most users will not manage a key:

* ``sha256`` digest — always present. Detects editing after writing. Says nothing about
  who wrote it: an attacker who rewrites the body can also rewrite the digest.
* ``hmac-sha256`` — used when a key is supplied (``--key-file`` or ``PROOPS_SIGNING_KEY``).
  Now a third party holding the same key can prove *which* key sealed it, and an editor
  without the key cannot re-seal after changing the body.

The receipt is the product, so this module is deliberately small and has no dependencies
beyond the standard library. Verification must be something a sceptical reader can do
themselves: ``python3 -m proofops verify receipts/PO-....json``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import pathlib

SCHEMA = "proofops.integrity/1"
KEY_ENV = "PROOPS_SIGNING_KEY"


def canonical(receipt: dict) -> bytes:
    """Stable bytes for hashing: any key order, any indentation, same digest."""
    body = {k: v for k, v in receipt.items() if k != "integrity"}
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(receipt: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical(receipt)).hexdigest()


def key_id(key: str) -> str:
    """Public fingerprint of a key, so a receipt can name its signer without leaking it."""
    return "sha256:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def seal(receipt: dict, key: str | None = None) -> dict:
    """Attach the integrity block, in place, and return the receipt."""
    body_digest = digest(receipt)
    block = {"schema": SCHEMA, "alg": "sha256", "digest": body_digest, "signed": False}
    if key:
        block.update({
            "alg": "hmac-sha256",
            "signed": True,
            "key_id": key_id(key),
            "mac": hmac.new(key.encode("utf-8"), body_digest.encode(), hashlib.sha256).hexdigest(),
        })
    receipt["integrity"] = block
    return receipt


def verify(receipt: dict, key: str | None = None) -> tuple[str, dict]:
    """Return (verdict, detail) where verdict is one of:

    ``valid``      — the body matches the sealed digest (and signature, when signed)
    ``tampered``   — the body was changed after sealing, or the key does not match
    ``unsealed``   — there is no integrity block; nothing can be concluded
    ``needs-key``  — the receipt is signed and no key was supplied, so it cannot be checked
    """
    block = receipt.get("integrity")
    if not isinstance(block, dict) or "digest" not in block:
        return "unsealed", {
            "detail": "no integrity block — this file could have been written by anything",
        }
    actual = digest(receipt)
    if actual != block["digest"]:
        return "tampered", {
            "detail": "the body does not match the sealed digest — it was edited after writing",
            "sealed": block["digest"],
            "recomputed": actual,
        }
    if block.get("alg") == "hmac-sha256":
        if not key:
            return "needs-key", {
                "detail": "receipt is signed; verification needs the same key",
                "key_id": block.get("key_id"),
            }
        mac = hmac.new(key.encode("utf-8"), block["digest"].encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, str(block.get("mac", ""))):
            return "tampered", {
                "detail": "signature does not match this key — either the body or the key is wrong",
                "key_id": block.get("key_id"),
                "supplied_key_id": key_id(key),
            }
        return "valid", {
            "detail": "digest and signature match",
            "key_id": block.get("key_id"),
            "signed": True,
        }
    return "valid", {
        "detail": (
            "digest matches — the file has not been edited since it was sealed. "
            "It is NOT signed: anyone who rewrites the body could also rewrite the digest."
        ),
        "signed": False,
    }


def key_from(value: str | pathlib.Path | None) -> str | None:
    """Resolve a key given as literal text, a path, or an environment variable."""
    import os

    if value is None:
        value = os.environ.get(KEY_ENV)
        if not value:
            return None
    text = str(value)
    p = pathlib.Path(text)
    try:
        if p.is_file():
            text = p.read_text().strip()
    except (OSError, ValueError):
        pass
    return text or None
