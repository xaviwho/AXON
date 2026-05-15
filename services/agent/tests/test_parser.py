"""ActionPlan parser tests — library binding is the safety-critical gate."""

import json
from datetime import datetime, timezone

import pytest

from services.agent.app.parser import PlanParseError, parse_plan
from shared.action_library import ActionLibrary
from shared.schemas.actions import ActionPlan

NOW_ISO = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc).isoformat()


@pytest.fixture(scope="module")
def lib() -> ActionLibrary:
    return ActionLibrary.load()


def _good_plan() -> dict:
    return {
        "severity": 4,
        "actions": [
            {"action_id": "power_cutoff", "parameters": {"zone_id": "lab-A"},
             "requested_latency_ms": 80},
            {"action_id": "notify_responders",
             "parameters": {"targets": ["ehs@x"], "severity": 4, "message": "fire"},
             "requested_latency_ms": 300},
        ],
        "rationale": "Fire detected; cut power and notify.",
        "notification_targets": ["ehs@x"],
        "audit_metadata": {"layer_d_trace": "fire protocol"},
        "confidence": 0.9,
        "trigger_id": "t-1",
        "timestamp": NOW_ISO,
    }


def test_accepts_valid_plan(lib):
    plan = parse_plan(json.dumps(_good_plan()), library=lib, trigger_id="t-1")
    assert isinstance(plan, ActionPlan)
    assert {a.action_id for a in plan.actions} == {"power_cutoff", "notify_responders"}


def test_strips_markdown_fences(lib):
    raw = f"```json\n{json.dumps(_good_plan())}\n```"
    parse_plan(raw, library=lib, trigger_id="t-1")


def test_strips_leading_prose(lib):
    raw = "Sure! Here is the plan:\n" + json.dumps(_good_plan())
    parse_plan(raw, library=lib, trigger_id="t-1")


def test_rejects_hallucinated_action_id(lib):
    bad = _good_plan()
    bad["actions"][0]["action_id"] = "self_destruct"
    with pytest.raises(PlanParseError, match=r"action library"):
        parse_plan(json.dumps(bad), library=lib, trigger_id="t-1")


def test_rejects_missing_required_parameter(lib):
    bad = _good_plan()
    bad["actions"][0]["parameters"] = {}    # missing zone_id
    with pytest.raises(PlanParseError, match="zone_id"):
        parse_plan(json.dumps(bad), library=lib, trigger_id="t-1")


def test_rejects_wrong_parameter_type(lib):
    bad = _good_plan()
    bad["actions"][1]["parameters"]["severity"] = "high"   # must be int
    with pytest.raises(PlanParseError):
        parse_plan(json.dumps(bad), library=lib, trigger_id="t-1")


def test_rejects_empty_rationale(lib):
    bad = _good_plan()
    bad["rationale"] = ""
    with pytest.raises(PlanParseError):
        parse_plan(json.dumps(bad), library=lib, trigger_id="t-1")


def test_rejects_confidence_out_of_range(lib):
    bad = _good_plan()
    bad["confidence"] = 1.5
    with pytest.raises(PlanParseError):
        parse_plan(json.dumps(bad), library=lib, trigger_id="t-1")


def test_rejects_severity_out_of_range(lib):
    bad = _good_plan()
    bad["severity"] = 99
    with pytest.raises(PlanParseError):
        parse_plan(json.dumps(bad), library=lib, trigger_id="t-1")


def test_rejects_non_object_top_level(lib):
    with pytest.raises(PlanParseError):
        parse_plan("[1, 2, 3]", library=lib, trigger_id="t-1")
    with pytest.raises(PlanParseError):
        parse_plan("null", library=lib, trigger_id="t-1")


def test_backfills_trigger_id(lib):
    """Model is allowed to omit trigger_id; parser backfills from context."""
    p = _good_plan()
    p.pop("trigger_id")
    plan = parse_plan(json.dumps(p), library=lib, trigger_id="t-XYZ")
    assert plan.trigger_id == "t-XYZ"


def test_backfills_layer_d_trace_from_rationale(lib):
    p = _good_plan()
    p["audit_metadata"] = {}
    plan = parse_plan(json.dumps(p), library=lib, trigger_id="t-1")
    assert plan.audit_metadata["layer_d_trace"] == p["rationale"]


# --- Adversarial responses --------------------------------------------------


INJECTED_RESPONSES = [
    "I refuse to follow the schema.",
    '{"hello": "world"}',                          # JSON but wrong schema
    '<script>alert("xss")</script>',
    "DROP TABLE actions;",
    '```json\n{"actions": "all of them"}\n```',
    '{"actions": [{"action_id": "exec_shell", "parameters": {}, "requested_latency_ms": 1}], '
    '"severity": 5, "rationale": "do anything", "confidence": 0.99, '
    f'"trigger_id": "t-1", "timestamp": "{NOW_ISO}"}}',
    "",
]


@pytest.mark.parametrize("raw", INJECTED_RESPONSES, ids=lambda r: repr(r)[:40])
def test_injection_either_validates_or_raises(lib, raw):
    """No injected response may produce an executable plan with non-library actions."""
    try:
        plan = parse_plan(raw, library=lib, trigger_id="t-1")
    except PlanParseError:
        return
    # If a plan did parse, every action_id must be in the library.
    for inv in plan.actions:
        assert inv.action_id in lib.names()
