"""Background tailer that mirrors bus events into the SQLite audit DB.

Subscribes to anomalies / scenes / plans / audit streams. On startup, it
back-fills from `-` (entire stream) so the dashboard isn't blank after a
container restart; thereafter it tracks the latest IDs.

Recent events are also exposed in-memory so the WebSocket fan-out
(`live.py`) and the /status endpoint can pull current state without
hitting SQLite for every read.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any

from loguru import logger

from shared.audit_signing import verify_entry
from shared.bus import (
    ALERT_STREAM,
    ANOMALY_STREAM,
    AUDIT_STREAM,
    Bus,
    PLAN_STREAM,
    SCENE_STREAM,
)

from .db import AuditDB


class EventHub:
    """Pub/sub fan-out for WebSocket clients + in-memory recent-events buffer."""

    def __init__(self, ring_size: int = 200) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._recent: deque[dict] = deque(maxlen=ring_size)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=128)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: str, payload: dict[str, Any]) -> None:
        msg = {"event": event, "payload": payload}
        self._recent.append(msg)
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)

    def snapshot(self, limit: int = 50) -> list[dict]:
        return list(self._recent)[-limit:]


class BusPersister:
    """Tails the bus and writes to SQLite + EventHub."""

    _STREAM_HANDLERS = {
        AUDIT_STREAM: "audit",
        ANOMALY_STREAM: "anomaly",
        SCENE_STREAM: "scene",
        PLAN_STREAM: "plan",
        ALERT_STREAM: "alert",
    }

    def __init__(self, *, bus: Bus, db: AuditDB, hub: EventHub) -> None:
        self._bus = bus
        self._db = db
        self._hub = hub
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        # Backfill runs inside the background task, not before it: on a full
        # bus it is thousands of SQLite writes, and blocking startup on it
        # left the API unreachable for minutes.
        self._task = asyncio.create_task(self._backfill_then_run(), name="console-persister")

    async def _backfill_then_run(self) -> None:
        # Backfill recent history so the dashboard isn't blank after a cold start.
        await self._backfill()
        await self._run()

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=3.0)
            except asyncio.TimeoutError:
                self._task.cancel()

    async def _backfill(self) -> None:
        """Read the existing tail of every stream so SQLite is warm at start."""
        from shared.bus import (
            ANOMALY_STREAM,
            AUDIT_STREAM,
            PLAN_STREAM,
            SCENE_STREAM,
        )

        for stream in (ANOMALY_STREAM, SCENE_STREAM, PLAN_STREAM, AUDIT_STREAM):
            try:
                # Newest 500, replayed oldest-first (xrange from "-" would
                # return the oldest entries instead).
                items = await self._bus._client.xrevrange(stream, count=500)   # noqa: SLF001
            except Exception as exc:    # noqa: BLE001
                logger.warning("backfill {} failed: {}", stream, exc)
                continue
            for _id, fields in reversed(items):
                if self._stop.is_set():
                    return
                await self._handle(stream, fields)
        logger.info("console backfill complete")

    async def _run(self) -> None:
        logger.info("console persister running — tailing audit/anomaly/scene/plan/alert")
        async for stream, _id, fields in self._bus.consume_streams(
            list(self._STREAM_HANDLERS.keys()), block_ms=200
        ):
            if self._stop.is_set():
                break
            if not stream or not fields:
                continue
            await self._handle(stream, fields)

    async def _handle(self, stream: str, fields: dict[bytes, bytes]) -> None:
        raw = fields.get(b"data")
        if raw is None:
            return
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("console: bad payload on {}: {}", stream, exc)
            return

        if stream == AUDIT_STREAM:
            valid = verify_entry(payload)
            if not valid:
                logger.warning(
                    "audit signature check FAILED action={} trigger={} — "
                    "row will be persisted with signature_valid=0",
                    payload.get("action_id"), payload.get("trigger_id"),
                )
            try:
                await self._db.insert_audit(payload, signature_valid=valid)
            except Exception as exc:    # noqa: BLE001
                logger.warning("audit insert failed: {}", exc)
        elif stream == ANOMALY_STREAM:
            await self._db.upsert_anomaly(payload)
        elif stream == SCENE_STREAM:
            await self._db.upsert_scene(payload)
        elif stream == PLAN_STREAM:
            await self._db.upsert_plan(payload)
        # alerts are not persisted, only relayed.

        self._hub.publish(self._STREAM_HANDLERS[stream], payload)


__all__ = ["BusPersister", "EventHub"]
