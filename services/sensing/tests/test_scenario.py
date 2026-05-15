"""Scenario YAML parser tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from services.sensing.app.scenario import (
    CameraSourceKind,
    Scenario,
    load_scenario,
)
from shared.schemas.enums import SensorType

REPO_ROOT = Path(__file__).resolve().parents[3]
MOCK_IDLE = REPO_ROOT / "demos" / "mock_data" / "scenarios" / "mock_idle.yaml"


def test_mock_idle_scenario_parses():
    s = load_scenario(MOCK_IDLE)
    assert s.name == "mock_idle"
    assert s.duration_seconds == 60
    assert len(s.cameras) == 1
    assert s.cameras[0].kind is CameraSourceKind.SYNTHETIC
    assert s.cameras[0].fps == 15
    assert {sensor.type for sensor in s.sensors} == {SensorType.GAS, SensorType.THERMAL}


def test_scenario_rejects_extra_fields():
    with pytest.raises(ValidationError):
        Scenario(
            name="x",
            duration_seconds=1,
            cameras=[],
            sensors=[],
            mystery_field=True,
        )


def test_camera_rtsp_needs_url():
    # synthetic doesn't need url; rtsp/file do, but pydantic alone won't
    # catch that — the camera ingestor raises at open time. Verify the parser
    # at least accepts the shape that the ingestor will refuse.
    s = Scenario(
        name="bad",
        cameras=[{"id": "c", "kind": "rtsp"}],
    )
    assert s.cameras[0].url is None
