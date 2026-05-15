"""Smoke tests for shared.schemas and shared.action_library.

Covers the Prompt 1 done-when criteria:
  - every Pydantic model validates a representative sample payload
  - boundary fields (confidence, severity, score) reject out-of-range values
  - validating an invalid ActionInvocation against the bounded action library
    raises a clear, actionable error
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from shared.action_library import (
    ActionLibrary,
    ActionParameterError,
    UnknownActionError,
)
from shared.schemas import (
    ActionEffect,
    ActionInvocation,
    ActionPlan,
    AnomalyScore,
    AuditEntry,
    BoundingBox,
    ContributingSignal,
    EquipmentState,
    HazardObservation,
    Keypoint,
    PersonObservation,
    PoseObservation,
    SceneDescription,
    SensorReading,
    SensorType,
    VisionDetection,
)

NOW = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)


# --- VisionDetection / PoseObservation ---------------------------------------


def test_vision_detection_valid():
    d = VisionDetection(
        object_class="person",
        bbox=BoundingBox(x=10.0, y=20.0, width=100.0, height=200.0),
        confidence=0.95,
        timestamp=NOW,
        camera_id="cam-01",
        frame_id="f-12345",
    )
    assert d.object_class == "person"
    assert d.bbox.width == 100.0


def test_vision_detection_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        VisionDetection(
            object_class="fire",
            bbox=BoundingBox(x=0.0, y=0.0, width=10.0, height=10.0),
            confidence=1.5,
            timestamp=NOW,
            camera_id="cam-01",
            frame_id="f-1",
        )


def test_pose_observation_valid():
    p = PoseObservation(
        keypoints=[
            Keypoint(name="nose", x=0.5, y=0.3, visibility=0.9),
            Keypoint(name="left_shoulder", x=0.4, y=0.5, z=0.0, visibility=0.85),
        ],
        confidence=0.8,
        person_id="anon-1",
        timestamp=NOW,
    )
    assert p.person_id == "anon-1"
    assert len(p.keypoints) == 2


# --- SensorReading -----------------------------------------------------------


def test_sensor_reading_valid():
    r = SensorReading(
        sensor_id="gas-01",
        sensor_type=SensorType.GAS,
        value=42.5,
        unit="ppm",
        timestamp=NOW,
    )
    assert r.sensor_type is SensorType.GAS


def test_sensor_reading_rejects_unknown_sensor_type():
    with pytest.raises(ValidationError):
        SensorReading(
            sensor_id="x", sensor_type="laser", value=0.0, unit="m", timestamp=NOW
        )


# --- AnomalyScore ------------------------------------------------------------


def test_anomaly_score_valid():
    a = AnomalyScore(
        composite_score=0.7,
        contributing_signals=[
            ContributingSignal(source="sensor:gas", weight=0.6, description="25 ppm"),
            ContributingSignal(source="pose:prone", weight=0.4),
        ],
        threshold_exceeded=True,
        trigger_reason="gas_leak_with_person_down",
        trigger_id="t-001",
        timestamp=NOW,
    )
    assert a.threshold_exceeded
    assert len(a.contributing_signals) == 2


def test_anomaly_score_rejects_score_above_one():
    with pytest.raises(ValidationError):
        AnomalyScore(
            composite_score=1.5,
            contributing_signals=[],
            threshold_exceeded=True,
            trigger_reason="x",
            trigger_id="t-002",
            timestamp=NOW,
        )


# --- SceneDescription --------------------------------------------------------


def test_scene_description_valid():
    s = SceneDescription(
        people_present=[PersonObservation(person_id="p1", posture="prone")],
        hazards=[HazardObservation(hazard_type="fire", severity="high")],
        equipment_state=[EquipmentState(equipment_id="furnace-B1", state="in_use")],
        location="lab-A",
        contextual_factors={"shift": "night", "occupancy": "single"},
        trigger_id="t-001",
        timestamp=NOW,
    )
    assert len(s.people_present) == 1
    assert s.contextual_factors["shift"] == "night"


# --- ActionInvocation / ActionPlan -------------------------------------------


def _good_invocation() -> ActionInvocation:
    return ActionInvocation(
        action_id="power_cutoff",
        parameters={"zone_id": "lab-A"},
        requested_latency_ms=50,
    )


def test_action_invocation_valid():
    inv = _good_invocation()
    assert inv.action_id == "power_cutoff"
    assert inv.requested_latency_ms == 50


def test_action_invocation_rejects_non_positive_latency():
    with pytest.raises(ValidationError):
        ActionInvocation(action_id="x", parameters={}, requested_latency_ms=0)


def test_action_plan_valid():
    plan = ActionPlan(
        severity=4,
        actions=[_good_invocation()],
        rationale="Fire detected at hot-plate-A1; cut power and contain.",
        notification_targets=["ehs@university.edu"],
        audit_metadata={"layer_d_model": "llama-3.1-8b-instruct"},
        confidence=0.9,
        trigger_id="t-001",
        timestamp=NOW,
    )
    assert plan.severity == 4
    assert plan.actions[0].action_id == "power_cutoff"


def test_action_plan_rejects_severity_above_five():
    with pytest.raises(ValidationError):
        ActionPlan(
            severity=6,
            actions=[],
            rationale="x",
            confidence=0.5,
            trigger_id="t-001",
            timestamp=NOW,
        )


# --- AuditEntry --------------------------------------------------------------


def test_audit_entry_valid():
    e = AuditEntry(
        timestamp=NOW,
        severity=4,
        layer_d_trace="Selected power_cutoff due to fire/smoke detection at zone lab-A.",
        action_id="power_cutoff",
        effect=ActionEffect.SUCCESS,
        agent_confidence=0.9,
        trigger_id="t-001",
        parameters={"zone_id": "lab-A"},
        latency_ms=42.5,
    )
    assert e.effect is ActionEffect.SUCCESS


# --- ActionLibrary validation ------------------------------------------------


@pytest.fixture(scope="module")
def lib() -> ActionLibrary:
    return ActionLibrary.load()


def test_library_contains_all_mvp_actions(lib: ActionLibrary):
    expected = {
        "power_cutoff",
        "door_lock",
        "door_unlock",
        "hvac_isolate",
        "slice_reshape",
        "notify_responders",
        "display_alert",
        "video_stream_to_responder",
    }
    assert expected.issubset(set(lib.names()))


def test_library_accepts_well_formed_invocation(lib: ActionLibrary):
    lib.validate(_good_invocation())  # no exception is the assertion


def test_library_rejects_unknown_action_id_with_clear_message(lib: ActionLibrary):
    inv = ActionInvocation(
        action_id="self_destruct",
        parameters={},
        requested_latency_ms=10,
    )
    with pytest.raises(UnknownActionError) as excinfo:
        lib.validate(inv)
    message = str(excinfo.value)
    assert "self_destruct" in message
    assert "bounded action library" in message
    assert "power_cutoff" in message  # the message lists the known actions


def test_library_rejects_missing_required_parameter(lib: ActionLibrary):
    inv = ActionInvocation(
        action_id="power_cutoff",
        parameters={},  # missing zone_id
        requested_latency_ms=50,
    )
    with pytest.raises(ActionParameterError) as excinfo:
        lib.validate(inv)
    message = str(excinfo.value)
    assert "power_cutoff" in message
    assert "zone_id" in message


def test_library_rejects_wrong_parameter_type(lib: ActionLibrary):
    inv = ActionInvocation(
        action_id="display_alert",
        parameters={"severity": "high", "message": "fire"},  # severity must be int
        requested_latency_ms=200,
    )
    with pytest.raises(ActionParameterError) as excinfo:
        lib.validate(inv)
    assert "severity" in str(excinfo.value)


def test_library_rejects_additional_properties(lib: ActionLibrary):
    inv = ActionInvocation(
        action_id="door_lock",
        parameters={"zone_id": "lab-A", "secret_param": True},
        requested_latency_ms=50,
    )
    with pytest.raises(ActionParameterError):
        lib.validate(inv)


def test_library_validates_nested_slice_reshape(lib: ActionLibrary):
    inv = ActionInvocation(
        action_id="slice_reshape",
        parameters={
            "slices": [
                {"slice_id": "URLLC", "priority": 9},
                {"slice_id": "eMBB", "priority": 3},
            ],
            "duration_seconds": 60,
        },
        requested_latency_ms=30,
    )
    lib.validate(inv)


def test_library_rejects_bad_slice_id(lib: ActionLibrary):
    inv = ActionInvocation(
        action_id="slice_reshape",
        parameters={"slices": [{"slice_id": "FastLane", "priority": 9}]},
        requested_latency_ms=30,
    )
    with pytest.raises(ActionParameterError):
        lib.validate(inv)
