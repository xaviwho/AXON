"""Regression: trigger context must be cached before the AnomalyScore goes out.

Layer C (and the action service's reflex path) react to the AnomalyScore
immediately. If the context hash isn't there yet, the VLM builds its scene
with no frames, no sensor readings and location "unknown".
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.fusion.app.fusion import FusionEngine
from services.fusion.app.rules import load_config
from services.fusion.app.telemetry import FusionTelemetry
from shared.schemas.enums import SensorType
from shared.schemas.sensors import SensorReading

RULES_YAML = Path(__file__).resolve().parents[1] / "rules.yaml"
NOW = datetime(2026, 11, 5, 13, 0, 0, tzinfo=timezone.utc)


class _OrderBus:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def publish_anomaly(self, payload):
        self.calls.append("publish_anomaly")

    async def latest_frame_entry_ids(self, camera_id, count=4):
        return []

    async def cache_trigger_context(self, **kwargs):
        self.calls.append("cache_trigger_context")


@pytest.mark.asyncio
async def test_context_cached_before_anomaly_published():
    bus = _OrderBus()
    engine = FusionEngine(
        bus, load_config(RULES_YAML), FusionTelemetry(), camera_ids=["cam-01"],  # type: ignore[arg-type]
    )
    engine.state.ingest_sensor(SensorReading(
        sensor_id="thermal-01", sensor_type=SensorType.THERMAL,
        value=85.0, unit="degC", timestamp=NOW,
    ))
    await engine._evaluate(NOW)
    assert bus.calls == ["cache_trigger_context", "publish_anomaly"]
