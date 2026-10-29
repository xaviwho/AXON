"""SQLite-backed audit store.

Tables are intentionally simple: the bus is the source of truth, this DB
is a queryable mirror. The tailer in `persistence.py` keeps it warm. All
writes go through `AuditDB`; routes only read.

Schema migration is hand-rolled (one statement each) — too small to
justify alembic. When PostgreSQL replaces SQLite, the same SQL works.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    trigger_id      TEXT,
    action_id       TEXT    NOT NULL,
    severity        INTEGER NOT NULL,
    effect          TEXT    NOT NULL,
    agent_confidence REAL   NOT NULL,
    layer_d_trace   TEXT    NOT NULL,
    parameters_json TEXT,
    latency_ms      REAL,
    phase           INTEGER NOT NULL DEFAULT 1,
    signature_hex   TEXT,
    signature_valid INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_audit_trigger ON audit_entries(trigger_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_entries(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_entries(action_id);

CREATE TABLE IF NOT EXISTS anomalies (
    trigger_id            TEXT PRIMARY KEY,
    timestamp             TEXT NOT NULL,
    composite_score       REAL NOT NULL,
    trigger_reason        TEXT NOT NULL,
    contributing_signals  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenes (
    trigger_id      TEXT PRIMARY KEY,
    timestamp       TEXT NOT NULL,
    location        TEXT NOT NULL,
    hazards         TEXT NOT NULL,
    people_present  TEXT NOT NULL,
    equipment_state TEXT NOT NULL,
    contextual_factors TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    trigger_id     TEXT PRIMARY KEY,
    timestamp      TEXT NOT NULL,
    severity       INTEGER NOT NULL,
    confidence     REAL NOT NULL,
    rationale      TEXT NOT NULL,
    actions        TEXT NOT NULL,
    audit_metadata TEXT NOT NULL
);
"""


