"""Prompt template tests."""

import json

import pytest

from services.agent.app.prompts import (
    SYSTEM_PROMPT,
    render_correction_prompt,
    render_user_prompt,
)
from shared.action_library import ActionLibrary


@pytest.fixture(scope="module")
def lib() -> ActionLibrary:
    return ActionLibrary.load()


def test_system_prompt_encodes_safety_constraints():
    text = SYSTEM_PROMPT
    assert "AXON's reasoning agent" in text
    assert "bounded action library" in text.lower()
    assert "NEVER invent new actions" in text
    assert "rationale" in text
    assert "confidence" in text
    assert "below 0.5" in text or "< 0.5" in text


def test_user_prompt_includes_required_sections(lib):
    scene_json = {
        "people_present": [], "hazards": [], "equipment_state": [],
        "location": "lab-A",
        "contextual_factors": {}, "trigger_id": "t-1",
        "timestamp": "2026-05-15T12:00:00Z",
    }
    prompt = render_user_prompt(
        scene_json=scene_json,
        trigger_reason="thermal_threshold",
        rag_context="kb section A\nkb section B",
        library=lib,
    )
    assert "Trigger reason: thermal_threshold" in prompt
    assert '"location": "lab-A"' in prompt
    assert "kb section A" in prompt
    # All 8 library actions must appear in the catalog.
    for name in lib.names():
        assert name in prompt, f"action {name} missing from catalog rendering"
    # Three worked examples present.
    assert "Example 1 —" in prompt
    assert "Example 2 —" in prompt
    assert "Example 3 —" in prompt
    # Schema is injected.
    assert '"ActionPlan"' in prompt or '"title": "ActionPlan"' in prompt
    # No-prose directive.
    assert "no prose" in prompt.lower() or "no markdown" in prompt.lower()


def test_correction_prompt_includes_error_and_catalog(lib):
    prompt = render_correction_prompt("unknown action_id 'self_destruct'", lib)
    assert "self_destruct" in prompt
    for name in lib.names():
        assert name in prompt


def test_user_prompt_is_json_serializable(lib):
    """Prompt fragments containing the model_json_schema must not blow up serialization."""
    scene_json = {
        "people_present": [], "hazards": [], "equipment_state": [],
        "location": "lab-A", "contextual_factors": {},
        "trigger_id": "t-1", "timestamp": "2026-05-15T12:00:00Z",
    }
    prompt = render_user_prompt(
        scene_json=scene_json,
        trigger_reason="thermal_threshold",
        rag_context="",
        library=lib,
    )
    # The scene JSON inside the prompt should be parseable as JSON when extracted.
    start = prompt.index("{")
    obj = json.loads(prompt[start : prompt.index("\n\n", start)])
    assert obj["location"] == "lab-A"
