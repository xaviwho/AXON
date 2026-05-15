"""Consumer concurrency contract: 5 in-flight, 6th waits on the semaphore.

We replace the real VLM client with a slow stub that signals when each
generation enters the critical section, then drive the consumer with
many anomalies and assert in-flight stays bounded.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from services.vlm.app.client import GenerationRequest, VLMClient
from services.vlm.app.consumer import SceneConsumer
from services.vlm.app.telemetry import VLMTelemetry
from shared.bus import ANOMALY_STREAM
from shared.schemas.anomaly import AnomalyScore, ContributingSignal
from shared.schemas.scene import SceneDescription


@dataclass
class _SlowClient(VLMClient):
    """Generation gated by an external event so the test controls duration."""
    mode = "stub"
    inflight: int = 0
    peak_inflight: int = 0
    release: asyncio.Event = None

    async def generate_scene(self, req: GenerationRequest) -> SceneDescription:
        self.inflight += 1
        self.peak_inflight = max(self.peak_inflight, self.inflight)
        try:
            await self.release.wait()
        finally:
            self.inflight -= 1
        return SceneDescription(
            people_present=[], hazards=[], equipment_state=[],
            location="lab-A", contextual_factors={"stub": True},
            trigger_id=req.trigger_id,
            timestamp=datetime.now(timezone.utc),
        )


class _FakeBus:
    """Minimal in-memory bus stand-in.

    Yields one preloaded anomaly batch from consume_streams, then idles.
    """

    def __init__(self, anomalies: list[AnomalyScore]) -> None:
        self._anomalies = anomalies
        self.published: list[dict] = []
        self.healthy = True

    async def consume_streams(self, streams, block_ms=200):
        # First yield: every preloaded anomaly back-to-back.
        for a in self._anomalies:
            yield ANOMALY_STREAM, "0-1", {b"data": a.model_dump_json().encode("utf-8")}
        # Then idle ticks forever so the consumer's main loop stays alive.
        while True:
            await asyncio.sleep(0.05)
            yield "", "", {}

    async def fetch_trigger_context(self, trigger_id):
        return {"frame_refs": {}, "sensor_refs": {}}

    async def fetch_frames_by_refs(self, frame_refs, *, max_per_camera=4):
        return []

    async def publish_scene(self, payload):
        self.published.append(payload)


def _anomaly(i: int) -> AnomalyScore:
    return AnomalyScore(
        composite_score=0.7,
        contributing_signals=[ContributingSignal(source="sensor:thermal:t-1", weight=0.6)],
        threshold_exceeded=True,
        trigger_reason="thermal_threshold",
        trigger_id=f"t-{i}",
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_concurrency_capped_at_max_concurrent():
    """Peak in-flight must equal min(N_triggers, max_concurrent)."""
    anomalies = [_anomaly(i) for i in range(10)]
    bus = _FakeBus(anomalies)
    telemetry = VLMTelemetry()
    release = asyncio.Event()
    client = _SlowClient(release=release)

    consumer = SceneConsumer(
        bus=bus, client=client, telemetry=telemetry,
        max_concurrent=5, keyframes_per_trigger=1,
    )
    await consumer.start()

    # Wait briefly for the consumer to spin up tasks and saturate the semaphore.
    for _ in range(20):
        await asyncio.sleep(0.02)
        if client.peak_inflight >= 5:
            break

    assert client.peak_inflight == 5, f"peak in-flight {client.peak_inflight} != 5"
    assert client.inflight == 5

    # Let every gen finish and the consumer drain.
    release.set()
    for _ in range(50):
        await asyncio.sleep(0.02)
        if len(bus.published) == 10:
            break

    await consumer.stop()
    assert len(bus.published) == 10