class AuditDB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = asyncio.Lock()
        # `check_same_thread=False` lets us call from any executor thread;
        # the asyncio lock above keeps writes serialized.
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate_audit_columns()
        # Indexes on migrated columns must come after the migration: in
        # _SCHEMA they crash startup on a legacy DB ("no such column").
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_signature_valid "
            "ON audit_entries(signature_valid)"
        )
        logger.info("audit DB ready at {}", path)

    def _migrate_audit_columns(self) -> None:
        """Add columns introduced after v1 (phase, signature_*) to legacy DBs.

        The ``IF NOT EXISTS`` guard on the initial CREATE TABLE means an
        existing DB from an older version keeps its old shape. ALTER TABLE
        ADD COLUMN with a default is safe and idempotent as long as we
        swallow the ``duplicate column name`` failure on second run.
        """
        for stmt in (
            "ALTER TABLE audit_entries ADD COLUMN phase INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE audit_entries ADD COLUMN signature_hex TEXT",
            "ALTER TABLE audit_entries ADD COLUMN signature_valid INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise

    @property
    def path(self) -> Path:
        return self._path

    async def close(self) -> None:
        async with self._lock:
            self._conn.close()

    # --- writers (called by the bus tailer) ---------------------------------

    async def insert_audit(
        self, e: dict[str, Any], *, signature_valid: bool = False,
    ) -> int:
        """Append one audit row; an exact replay of a stored entry is a no-op.

        The persister backfills from the bus on every restart, so the same
        AuditEntry can arrive twice. Only a byte-for-byte replay is skipped
        (signature included) — a tampered copy still lands, flagged invalid.
        Returns the row id, existing or new.
        """
        params_json = json.dumps(e.get("parameters") or {})
        phase = int(e.get("phase") or 1)
        async with self._lock:
            existing = self._conn.execute(
                """
                SELECT id FROM audit_entries
                WHERE trigger_id IS ? AND action_id = ? AND timestamp = ?
                  AND signature_hex IS ? AND parameters_json = ? AND effect = ?
                  AND phase = ?
                """,
                (e.get("trigger_id"), e["action_id"], e["timestamp"],
                 e.get("signature"), params_json, e["effect"], phase),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])
            cur = self._conn.execute(
                """
                INSERT INTO audit_entries (
                    timestamp, trigger_id, action_id, severity, effect,
                    agent_confidence, layer_d_trace, parameters_json, latency_ms,
                    phase, signature_hex, signature_valid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    e["timestamp"], e.get("trigger_id"), e["action_id"], e["severity"],
                    e["effect"], e["agent_confidence"], e["layer_d_trace"],
                    params_json, e.get("latency_ms"),
                    phase,
                    e.get("signature"),
                    1 if signature_valid else 0,
                ),
            )
            return int(cur.lastrowid)

    async def upsert_anomaly(self, a: dict[str, Any]) -> None:
        async with self._lock:
            self._conn.execute(
                """
                INSERT INTO anomalies (
                    trigger_id, timestamp, composite_score, trigger_reason, contributing_signals
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(trigger_id) DO UPDATE SET
                    timestamp=excluded.timestamp,
                    composite_score=excluded.composite_score,
                    trigger_reason=excluded.trigger_reason,
                    contributing_signals=excluded.contributing_signals
                """,
                (
                    a["trigger_id"], a["timestamp"], a["composite_score"],
                    a["trigger_reason"], json.dumps(a.get("contributing_signals") or []),
                ),
            )

    async def upsert_scene(self, s: dict[str, Any]) -> None:
        async with self._lock:
            self._conn.execute(
                """
                INSERT INTO scenes (
                    trigger_id, timestamp, location, hazards, people_present,
                    equipment_state, contextual_factors
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trigger_id) DO UPDATE SET
                    timestamp=excluded.timestamp,
                    location=excluded.location,
                    hazards=excluded.hazards,
                    people_present=excluded.people_present,
                    equipment_state=excluded.equipment_state,
                    contextual_factors=excluded.contextual_factors
                """,
                (
                    s["trigger_id"], s["timestamp"], s["location"],
                    json.dumps(s.get("hazards") or []),
                    json.dumps(s.get("people_present") or []),
                    json.dumps(s.get("equipment_state") or []),
                    json.dumps(s.get("contextual_factors") or {}),
                ),
            )

    async def upsert_plan(self, p: dict[str, Any]) -> None:
        async with self._lock:
            self._conn.execute(
                """
                INSERT INTO plans (
                    trigger_id, timestamp, severity, confidence,
                    rationale, actions, audit_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trigger_id) DO UPDATE SET
                    timestamp=excluded.timestamp,
                    severity=excluded.severity,
                    confidence=excluded.confidence,
                    rationale=excluded.rationale,
                    actions=excluded.actions,
                    audit_metadata=excluded.audit_metadata
                """,
                (
                    p["trigger_id"], p["timestamp"], p["severity"], p["confidence"],
                    p["rationale"],
                    json.dumps(p.get("actions") or []),
                    json.dumps(p.get("audit_metadata") or {}),
                ),
            )

    # --- readers (used by routes) -------------------------------------------

    async def list_audits(
        self,
        *,
        severity: int | None = None,
        action_id: str | None = None,
        trigger_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if severity is not None:
            clauses.append("severity = ?")
            params.append(severity)
        if action_id is not None:
            clauses.append("action_id = ?")
            params.append(action_id)
        if trigger_id is not None:
            clauses.append("trigger_id = ?")
            params.append(trigger_id)
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(start.isoformat())
        if end is not None:
            clauses.append("timestamp <= ?")
            params.append(end.isoformat())
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        async with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM audit_entries {where}", params
            ).fetchone()["n"]
            rows = self._conn.execute(
                f"""
                SELECT id, timestamp, trigger_id, action_id, severity, effect,
                       agent_confidence, layer_d_trace, parameters_json, latency_ms,
                       phase, signature_hex, signature_valid
                FROM audit_entries {where}
                ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        return [_audit_row(r) for r in rows], int(total)

    async def get_audit(self, audit_id: int) -> dict | None:
        async with self._lock:
            row = self._conn.execute(
                """
                SELECT id, timestamp, trigger_id, action_id, severity, effect,
                       agent_confidence, layer_d_trace, parameters_json, latency_ms,
                       phase, signature_hex, signature_valid
                FROM audit_entries WHERE id = ?
                """,
                (audit_id,),
            ).fetchone()
        return _audit_row(row) if row else None

    async def get_incident(self, trigger_id: str) -> dict | None:
        async with self._lock:
            anomaly = self._conn.execute(
                "SELECT * FROM anomalies WHERE trigger_id = ?", (trigger_id,)
            ).fetchone()
            scene = self._conn.execute(
                "SELECT * FROM scenes WHERE trigger_id = ?", (trigger_id,)
            ).fetchone()
            plan = self._conn.execute(
                "SELECT * FROM plans WHERE trigger_id = ?", (trigger_id,)
            ).fetchone()
            audits = self._conn.execute(
                """
                SELECT id, timestamp, trigger_id, action_id, severity, effect,
                       agent_confidence, layer_d_trace, parameters_json, latency_ms,
                       phase, signature_hex, signature_valid
                FROM audit_entries WHERE trigger_id = ? ORDER BY id ASC
                """,
                (trigger_id,),
            ).fetchall()
        if anomaly is None and not audits:
            return None
        return {
            "trigger_id": trigger_id,
            "anomaly": _anomaly_row(anomaly) if anomaly else None,
            "scene": _scene_row(scene) if scene else None,
            "plan": _plan_row(plan) if plan else None,
            "audits": [_audit_row(r) for r in audits],
        }

    async def recent_audits(self, limit: int = 20) -> list[dict]:
        rows, _ = await self.list_audits(limit=limit)
        return rows

    async def recent_incidents(self, limit: int = 20) -> list[dict]:
        async with self._lock:
            rows = self._conn.execute(
                "SELECT trigger_id, timestamp, composite_score, trigger_reason "
                "FROM anomalies ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    async def counts(self) -> dict[str, int]:
        async with self._lock:
            return {
                "audit_entries": self._conn.execute(
                    "SELECT COUNT(*) AS n FROM audit_entries"
                ).fetchone()["n"],
                "anomalies": self._conn.execute(
                    "SELECT COUNT(*) AS n FROM anomalies"
                ).fetchone()["n"],
                "scenes": self._conn.execute(
                    "SELECT COUNT(*) AS n FROM scenes"
                ).fetchone()["n"],
                "plans": self._conn.execute(
                    "SELECT COUNT(*) AS n FROM plans"
                ).fetchone()["n"],
            }


def _audit_row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    return {
        "id": r["id"],
        "timestamp": r["timestamp"],
        "trigger_id": r["trigger_id"],
        "action_id": r["action_id"],
        "severity": r["severity"],
        "effect": r["effect"],
        "agent_confidence": r["agent_confidence"],
        "layer_d_trace": r["layer_d_trace"],
        "parameters": json.loads(r["parameters_json"] or "{}"),
        "latency_ms": r["latency_ms"],
        "phase": _row_get(r, "phase", 1),
        "signature_hex": _row_get(r, "signature_hex", None),
        "signature_valid": bool(_row_get(r, "signature_valid", 0)),
    }


def _row_get(r: sqlite3.Row, key: str, default: Any) -> Any:
    """Row.__getitem__ raises IndexError when the column is missing (legacy DB)."""
    try:
        return r[key]
    except (IndexError, KeyError):
        return default


def _anomaly_row(r: sqlite3.Row) -> dict:
    return {
        "trigger_id": r["trigger_id"],
        "timestamp": r["timestamp"],
        "composite_score": r["composite_score"],
        "trigger_reason": r["trigger_reason"],
        "contributing_signals": json.loads(r["contributing_signals"]),
    }


def _scene_row(r: sqlite3.Row) -> dict:
    return {
        "trigger_id": r["trigger_id"],
        "timestamp": r["timestamp"],
        "location": r["location"],
        "hazards": json.loads(r["hazards"]),
        "people_present": json.loads(r["people_present"]),
        "equipment_state": json.loads(r["equipment_state"]),
        "contextual_factors": json.loads(r["contextual_factors"]),
    }


def _plan_row(r: sqlite3.Row) -> dict:
    return {
        "trigger_id": r["trigger_id"],
        "timestamp": r["timestamp"],
        "severity": r["severity"],
        "confidence": r["confidence"],
        "rationale": r["rationale"],
        "actions": json.loads(r["actions"]),
        "audit_metadata": json.loads(r["audit_metadata"]),
    }
