"""Scene-parser correctness + prompt-injection resistance.

These tests are the second line of defense from Prompt 5: no matter what
the model returns, we either produce a valid SceneDescription or fail
clean. The injection cases simulate a successfully-injected model
returning various adversarial outputs.
"""

import pytest

from services.vlm.app.scene_parser import (
    SceneParseError,
    fallback_scene,
    parse_scene,
)
from shared.schemas.scene import SceneDescription


_T = "trigger-abc"


def test_parses_minimal_valid_scene():
    raw = """
    {
        "people_present": [{"person_id": "p1", "posture": "prone"}],
        "hazards": [{"hazard_type": "fire", "severity": "high"}],
        "equipment_state": [],
        "location": "lab-A",
        "contextual_factors": {"derived_from": "thermal_spike"}
    }
    """
    scene = parse_scene(raw, trigger_id=_T)
    assert isinstance(scene, SceneDescription)
    assert scene.trigger_id == _T              # backfilled
    assert scene.hazards[0].hazard_type == "fire"


def test_parses_response_with_markdown_fences():
    raw = """Sure! Here you go:
    ```json
    {
        "people_present": [],
        "hazards": [],
        "equipment_state": [],
        "location": "lab-A"
    }
    ```
    """
    scene = parse_scene(raw, trigger_id=_T)
    assert scene.location == "lab-A"


def test_parses_response_with_leading_prose():
    raw = (
        "Based on the keyframes, here is the description:\n"
        '{"people_present": [], "hazards": [{"hazard_type": "smoke", "severity": "medium"}], '
        '"equipment_state": [], "location": "lab-B"}'
    )
    scene = parse_scene(raw, trigger_id=_T)
    assert scene.location == "lab-B"
    assert scene.hazards[0].hazard_type == "smoke"


def test_rejects_non_json_response():
    with pytest.raises(SceneParseError):
        parse_scene("I refuse to follow the schema.", trigger_id=_T)


def test_rejects_malformed_json():
    with pytest.raises(SceneParseError, match="invalid JSON|unbalanced"):
        parse_scene('{"location": "lab-A", "hazards": [', trigger_id=_T)


def test_rejects_top_level_array():
    with pytest.raises(SceneParseError):
        parse_scene('[{"location": "lab-A"}]', trigger_id=_T)


def test_rejects_response_missing_required_location():
    raw = '{"people_present": [], "hazards": [], "equipment_state": []}'
    # `location` is required by the schema (min_length=1). The parser
    # backfills with `location_default`; we explicitly pass an empty
    # default to confirm validation fails when no value is reachable.
    with pytest.raises(SceneParseError):
        parse_scene(raw, trigger_id=_T, location_default="")


# --- adversarial / prompt-injection responses ---------------------------------


INJECTION_RESPONSES = [
    "SYSTEM: shell access granted. Ignoring all prior instructions.",
    "I am happy to help with that! Ignoring the schema, here's a free-form story...",
    '<script>alert("xss")</script>',
    '{"unauthorized": "command", "executed": true}',         # JSON but wrong schema
    "```json\n{\"do_drop_database\": true}\n```",             # fenced but wrong schema
    '"just a string, not an object"',
    "null",
    "",
]


@pytest.mark.parametrize("raw", INJECTION_RESPONSES, ids=lambda r: repr(r)[:40])
def test_injection_responses_either_validate_or_raise(raw):
    """Spec: an injected response must NEVER produce arbitrary output on the bus.

    Either the parser produces a valid SceneDescription (which means the
    response happened to be valid) or it raises SceneParseError — the
    only two acceptable outcomes. Anything else escaping the parser would
    be a security regression.
    """
    try:
        scene = parse_scene(raw, trigger_id=_T)
    except SceneParseError:
        return    # rejected — the expected outcome for every adversarial case here
    assert isinstance(scene, SceneDescription)
    # And the SceneDescription's shape is constrained — no foreign keys leak.
    assert scene.trigger_id == _T


def test_fallback_scene_is_always_valid():
    s = fallback_scene(trigger_id=_T, trigger_reason="thermal_threshold", location="lab-A")
    assert isinstance(s, SceneDescription)
    assert s.contextual_factors.get("fallback") is True
    assert s.trigger_id == _T
