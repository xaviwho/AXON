"""HMAC-SHA256 signing and verification for AuditEntry records.

The audit stream is the chain-of-custody surface for AXON: every actuator
command lands there, and downstream analysis (the console persister, the
SQLite mirror, third-party incident review) reads from it. Signing each
entry at the point of dispatch lets a verifier detect any post-facto
edit, and lets the persister drop rows that fail verification instead of
silently mirroring them.

Design constraints:

- **Canonicalization is stable.** The signed payload is the JSON of the
  entry with sorted keys and the ``signature`` field itself removed;
  otherwise the presence of the signature would participate in the
  signature it purports to authenticate.
- **Key comes from the environment.** ``AXON_AUDIT_SIGNING_KEY`` supplies
  the shared secret. When unset, the dispatcher generates a per-process
  random key and logs a loud warning so dev runs still produce verifiable
  audits but nobody accidentally ships without configuring one.
- **Signature is a hex string.** 64 hex chars = HMAC-SHA256; stays
  transport-friendly on Redis streams and inside JSON columns.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from typing import Any

from loguru import logger

_ENV_VAR = "AXON_AUDIT_SIGNING_KEY"
_DEV_KEY_ONCE: dict[str, str] = {}
SIGNATURE_FIELD = "signature"


def resolve_signing_key() -> str:
    """Return the shared signing key, generating a dev key on first miss.

    A missing key is a deployment error in production; in dev we still
    want the pipeline to run, so we synthesize one and cache it for the
    lifetime of the process. The warning is fired exactly once.
    """
    key = os.environ.get(_ENV_VAR)
    if key:
        return key
    if "dev" not in _DEV_KEY_ONCE:
        _DEV_KEY_ONCE["dev"] = secrets.token_hex(32)
        logger.warning(
            "audit signing: {} not set — generated an ephemeral dev key. "
            "Audits will verify inside this process only. Set {} for prod.",
            _ENV_VAR, _ENV_VAR,
        )
    return _DEV_KEY_ONCE["dev"]


def _canonical_bytes(entry: dict[str, Any]) -> bytes:
    stripped = {k: v for k, v in entry.items() if k != SIGNATURE_FIELD}
    return json.dumps(
        stripped, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def sign_entry(entry: dict[str, Any], *, key: str | None = None) -> str:
    """Return the hex HMAC-SHA256 signature over the entry's canonical form."""
    k = (key or resolve_signing_key()).encode("utf-8")
    return hmac.new(k, _canonical_bytes(entry), hashlib.sha256).hexdigest()


def verify_entry(entry: dict[str, Any], *, key: str | None = None) -> bool:
    """True iff ``entry[SIGNATURE_FIELD]`` matches the recomputed signature."""
    provided = entry.get(SIGNATURE_FIELD)
    if not provided or not isinstance(provided, str):
        return False
    expected = sign_entry(entry, key=key)
    return hmac.compare_digest(provided, expected)


__all__ = [
    "SIGNATURE_FIELD",
    "resolve_signing_key",
    "sign_entry",
    "verify_entry",
]
