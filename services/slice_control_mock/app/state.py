"""HFR-shaped slice state held in memory; broadcast on change.

This stand-in lets Layer 4 exercise the slice-reshape control plane today.
When HFR's real API arrives we replace this module with an HTTP client
behind the same shape; the dispatcher's handler doesn't change.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

SliceId = Literal["eMBB", "URLLC", "mMTC"]


class SliceParams(BaseModel):
    model_config = ConfigDict(frozen=True)
    priority: int = Field(ge=1, le=10)
    active: bool = True


class SliceState(BaseModel):
    eMBB: SliceParams = SliceParams(priority=5)
    URLLC: SliceParams = SliceParams(priority=5)
    mMTC: SliceParams = SliceParams(priority=5)
    preempt_active: bool = False
    preempt_until: datetime | None = None
    preempt_reason: str | None = None
    last_change: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    revision: int = 0


class SliceStore:
    """In-memory slice state with async pub/sub for WebSocket broadcast."""

    def __init__(self) -> None:
        self._state = SliceState()
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> SliceState:
        return self._state

    def snapshot(self) -> dict:
        return self._state.model_dump(mode="json")

    async def set_priority(self, slice_id: SliceId, priority: int) -> SliceState:
        async with self._lock:
            updated = self._state.model_copy(
                update={
                    slice_id: SliceParams(priority=priority),
                    "last_change": datetime.now(timezone.utc),
                    "revision": self._state.revision + 1,
                }
            )
            self._state = updated
        logger.info("slice {} priority -> {}", slice_id, priority)
        await self._broadcast("priority_change", {"slice_id": slice_id, "priority": priority})
        return updated

    async def preempt(self, duration_seconds: int, reason: str) -> SliceState:
        async with self._lock:
            now = datetime.now(timezone.utc)
            updated = self._state.model_copy(
                update={
                    "preempt_active": True,
                    "preempt_until": now + timedelta(seconds=duration_seconds),
                    "preempt_reason": reason,
                    "last_change": now,
                    "revision": self._state.revision + 1,
                }
            )
            self._state = updated
        logger.warning("slice preemption ON for {}s: {}", duration_seconds, reason)
        await self._broadcast(
            "preempt_active",
            {"duration_seconds": duration_seconds, "reason": reason},
        )
        return updated

    async def clear_preempt(self) -> SliceState:
        async with self._lock:
            updated = self._state.model_copy(
                update={
                    "preempt_active": False,
                    "preempt_until": None,
                    "preempt_reason": None,
                    "last_change": datetime.now(timezone.utc),
                    "revision": self._state.revision + 1,
                }
            )
            self._state = updated
        logger.info("slice preemption cleared")
        await self._broadcast("preempt_cleared", {})
        return updated

    # --- pub/sub for WebSocket clients ---------------------------------------

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def _broadcast(self, event: str, detail: dict) -> None:
        msg = {
            "event": event,
            "detail": detail,
            "state": self.snapshot(),
        }
        payload = json.dumps(msg)
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Slow client — drop them rather than slowing the control plane.
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)
