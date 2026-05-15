"""Ten 'reasonable plan' scenarios — Prompt 6 done-when (3) labeled set.

The stub LLM client is the same code path that produces the production
fail-safe fallback, so this also locks in the safety-protocol behavior
the system will execute when the real LLM has low confidence.

Each case asserts:
  - the plan parses + library-binds (i.e. is dispatchable),
  - severity falls in the expected band,
  - the critical actions for that hazard are present,
  - forbidden actions are absent.

These constraints encode CLAUDE.md anti-patterns (e.g. PPE alone never
escalates to power_cutoff) plus the worked examples in prompts.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest

from services.agent.app.client import PlanRequest, StubLLMClient
from shared.action_library import ActionLibrary
from shared.schemas.actions import ActionPlan
from shared.schemas.scene import (
    EquipmentState,
    HazardObservation,
    PersonObservation,
    SceneDescription,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


def _scene(
    *,
    location: str = "lab-A",
    trigger_id: str = "t-test",
    trigger_reason: str = "thermal_threshold",
    hazards: list[HazardObservation] | None = None,
    people: list[PersonObservation] | None = None,
    equipment: list[EquipmentState] | None = None,
) -> SceneDescription:
    return SceneDescription(
        people_present=people or [],
        hazards=hazards or [],
        equipment_state=equipment or [],
        location=location,
        contextual_factors={"trigger_reason": trigger_reason},
        trigger_id=trigger_id,
        timestamp=NOW,
    )


@dataclass(frozen=True)
class Scenario:
    name: str
    build_scene: Callable[[], SceneDescription]
    trigger_reason: str
    severity_min: int
    severity_max: int
    must_include: set[str]
    must_not_include: set[str] = frozenset()


SCENARIOS: list[Scenario] = [
    Scenario(
        name="01 fire / thermal anomaly",
        build_scene=lambda: _scene(
            hazards=[HazardObservation(hazard_type="fire", severity="high", location="lab-A")],
            equipment=[EquipmentState(equipment_id="hot-plate-A1", state="in_use")],
        ),
        trigger_reason="thermal_threshold",
        severity_min=4, severity_max=5,
        must_include={"power_cutoff", "hvac_isolate", "door_lock",
                      "slice_reshape", "notify_responders", "display_alert"},
    ),
    Scenario(
        name="02 gas leak only",
        build_scene=lambda: _scene(
            hazards=[HazardObservation(hazard_type="gas_leak", severity="high")],
        ),
        trigger_reason="gas_threshold",
        severity_min=3, severity_max=4,
        must_include={"hvac_isolate", "door_lock", "notify_responders", "display_alert"},
        # power_cutoff is NOT in the basic gas protocol — could create ignition risk.
        must_not_include={"power_cutoff"},
    ),
    Scenario(
        name="03 person prone (medical)",
        build_scene=lambda: _scene(
            people=[PersonObservation(person_id="p-1", posture="prone", location="lab-A")],
        ),
        trigger_reason="person_prone_persistent",
        severity_min=4, severity_max=5,
        must_include={"door_unlock", "notify_responders", "display_alert"},
        # Never lock a person in during a medical event.
        must_not_include={"door_lock"},
    ),
    Scenario(
        name="04 PPE violation only (informational)",
        build_scene=lambda: _scene(
            equipment=[EquipmentState(equipment_id="hot-plate-A1", state="in_use")],
            people=[PersonObservation(person_id="p-1", posture="standing")],
        ),
        trigger_reason="ppe_with_equipment",
        severity_min=0, severity_max=1,
        must_include={"display_alert", "notify_responders"},
        # Hard CLAUDE.md anti-pattern: PPE alone NEVER escalates to these.
        must_not_include={"power_cutoff", "door_lock", "hvac_isolate"},
    ),
    Scenario(
        name="05 fire + person down (compound severe)",
        build_scene=lambda: _scene(
            hazards=[HazardObservation(hazard_type="fire", severity="high")],
            people=[PersonObservation(person_id="p-1", posture="prone")],
        ),
        trigger_reason="thermal_threshold|person_prone_persistent",
        severity_min=4, severity_max=5,
        must_include={"power_cutoff", "hvac_isolate", "door_unlock",
                      "notify_responders", "display_alert", "slice_reshape"},
        # Medical wins over containment for door: must unlock, never lock.
        must_not_include={"door_lock"},
    ),
    Scenario(
        name="06 fire/smoke (vision-detected)",
        build_scene=lambda: _scene(
            hazards=[HazardObservation(hazard_type="smoke", severity="medium")],
        ),
        trigger_reason="fire_smoke_vision",
        severity_min=4, severity_max=5,
        must_include={"power_cutoff", "hvac_isolate", "door_lock", "notify_responders"},
    ),
    Scenario(
        name="07 gas + person prone (compound)",
        build_scene=lambda: _scene(
            hazards=[HazardObservation(hazard_type="gas_leak", severity="high")],
            people=[PersonObservation(person_id="p-1", posture="prone")],
        ),
        trigger_reason="gas_threshold|person_prone_persistent",
        severity_min=4, severity_max=5,
        must_include={"hvac_isolate", "door_unlock", "notify_responders", "display_alert"},
        must_not_include={"door_lock"},
    ),
    Scenario(
        name="08 equipment in use + PPE violation in same zone",
        build_scene=lambda: _scene(
            equipment=[EquipmentState(equipment_id="hot-plate-A1", state="in_use")],
        ),
        trigger_reason="ppe_with_equipment",
        severity_min=0, severity_max=1,
        must_include={"display_alert", "notify_responders"},
        must_not_include={"power_cutoff", "door_lock", "hvac_isolate", "slice_reshape"},
    ),
    Scenario(
        name="09 empty / quiet trigger",
        build_scene=lambda: _scene(
            trigger_reason="",
        ),
        trigger_reason="",
        severity_min=0, severity_max=2,
        must_include={"display_alert", "notify_responders"},
    ),
    Scenario(
        name="10 unknown trigger reason",
        build_scene=lambda: _scene(
            trigger_reason="reactor_malfunction",
        ),
        trigger_reason="reactor_malfunction",
        severity_min=0, severity_max=2,
        must_include={"display_alert", "notify_responders"},
        # Unknown trigger must NOT cascade safety-critical actions.
        must_not_include={"power_cutoff", "hvac_isolate", "door_lock"},
    ),
]


@pytest.fixture(scope="module")
def lib() -> ActionLibrary:
    return ActionLibrary.load()


@pytest.fixture(scope="module")
def stub(lib) -> StubLLMClient:
    return StubLLMClient(lib)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
@pytest.mark.asyncio
async def test_scenario_produces_reasonable_plan(stub, lib, scenario):
    scene = scenario.build_scene()
    plan = await stub.generate_plan(
        PlanRequest(scene=scene, trigger_reason=scenario.trigger_reason, rag_context="")
    )

    # 1. dispatchable: plan is a valid ActionPlan; every action library-binds.
    assert isinstance(plan, ActionPlan)
    for inv in plan.actions:
        lib.validate(inv)    # no exception

    # 2. severity in expected band
    assert scenario.severity_min <= plan.severity <= scenario.severity_max, (
        f"{scenario.name}: severity {plan.severity} not in "
        f"[{scenario.severity_min}, {scenario.severity_max}]"
    )

    # 3. critical actions present
    action_ids = {inv.action_id for inv in plan.actions}
    missing = scenario.must_include - action_ids
    assert not missing, f"{scenario.name}: missing {missing}; got {sorted(action_ids)}"

    # 4. forbidden actions absent
    forbidden = scenario.must_not_include & action_ids
    assert not forbidden, f"{scenario.name}: must NOT include {forbidden}"

    # 5. audit trace recorded
    assert plan.audit_metadata.get("layer_d_trace"), (
        f"{scenario.name}: audit_metadata.layer_d_trace missing"
    )
    assert plan.rationale.strip(), f"{scenario.name}: empty rationale"
