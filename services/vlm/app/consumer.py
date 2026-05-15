"""Anomaly → SceneDescription consumer for Layer C.

Subscribes to `axon:anomalies`. For each AnomalyScore message:
  1. Pull the trigger context hash from Redis (frame_refs + sensor_refs).
  2. Fetch the cached keyframes (JPEG bytes).
  3. Hand off to a VLMClient (stub or real vLLM) under a concurrency cap.
  4. Publish the resulting SceneDescription to `axon:scenes`.

The cap (`max_concurrent_triggers`, default 5) is the "5 concurrent
triggers without queue buildup" contract from Prompt 5. Each generation
runs in its own asyncio task; arrival of a sixth trigger waits on the
semaphore rather than queuing inside the consumer loop.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from loguru import logger
from pydantic import ValidationError

from shared.bus import ANOMALY_STREAM, Bus
from shared.schemas.anomaly import AnomalyScore

from .client import GenerationRequest, VLMClient
from .scene_parser import fallback_scene
from .telemetry import VLMTelemetry


class SceneConsumer:
    def __init__(
        self,
        *,
        bus: Bus,
        client: VLMClient,
        telemetry: VLMTelemetry,
        max_concurrent: int = 5,
        keyframes_per_trigger: int = 3,
    ) -> None:
        self._bus = bus
        self._client = client
        self._telemetry = telemetry
        self._sem = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._keyframes = keyframes_per_trigger
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.active = False
        self._inflight: set[asyncio.Task] = set()
        self.processed_total = 0
        self.last_trigger_id: str | None = None

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="vlm-consumer")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=3.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        if self._inflight:
            await asyncio.gather(*self._inflight, return_exceptions=True)

    async def _run(self) -> None:
        self.active = True
        logger.info(
            "vlm consumer running: mode={} max_concurrent={} keyframes={}",
            self._client.mode, self._max_concurrent, self._keyframes,
        )
        try:
            async for stream, _id, fields in self._bus.consume_streams(
                [ANOMALY_STREAM], block_ms=200
            ):
                if self._stop.is_set():
                    break
                if not stream or not fields:
                    continue
                anomaly = self._parse_anomaly(fields)
                if anomaly is None:
                    continue
                task = asyncio.create_task(
                    self._handle_anomaly(anomaly),
                    name=f"vlm:trigger:{anomaly.trigger_id}",
                )
                self._inflight.add(task)
                task.add_done_callback(self._inflight.discard)
        finally:
            self.active = False

    def _parse_anomaly(self, fields: dict[bytes, bytes]) -> AnomalyScore | None:
        raw = fields.get(b"data")
        if raw is None:
            return None
        try:
            return AnomalyScore.model_validate_json(raw)
        except ValidationError as exc:
            logger.warning("vlm: malformed AnomalyScore: {}", exc)
            return None

    async def _handle_anomaly(self, anomaly: AnomalyScore) -> None:
        async with self._sem:
            self._telemetry.in_flight.inc()
            start = time.monotonic()
            outcome = "ok"
            try:
                ctx = await self._bus.fetch_trigger_context(anomaly.trigger_id) or {}
                frame_refs = ctx.get("frame_refs", {}) or {}
                sensor_refs = ctx.get("sensor_refs", {}) or {}

                frames = await self._bus.fetch_frames_by_refs(
                    frame_refs, max_per_camera=self._keyframes
                )
                req = GenerationRequest(
                    trigger_id=anomaly.trigger_id,
                    trigger_reason=anomaly.trigger_reason,
                    sensor_refs=sensor_refs,
                    frames=frames,
                    location_hint=self._infer_location(sensor_refs),
                )

                try:
                    scene = await self._client.generate_scene(req)
                except Exception as exc:    # noqa: BLE001 — degrade on any client failure
                    logger.exception("vlm client error on {}: {}", anomaly.trigger_id, exc)
                    scene = fallback_scene(
                        trigger_id=anomaly.trigger_id,
                        trigger_reason=anomaly.trigger_reason,
                        location=req.location_hint,
                        note=f"client exception: {type(exc).__name__}",
                    )
                    outcome = "client_error"

                await self._bus.publish_scene(scene.model_dump(mode="json"))
                if scene.contextual_factors.get("fallback"):
                    outcome = "fallback"
                self.processed_total += 1
                self.last_trigger_id = anomaly.trigger_id
                logger.info(
                    "vlm scene published trigger={} outcome={} hazards={} people={}",
                    anomaly.trigger_id, outcome, len(scene.hazards), len(scene.people_present),
                )
            finally:
                elapsed = time.monotonic() - start
                self._telemetry.in_flight.dec()
                self._telemetry.generation_latency.labels(
                    mode=self._client.mode, outcome=outcome
                ).observe(elapsed)
                self._telemetry.scenes_total.labels(
                    mode=self._client.mode, outcome=outcome
                ).inc()

    @staticmethod
    def _infer_location(sensor_refs: dict[str, Any]) -> str:
        for sid in sensor_refs:
            # sensor IDs are typically "{type}-{n}"; we don't have a location
            # field on SensorReading yet. Default for the MVP demo lab.
            del sid
            return "lab-A"
        return "unknown"


__all__ = ["SceneConsumer"]
