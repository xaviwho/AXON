"""Rule + engine evaluation tests.

The `LABELED_CASES` table is the seed of the labeled test set the prompt
references — 20 hand-constructed mini-scenarios with expected outcomes.
Each case feeds a sequence of observations into a FusionState, advances
time, and asserts whether the composite score crossed the threshold.
This is the "sensible gating" check; richer real-clip labels follow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from services.fusion.app.rules import FusionConfig, evaluate, load_config
from services.fusion.app.window import FusionState
from shared.schemas.enums import SensorType
from shared.schemas.sensors import SensorReading
from shared.schemas.vision import BoundingBox, PoseObservation, VisionDetection

REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_YAML = REPO_ROOT / "services" / "fusion" / "rules.yaml"
T0 = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def cfg() -> FusionConfig:
    return load_config(RULES_YAML)


def _det(cls: str, t_offset: float, *, conf: float = 0.9, cam: str = "cam-01") -> VisionDetection:
    return VisionDetection(
        object_class=cls,
        bbox=BoundingBox(x=0, y=0, width=10, height=10),
        confidence=conf,
        timestamp=T0 + timedelta(seconds=t_offset),
        camera_id=cam,
        frame_id=f"f-{int(t_offset * 1000)}",
    )


def _pose(posture: str, t_offset: float, person_id: str = "anon-0") -> PoseObservation:
    return PoseObservation(
        keypoints=[], confidence=0.8, person_id=person_id,
        timestamp=T0 + timedelta(seconds=t_offset), posture=posture, camera_id="cam-01",
    )


def _sensor(sensor_type: SensorType, value: float, *, sensor_id: str | None = None, unit: str = "u") -> SensorReading:
    return SensorReading(
        sensor_id=sensor_id or f"{sensor_type.value}-01",
        sensor_type=sensor_type, value=value, unit=unit, timestamp=T0,
    )


@dataclass(frozen=True)
class Case:
    name: str
    setup: Callable[[FusionState], None]
    eval_at_offset: float
    expect_above_threshold: bool
    expect_rule_id: str | None = None


def _none(_: FusionState) -> None: pass


LABELED_CASES: list[Case] = [
    # --- happy / quiet path -------------------------------------------------
    Case("empty state stays quiet", _none, 1.0, False),
    Case("single benign person detection", lambda s: s.ingest_detection(_det("person", 0.0)), 1.0, False),
    Case("single standing pose", lambda s: s.ingest_pose(_pose("standing", 0.0)), 1.0, False),
    Case("calm gas reading 0.2ppm",
         lambda s: s.ingest_sensor(_sensor(SensorType.GAS, 0.2)), 1.0, False),
    Case("calm thermal 22°C",
         lambda s: s.ingest_sensor(_sensor(SensorType.THERMAL, 22.0)), 1.0, False),
    Case("brief prone <5s, no streak yet",
         lambda s: s.ingest_pose(_pose("prone", 0.0)), 1.0, False),
    Case("low-confidence fire detection drops",
         lambda s: s.ingest_detection(_det("fire", 0.0, conf=0.4)),
         1.0, False),

    # --- single-rule activations -------------------------------------------
    Case("fire detection high confidence triggers",
         lambda s: s.ingest_detection(_det("fire", 0.0, conf=0.9)),
         1.0, True, "fire_smoke_vision"),
    Case("smoke high confidence triggers",
         lambda s: s.ingest_detection(_det("smoke", 0.0, conf=0.75)),
         1.0, True, "fire_smoke_vision"),
    Case("gas above 25ppm triggers",
         lambda s: s.ingest_sensor(_sensor(SensorType.GAS, 30.0, unit="ppm")),
         1.0, True, "gas_threshold"),
    Case("thermal 80°C triggers (fire proxy)",
         lambda s: s.ingest_sensor(_sensor(SensorType.THERMAL, 80.0, unit="degC")),
         1.0, True, "thermal_threshold"),
    Case("thermal at threshold edge 60°C triggers",
         lambda s: s.ingest_sensor(_sensor(SensorType.THERMAL, 60.0, unit="degC")),
         1.0, True, "thermal_threshold"),
    Case("thermal just below 60°C does not trigger",
         lambda s: s.ingest_sensor(_sensor(SensorType.THERMAL, 59.5, unit="degC")),
         1.0, False),
    # Person-down weight bumped to 0.5 for Prompt 9: medical emergencies fire
    # the gate on their own without needing a compounding sensor signal.
    Case("prone for 5s alone triggers",
         lambda s: s.ingest_pose(_pose("prone", 0.0)), 5.01, True, "person_prone_persistent"),
    Case("prone 5s + benign person detection triggers",
         lambda s: (
             s.ingest_pose(_pose("prone", 0.0)),
             s.ingest_detection(_det("person", 0.0)),
         ), 5.01, True, "person_prone_persistent"),
    Case("prone for 4s does not trigger (under duration)",
         lambda s: s.ingest_pose(_pose("prone", 0.0)), 4.0, False),

    # --- compounding (cap-at-1 semantics) ----------------------------------
    Case("prone + gas threshold compound is still a trigger",
         lambda s: (
             s.ingest_pose(_pose("prone", 0.0)),
             s.ingest_sensor(_sensor(SensorType.GAS, 26.0, unit="ppm")),
         ),
         5.5, True),
    Case("fire+gas+thermal compound stays ≤1.0 cap",
         lambda s: (
             s.ingest_detection(_det("fire", 0.0, conf=0.9)),
             s.ingest_sensor(_sensor(SensorType.GAS, 40.0, unit="ppm")),
             s.ingest_sensor(_sensor(SensorType.THERMAL, 70.0, unit="degC")),
         ),
         1.0, True),

    # --- vision pair rule --------------------------------------------------
    Case("ppe violation alone does NOT trigger (0.3 < 0.4)",
         lambda s: s.ingest_detection(_det("ppe_violation", 0.0, conf=0.8)),
         1.0, False),
    Case("ppe_violation + equipment_in_use in same cam ⇒ does NOT trigger alone (0.3 weight)",
         lambda s: (
             s.ingest_detection(_det("ppe_violation", 0.0, conf=0.8, cam="cam-01")),
             s.ingest_detection(_det("equipment_in_use", 0.1, conf=0.8, cam="cam-01")),
         ), 1.0, False),
    Case("ppe pair on different cameras does NOT pair",
         lambda s: (
             s.ingest_detection(_det("ppe_violation", 0.0, conf=0.8, cam="cam-01")),
             s.ingest_detection(_det("equipment_in_use", 0.0, conf=0.8, cam="cam-02")),
         ), 1.0, False),
    Case("ppe pair + benign thermal does not trigger",
         lambda s: (
             s.ingest_detection(_det("ppe_violation", 0.0, conf=0.8, cam="cam-01")),
             s.ingest_detection(_det("equipment_in_use", 0.0, conf=0.8, cam="cam-01")),
             s.ingest_sensor(_sensor(SensorType.THERMAL, 25.0, unit="degC")),
         ), 1.0, False),
    Case("ppe pair + gas threshold trigger together",
         lambda s: (
             s.ingest_detection(_det("ppe_violation", 0.0, conf=0.8, cam="cam-01")),
             s.ingest_detection(_det("equipment_in_use", 0.0, conf=0.8, cam="cam-01")),
             s.ingest_sensor(_sensor(SensorType.GAS, 30.0, unit="ppm")),
         ), 1.0, True),
]


@pytest.mark.parametrize("case", LABELED_CASES, ids=[c.name for c in LABELED_CASES])
def test_labeled_case(cfg: FusionConfig, case: Case):
    state = FusionState(window_seconds=cfg.window_seconds)
    case.setup(state)
    now = T0 + timedelta(seconds=case.eval_at_offset)
    state.prune(now)
    hits = evaluate(cfg, state, now)
    score = min(1.0, sum(h.signal.weight for h in hits))
    above = score > cfg.trigger_threshold
    assert above is case.expect_above_threshold, (
        f"{case.name}: score={score:.2f} above={above} hits={[h.rule_id for h in hits]}"
    )
    if case.expect_rule_id is not None:
        assert case.expect_rule_id in {h.rule_id for h in hits}, (
            f"{case.name}: expected rule '{case.expect_rule_id}' in hits "
            f"{[h.rule_id for h in hits]}"
        )


def test_score_capped_at_one(cfg: FusionConfig):
    state = FusionState(window_seconds=cfg.window_seconds)
    state.ingest_detection(_det("fire", 0.0, conf=0.95))          # +0.5
    state.ingest_sensor(_sensor(SensorType.GAS, 30.0, unit="ppm"))  # +0.6
    state.ingest_sensor(_sensor(SensorType.THERMAL, 75.0, unit="degC"))  # +0.6
    hits = evaluate(cfg, state, T0 + timedelta(seconds=1.0))
    score = min(1.0, sum(h.signal.weight for h in hits))
    assert score == 1.0


def test_yaml_round_trip_loads_all_mvp_rules(cfg: FusionConfig):
    ids = {r.id for r in cfg.rules}
    assert ids >= {
        "fire_smoke_vision", "person_prone_persistent", "gas_threshold",
        "thermal_threshold", "ppe_with_equipment",
    }
    assert cfg.trigger_threshold == 0.4
    assert cfg.window_seconds == 5.0
