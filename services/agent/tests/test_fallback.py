"""Fallback safety-protocol tests + confidence-floor behavior."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from services.agent.app.client import PlanRequest, VLLMOpenAIClient
from services.agent.app.fallback import build_fallback_plan
from shared.action_library import ActionLibrary
from shared.schemas.actions import ActionPlan
from shared.schemas.scene import HazardObservation, SceneDescription

NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


def _scene(reason: str = "thermal_threshold") -> SceneDescription:
    return SceneDescription(
        people_present=[], hazards=[], equipment_state=[],
        location="lab-A", contextual_factors={"trigger_reason": reason},
        trigger_id="t-fb", timestamp=NOW,
    )


@pytest.fixture(scope="module")
def lib() -> ActionLibrary:
    return ActionLibrary.load()


def test_fallback_plan_is_dispatchable(lib):
    plan = build_fallback_plan(
        scene=_scene(), trigger_reason="thermal_threshold", library=lib,
    )
    assert isinstance(plan, ActionPlan)
    assert plan.audit_metadata["fallback"] is True
    assert plan.confidence == 1.0
    for inv in plan.actions:
        lib.validate(inv)


def test_fallback_dedupes_compound_triggers(lib):
    """Same (action_id, zone_id) must not appear twice when rules overlap."""
    plan = build_fallback_plan(
        scene=_scene(),
        trigger_reason="thermal_threshold|fire_smoke_vision",
        library=lib,
    )
    keys = [(a.action_id, a.parameters.get("zone_id")) for a in plan.actions]
    assert len(keys) == len(set(keys))


def test_fallback_handles_unknown_trigger(lib):
    plan = build_fallback_plan(
        scene=_scene(), trigger_reason="reactor_malfunction", library=lib,
    )
    # Must produce a parseable plan with informational-only actions.
    assert plan.severity <= 1
    action_ids = {a.action_id for a in plan.actions}
    assert "display_alert" in action_ids
    assert "power_cutoff" not in action_ids


@pytest.mark.asyncio
async def test_vllm_client_low_confidence_falls_back(lib, monkeypatch):
    """Confidence < floor → rule-based protocol replaces the model plan."""
    client = VLLMOpenAIClient(
        lib, base_url="http://x/v1", model="m", api_key="k",
        timeout_seconds=1.0, temperature=0.0, max_parse_retries=0,
        confidence_floor=0.5,
    )
    # Forge a low-confidence model response that PASSES schema + library.
    low_conf_json = (
        '{"severity": 1, "actions": ['
        '{"action_id": "display_alert", '
        '"parameters": {"severity": 1, "message": "x"}, '
        '"requested_latency_ms": 200}], '
        '"rationale": "uncertain", "confidence": 0.3, '
        '"trigger_id": "t-fb", "timestamp": "2026-05-15T12:00:00Z"}'
    )

    async def fake_chat(_http, _messages):
        return low_conf_json

    monkeypatch.setattr(client, "_chat", fake_chat)
    plan = await client.generate_plan(
        PlanRequest(scene=_scene("thermal_threshold"),
                    trigger_reason="thermal_threshold",
                    rag_context="")
    )
    # The agent must NOT publish the low-confidence model plan; fallback wins.
    assert plan.audit_metadata.get("fallback") is True
    assert plan.confidence == 1.0


@pytest.mark.asyncio
async def test_vllm_client_invalid_action_retries_then_falls_back(lib, monkeypatch):
    """Hallucinated action triggers correction prompt, then fallback if still invalid."""
    client = VLLMOpenAIClient(
        lib, base_url="http://x/v1", model="m", api_key="k",
        timeout_seconds=1.0, temperature=0.0, max_parse_retries=1,
        confidence_floor=0.5,
    )

    calls = []
    bad_json = (
        '{"severity": 4, "actions": ['
        '{"action_id": "self_destruct", '
        '"parameters": {}, "requested_latency_ms": 50}], '
        '"rationale": "I do what I want", "confidence": 0.99, '
        '"trigger_id": "t-fb", "timestamp": "2026-05-15T12:00:00Z"}'
    )

    async def fake_chat(_http, messages):
        calls.append(messages)
        return bad_json    # consistently bad — exhausts retry → fallback

    monkeypatch.setattr(client, "_chat", fake_chat)
    plan = await client.generate_plan(
        PlanRequest(scene=_scene(), trigger_reason="thermal_threshold", rag_context="")
    )
    assert len(calls) == 2, f"expected 1 retry; got {len(calls)} total calls"
    assert plan.audit_metadata.get("fallback") is True
    # The hallucinated action never reached the published plan.
    assert all(a.action_id != "self_destruct" for a in plan.actions)


@pytest.mark.asyncio
async def test_vllm_client_returns_high_confidence_valid_plan(lib, monkeypatch):
    """Happy path: valid plan + confidence ≥ floor → plan published as-is."""
    client = VLLMOpenAIClient(
        lib, base_url="http://x/v1", model="m", api_key="k",
        timeout_seconds=1.0, temperature=0.0, max_parse_retries=0,
        confidence_floor=0.5,
    )
    good_json = (
        '{"severity": 4, "actions": ['
        '{"action_id": "power_cutoff", '
        '"parameters": {"zone_id": "lab-A"}, "requested_latency_ms": 80}], '
        '"rationale": "Cut power for safety.", "confidence": 0.9, '
        '"trigger_id": "t-fb", "timestamp": "2026-05-15T12:00:00Z"}'
    )

    async def fake_chat(_http, _messages):
        return good_json

    monkeypatch.setattr(client, "_chat", fake_chat)
    plan = await client.generate_plan(
        PlanRequest(scene=_scene(), trigger_reason="thermal_threshold", rag_context="")
    )
    assert plan.audit_metadata.get("fallback") is None
    assert plan.confidence == 0.9
    assert plan.actions[0].action_id == "power_cutoff"
