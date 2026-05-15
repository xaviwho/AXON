"""Layer B fusion engine.

Wires:
  - Redis stream consumption (detections / poses / sensors)
  - Sliding-window state maintenance
  - Per-tick rule evaluation
  - AnomalyScore emission + trigger-context caching (per Prompt 4 done-when)
  - Prometheus + OTel instrumentation

Re-evaluates after every ingested message and at least every `eval_tick_ms`
(via the bus consumer's idle heartbeat) so time-based rules like
"person prone for >5s" can fire even when no new messages arrive.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from loguru import logger
from pydantic import ValidationError

from shared.bus import (
    Bus,
    DETECTION_STREAM,
    POSE_STREAM,
    SENSOR_STREAM,
)
from shared.schemas.anomaly import AnomalyScore, ContributingSignal
from shared.schemas.sensors import SensorReading
from shared.schemas.vision import PoseObservation, VisionDetection

from .rules import FusionConfig, RuleHit, evaluate
from .telemetry import FusionTelemetry
from .window import FusionState, utc_now


@dataclass(frozen=True)
class EmissionResult:
    trigger_id: str
    score: float
    trigger_reason: str
    contributing_signals: list[ContributingSignal]


class FusionEngine:
    def __init__(
        self,
        bus: Bus,
        config: FusionConfig,
        telemetry: FusionTelemetry,
        *,
        camera_ids: list[str],
        eval_tick_ms: int = 100,
    ) -> None:
        self.bus = bus
        self.config = config
        self.telemetry = telemetry
        self.state = FusionState(window_seconds=config.window_seconds)
        self._camera_ids = camera_ids
        self._eval_tick_ms = eval_tick_ms
        self._last_emission_at: datetime | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.active = False
        # Public for /health
        self.last_score: float = 0.0
        self.last_emission: EmissionResult | None = None

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="fusion-engine")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=3.0)
            except asyncio.TimeoutError:
                self._task.cancel()

    async def _run(self) -> None:
        self.active = True
        logger.info(
            "fusion engine running: threshold={} cooldown={}s window={}s rules={}",
            self.config.trigger_threshold,
            self.config.emission_cooldown_seconds,
            self.config.window_seconds,
            [r.id for r in self.config.rules],
        )
        consumer = self.bus.consume_streams(
            [DETECTION_STREAM, POSE_STREAM, SENSOR_STREAM],
            block_ms=self._eval_tick_ms,
            count=100,
        )
        try:
            async for stream, _entry_id, fields in consumer:
                if self._stop.is_set():
                    break
                if stream and fields:
                    self._ingest(stream, fields)
                now = utc_now()
                self.state.prune(now)
                await self._evaluate(now)
        finally:
            self.active = False

    def _ingest(self, stream: str, fields: dict[bytes, bytes]) -> None:
        raw = fields.get(b"data")
        if raw is None:
            return
        try:
            if stream == DETECTION_STREAM:
                self.state.ingest_detection(VisionDetection.model_validate_json(raw))
            elif stream == POSE_STREAM:
                self.state.ingest_pose(PoseObservation.model_validate_json(raw))
            elif stream == SENSOR_STREAM:
                self.state.ingest_sensor(SensorReading.model_validate_json(raw))
        except ValidationError as exc:
            logger.warning("fusion: malformed message on {}: {}", stream, exc)

    async def _evaluate(self, now: datetime) -> None:
        hits = evaluate(self.config, self.state, now)
        score = min(1.0, sum(h.signal.weight for h in hits))
        above = score > self.config.trigger_threshold
        self.last_score = score
        for h in hits:
            self.telemetry.rule_contributions_total.labels(rule_id=h.rule_id).inc()
        self.telemetry.record_evaluation(score, above)

        if not above:
            return
        if self._last_emission_at is not None:
            elapsed = (now - self._last_emission_at).total_seconds()
            if elapsed < self.config.emission_cooldown_seconds:
                return
        await self._emit(now, hits, score)

    async def _emit(self, now: datetime, hits: list[RuleHit], score: float) -> None:
        trigger_id = str(uuid.uuid4())
        signals = [h.signal for h in hits]
        trigger_reason = "|".join(h.rule_id for h in hits)

        msg = AnomalyScore(
            composite_score=score,
            contributing_signals=signals,
            threshold_exceeded=True,
            trigger_reason=trigger_reason,
            trigger_id=trigger_id,
            timestamp=now,
        )
        await self.bus.publish_anomaly(msg.model_dump(mode="json"))

        frame_refs: dict[str, list[str]] = {}
        for cam_id in self._camera_ids:
            frame_refs[cam_id] = await self.bus.latest_frame_entry_ids(cam_id, count=4)

        sensor_refs = {
            sid: json.loads(r.model_dump_json())
            for sid, r in self.state.sensor_latest.items()
        }

        await self.bus.cache_trigger_context(
            trigger_id=trigger_id,
            score=score,
            trigger_reason=trigger_reason,
            timestamp_iso=now.isoformat(),
            contributing_signals=[json.loads(s.model_dump_json()) for s in signals],
            frame_refs=frame_refs,
            sensor_refs=sensor_refs,
        )

        self._last_emission_at = now
        self.telemetry.activations_total.inc()
        self.last_emission = EmissionResult(
            trigger_id=trigger_id,
            score=score,
            trigger_reason=trigger_reason,
            contributing_signals=signals,
        )
        logger.info(
            "fusion ACTIVATED trigger_id={} score={:.2f} rules={}",
            trigger_id, score, [h.rule_id for h in hits],
        )
