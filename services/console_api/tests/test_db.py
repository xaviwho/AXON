"""SQLite store tests."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.console_api.app.db import AuditDB

NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


def _audit(i: int, *, action_id="power_cutoff", severity=4, effect="success",
           trigger_id="t-1", offset_s: float = 0) -> dict:
    # Distinct audits never share a timestamp in practice; +i ms keeps them
    # distinct here too (identical ones are treated as a bus replay).
    return {
        "timestamp": (NOW + timedelta(seconds=offset_s, milliseconds=i)).isoformat(),
        "trigger_id": trigger_id, "action_id": action_id, "severity": severity,
        "effect": effect, "agent_confidence": 0.9,
        "layer_d_trace": f"trace-{i}", "parameters": {"zone_id": "lab-A"},
        "latency_ms": 1.0 + i,
    }


@pytest.fixture
def db(tmp_path) -> AuditDB:
    return AuditDB(tmp_path / "console.db")


@pytest.mark.asyncio
async def test_insert_and_get_audit(db):
    entry_id = await db.insert_audit(_audit(0))
    row = await db.get_audit(entry_id)
    assert row["action_id"] == "power_cutoff"
    assert row["trigger_id"] == "t-1"
    assert row["parameters"] == {"zone_id": "lab-A"}


@pytest.mark.asyncio
async def test_replayed_audit_is_not_duplicated(db):
    """Console restarts backfill from the bus; the same entry must not land twice."""
    first = await db.insert_audit(_audit(0))
    again = await db.insert_audit(_audit(0))
    assert again == first
    _rows, total = await db.list_audits()
    assert total == 1


@pytest.mark.asyncio
async def test_tampered_copy_of_stored_audit_still_lands(db):
    """Dedupe must not swallow a tampered entry that reuses a real one's identity."""
    real = _audit(0)
    await db.insert_audit({**real, "signature": "aa" * 32}, signature_valid=True)
    tampered = {**real, "signature": "aa" * 32, "parameters": {"zone_id": "lab-Z"}}
    await db.insert_audit(tampered, signature_valid=False)
    _rows, total = await db.list_audits()
    assert total == 2


@pytest.mark.asyncio
async def test_list_audit_filters(db):
    for i in range(6):
        action = "power_cutoff" if i % 2 == 0 else "door_lock"
        severity = 4 if i < 3 else 1
        await db.insert_audit(_audit(i, action_id=action, severity=severity,
                                     trigger_id="t-A" if i < 3 else "t-B"))

    # severity filter
    rows, total = await db.list_audits(severity=4)
    assert total == 3
    assert all(r["severity"] == 4 for r in rows)

    # action_id filter
    rows, total = await db.list_audits(action_id="door_lock")
    assert total == 3
    assert {r["action_id"] for r in rows} == {"door_lock"}

    # trigger_id filter
    rows, total = await db.list_audits(trigger_id="t-A")
    assert total == 3

    # pagination
    rows, total = await db.list_audits(limit=2, offset=2)
    assert total == 6
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_get_incident_joins_all_tables(db):
    tid = "t-XYZ"
    await db.upsert_anomaly({
        "trigger_id": tid, "timestamp": NOW.isoformat(),
        "composite_score": 0.7, "trigger_reason": "thermal_threshold",
        "contributing_signals": [{"source": "s", "weight": 0.6}],
    })
    await db.upsert_scene({
        "trigger_id": tid, "timestamp": NOW.isoformat(), "location": "lab-A",
        "hazards": [{"hazard_type": "fire", "severity": "high"}],
        "people_present": [], "equipment_state": [],
        "contextual_factors": {"trigger_reason": "thermal_threshold"},
    })
    await db.upsert_plan({
        "trigger_id": tid, "timestamp": NOW.isoformat(), "severity": 4,
        "confidence": 1.0, "rationale": "fire protocol",
        "actions": [{"action_id": "power_cutoff", "parameters": {}, "requested_latency_ms": 80}],
        "audit_metadata": {"layer_d_trace": "fire"},
    })
    for i in range(2):
        await db.insert_audit(_audit(i, trigger_id=tid))

    incident = await db.get_incident(tid)
    assert incident is not None
    assert incident["anomaly"]["composite_score"] == 0.7
    assert incident["scene"]["location"] == "lab-A"
    assert incident["plan"]["confidence"] == 1.0
    assert len(incident["audits"]) == 2


@pytest.mark.asyncio
async def test_upsert_idempotent(db):
    tid = "t-IDEM"
    await db.upsert_anomaly({
        "trigger_id": tid, "timestamp": NOW.isoformat(),
        "composite_score": 0.5, "trigger_reason": "x", "contributing_signals": [],
    })
    await db.upsert_anomaly({
        "trigger_id": tid, "timestamp": NOW.isoformat(),
        "composite_score": 0.9, "trigger_reason": "x", "contributing_signals": [],
    })
    counts = await db.counts()
    assert counts["anomalies"] == 1


@pytest.mark.asyncio
async def test_recent_incidents_ordered_by_time(db):
    for i in range(3):
        await db.upsert_anomaly({
            "trigger_id": f"t-{i}",
            "timestamp": (NOW + timedelta(seconds=i)).isoformat(),
            "composite_score": 0.5 + i * 0.1,
            "trigger_reason": "x", "contributing_signals": [],
        })
    rows = await db.recent_incidents(limit=10)
    assert [r["trigger_id"] for r in rows] == ["t-2", "t-1", "t-0"]


def test_opens_legacy_db_without_signature_columns(tmp_path):
    """A console.db created before signed audits must migrate, not crash startup."""
    import sqlite3

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE audit_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            trigger_id TEXT, action_id TEXT NOT NULL, severity INTEGER NOT NULL,
            effect TEXT NOT NULL, agent_confidence REAL NOT NULL,
            layer_d_trace TEXT NOT NULL, parameters_json TEXT, latency_ms REAL
        );
    """)
    conn.close()

    db = AuditDB(path)
    cols = {r[1] for r in db._conn.execute("PRAGMA table_info(audit_entries)")}
    assert {"phase", "signature_hex", "signature_valid"} <= cols
