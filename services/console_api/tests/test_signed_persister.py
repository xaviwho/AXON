"""End-to-end signed-audit persistence.

Dispatcher signs → bus → persister verifies → SQLite mirrors the flag.
Uses an in-memory `_MemoryBus` to feed synthetic audit payloads and a
temporary SQLite file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.console_api.app.db import AuditDB
from services.console_api.app.persistence import BusPersister, EventHub
from shared.audit_signing import sign_entry


class _StubBus:
    """Fake bus surface exposing only what BusPersister touches."""

    healthy = True

    def __init__(self):
        self._client = _StubRedis()

    async def consume_streams(self, *_a, **_kw):
        # Not exercised in these tests — we drive the persister directly
        # via _handle().
        if False:
            yield None
        return


class _StubRedis:
    async def xrange(self, *_a, **_kw):
        return []


@pytest.fixture
def key(monkeypatch) -> str:
    k = "b" * 64
    monkeypatch.setenv("AXON_AUDIT_SIGNING_KEY", k)
    return k


@pytest.fixture
def persister(tmp_path: Path, key: str):
    db = AuditDB(tmp_path / "audit.db")
    hub = EventHub()
    p = BusPersister(bus=_StubBus(), db=db, hub=hub)
    yield p, db


def _signed_audit(action_id: str = "power_cutoff") -> dict:
    e = {
        "timestamp": "2026-05-15T12:00:00+00:00",
        "severity": 4,
        "layer_d_trace": "phase-1 gated protocol",
        "action_id": action_id,
        "effect": "success",
        "agent_confidence": 1.0,
        "trigger_id": "t-signed",
        "parameters": {"zone_id": "lab-A"},
        "latency_ms": 22.5,
        "phase": 1,
    }
    e["signature"] = sign_entry(e)
    return e


@pytest.mark.asyncio
async def test_signed_audit_lands_with_valid_flag(persister):
    p, db = persister
    import json
    payload = _signed_audit()
    await p._handle("axon:audit", {b"data": json.dumps(payload).encode()})

    rows, total = await db.list_audits(limit=10)
    assert total == 1
    assert rows[0]["signature_valid"] is True
    assert rows[0]["phase"] == 1
    assert rows[0]["signature_hex"] == payload["signature"]


@pytest.mark.asyncio
async def test_tampered_audit_lands_with_invalid_flag(persister):
    p, db = persister
    import json
    payload = _signed_audit()
    # Attacker rewrites the action after signing.
    payload["action_id"] = "door_unlock"
    await p._handle("axon:audit", {b"data": json.dumps(payload).encode()})

    rows, total = await db.list_audits(limit=10)
    assert total == 1
    assert rows[0]["signature_valid"] is False
    assert rows[0]["action_id"] == "door_unlock"    # persisted so we have a record


@pytest.mark.asyncio
async def test_unsigned_audit_lands_with_invalid_flag(persister):
    p, db = persister
    import json
    payload = _signed_audit()
    payload.pop("signature")
    await p._handle("axon:audit", {b"data": json.dumps(payload).encode()})

    rows, _ = await db.list_audits(limit=10)
    assert rows[0]["signature_valid"] is False
    assert rows[0]["signature_hex"] is None
