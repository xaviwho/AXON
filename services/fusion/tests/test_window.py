"""Sliding-window state tests."""

from datetime import datetime, timedelta, timezone

from services.fusion.app.window import FusionState
from shared.schemas.enums import SensorType
from shared.schemas.sensors import SensorReading
from shared.schemas.vision import BoundingBox, PoseObservation, VisionDetection

T0 = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


def _det(t_offset: float, cls: str = "person", cam: str = "cam-01", conf: float = 0.9):
    return VisionDetection(
        object_class=cls,
        bbox=BoundingBox(x=0, y=0, width=10, height=10),
        confidence=conf,
        timestamp=T0 + timedelta(seconds=t_offset),
        camera_id=cam,
        frame_id=f"f-{int(t_offset * 100)}",
    )


def _pose(t_offset: float, posture: str, person_id: str = "anon-0"):
    return PoseObservation(
        keypoints=[],
        confidence=0.8,
        person_id=person_id,
        timestamp=T0 + timedelta(seconds=t_offset),
        posture=posture,
        camera_id="cam-01",
    )


def test_prune_drops_old_detections():
    state = FusionState(window_seconds=5.0)
    state.ingest_detection(_det(0.0))    # 5.5 s before "now" — outside window
    state.ingest_detection(_det(4.0))
    state.prune(T0 + timedelta(seconds=5.5))
    assert len(state.detections) == 1
    assert state.detections[0].timestamp == T0 + timedelta(seconds=4.0)


def test_prone_streak_persists_and_drops_on_posture_change():
    state = FusionState(window_seconds=5.0)
    state.ingest_pose(_pose(0.0, "prone"))
    state.ingest_pose(_pose(1.0, "prone"))
    state.ingest_pose(_pose(2.0, "prone"))
    streak = state.prone_streaks["anon-0"]
    assert streak.started_at == T0
    assert streak.last_seen_at == T0 + timedelta(seconds=2.0)

    # standing should kill the streak
    state.ingest_pose(_pose(3.0, "standing"))
    assert "anon-0" not in state.prone_streaks


def test_prone_streak_dropped_by_prune_after_grace_period():
    # Streak grace = 3× window — survives single-window absences but drops eventually.
    state = FusionState(window_seconds=5.0)
    state.ingest_pose(_pose(0.0, "prone"))
    state.prune(T0 + timedelta(seconds=10.0))    # within 15 s grace
    assert "anon-0" in state.prone_streaks
    state.prune(T0 + timedelta(seconds=20.0))    # past 15 s grace
    assert state.prone_streaks == {}


def test_sensor_latest_kept_per_id():
    state = FusionState()
    state.ingest_sensor(SensorReading(
        sensor_id="thermal-01", sensor_type=SensorType.THERMAL,
        value=22.0, unit="degC", timestamp=T0,
    ))
    state.ingest_sensor(SensorReading(
        sensor_id="thermal-01", sensor_type=SensorType.THERMAL,
        value=80.0, unit="degC", timestamp=T0 + timedelta(seconds=10.0),
    ))
    assert state.sensor_latest["thermal-01"].value == 80.0
