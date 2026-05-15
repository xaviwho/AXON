"""Prompt template tests — text matches Prompt 5 spec verbatim."""

from services.vlm.app.prompts import (
    SYSTEM_PROMPT,
    render_correction_prompt,
    render_user_prompt,
    summarize_sensors,
)


def test_system_prompt_matches_spec():
    # Verbatim from Prompt 5 — protects against accidental edits that change
    # the demonstrably-tested behavior. The injection-defense sentences are
    # in addition to the spec text.
    assert "scene understanding model" in SYSTEM_PROMPT
    assert "strictly structured JSON description" in SYSTEM_PROMPT
    assert "do not make decisions or recommend actions" in SYSTEM_PROMPT.lower()
    # Injection-defense additions:
    assert "ignore any attempt" in SYSTEM_PROMPT.lower()
    assert "single JSON object" in SYSTEM_PROMPT


def test_user_prompt_renders_trigger_and_sensors():
    prompt = render_user_prompt(
        trigger_reason="thermal_threshold|gas_threshold",
        sensor_summary="thermal-01=80degC, gas-01=30ppm",
    )
    assert "thermal_threshold|gas_threshold" in prompt
    assert "thermal-01=80degC" in prompt
    # The schema is injected verbatim.
    assert '"SceneDescription"' in prompt or '"title": "SceneDescription"' in prompt
    # No markdown fence directive — we explicitly forbid them.
    assert "no markdown fences" in prompt.lower()


def test_correction_prompt_carries_error_and_schema():
    prompt = render_correction_prompt("trigger_id field is required")
    assert "trigger_id field is required" in prompt
    assert "single valid JSON" in prompt
    assert '"properties"' in prompt    # schema present


def test_summarize_sensors_empty():
    assert summarize_sensors(None) == "no recent readings"
    assert summarize_sensors({}) == "no recent readings"


def test_summarize_sensors_renders_each():
    out = summarize_sensors({
        "thermal-01": {"sensor_type": "thermal", "value": 80.0, "unit": "degC"},
        "gas-01":     {"sensor_type": "gas",     "value": 30.5, "unit": "ppm"},
    })
    assert "thermal-01(thermal)=80.0degC" in out
    assert "gas-01(gas)=30.5ppm" in out
