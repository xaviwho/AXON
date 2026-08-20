"""Fail-safe posture — empirical evidence for CLAUDE.md's guarantees.

The paper's Proposition 1 is a theorem about the medical projection; the
system-level guarantees around it (LLM crash → fallback protocol still
fires, actuator failure → correct effect on audit, malformed bus messages
→ pipeline stays running) are stated in prose. These tests verify each
one with a small chaos surface so the paper can cite them.

Each test is deliberately narrow: one fault, one expected behavior. The
test names are the fail-safe claims.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from services.action.app.dispatcher import ActionDispatcher
from services.action.app.telemetry import ActionTelemetry
from shared.action_library import ActionLibrary
from shared.schemas.actions import ActionInvocation, ActionPlan
from shared.schemas.anomaly import AnomalyScore, ContributingSignal
from shared.schemas.enums import ActionEffect

NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


class _ChaosTransport(httpx.AsyncBaseTransport):
    """Programmable transport: per-URL-substring response override."""

    def __init__(self, rules: list[tuple[str, str]]) -> None:
        # rules = [(url_substring, mode), ...] where mode in
        # {"500", "timeout", "exception", "ok"}. First match wins.
        self._rules = rules

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for needle, mode in self._rules:
            if needle in url:
                if mode == "500":
                    return httpx.Response(500, text="chaos: forced 500", request=request)
                if mode == "timeout":
                    raise httpx.TimeoutException("chaos: forced timeout", request=request)
                if mode == "exception":
                    raise httpx.ConnectError("chaos: forced connect error", request=request)
                if mode == "ok":
                    return httpx.Response(200, json={"ok": True}, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)


class _MemoryBus:
    healthy = True

    def __init__(self) -> None:
        self.alerts: list[dict] = []
        self.audits: list[dict] = []

    async def publish_alert(self, payload):
        self.alerts.append(payload)

    async def publish_audit(self, payload):
        self.audits.append(payload)


@pytest.fixture
def signing_env(monkeypatch):
    monkeypatch.setenv("AXON_AUDIT_SIGNING_KEY", "c" * 64)


def _make_dispatcher(transport: httpx.AsyncBaseTransport):
    http = httpx.AsyncClient(transport=transport, timeout=2.0)
    bus = _MemoryBus()
    d = ActionDispatcher(
        bus=bus, http=http, telemetry=ActionTelemetry(),
        library=ActionLibrary.load(),
        actuators_url="http://actuators-mock:8000",
        slice_control_url="http://slice-control-mock:8000",
        timeout_seconds=0.5, max_concurrent_plans=5,
    )
    return d, bus, http


def _six_action_plan(trigger_id: str = "t-chaos") -> ActionPlan:
    return ActionPlan(
        severity=4,
        actions=[
            ActionInvocation(action_id="power_cutoff",
                             parameters={"zone_id": "lab-A"}, requested_latency_ms=80),
            ActionInvocation(action_id="hvac_isolate",
                             parameters={"zone_id": "lab-A"}, requested_latency_ms=80),
            ActionInvocation(action_id="slice_reshape",
                             parameters={"slices": [{"slice_id": "URLLC", "priority": 9}]},
                             requested_latency_ms=60),
            ActionInvocation(action_id="notify_responders",
                             parameters={"targets": ["ehs@x"], "severity": 4,
                                         "message": "x"},
                             requested_latency_ms=300),
            ActionInvocation(action_id="display_alert",
                             parameters={"severity": 4, "message": "x"},
                             requested_latency_ms=200),
        ],
        rationale="chaos plan",
        audit_metadata={"layer_d_trace": "chaos"},
        confidence=1.0, trigger_id=trigger_id, timestamp=NOW,
    )


# ---------------------------------------------------------------------------
# Group A: actuator / network failures land the correct ActionEffect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_actuator_500_records_failure(signing_env):
    d, bus, http = _make_dispatcher(_ChaosTransport([
        ("/equipment/power_cutoff", "500"),
    ]))
    try:
        outcomes = await d.dispatch_plan(_six_action_plan())
    finally:
        await http.aclose()

    by_action = {o.invocation.action_id: o for o in outcomes}
    assert by_action["power_cutoff"].effect is ActionEffect.FAILURE
    # Other actions unaffected.
    assert by_action["hvac_isolate"].effect is ActionEffect.SUCCESS
    # Audit stream still gets one record per action.
    assert len(bus.audits) == len(outcomes)


@pytest.mark.asyncio
async def test_actuator_timeout_records_timeout_effect(signing_env):
    d, bus, http = _make_dispatcher(_ChaosTransport([
        ("/hvac/isolate", "timeout"),
    ]))
    try:
        outcomes = await d.dispatch_plan(_six_action_plan())
    finally:
        await http.aclose()

    by_action = {o.invocation.action_id: o for o in outcomes}
    assert by_action["hvac_isolate"].effect is ActionEffect.TIMEOUT
    assert by_action["power_cutoff"].effect is ActionEffect.SUCCESS


@pytest.mark.asyncio
async def test_slice_controller_503_isolated_to_slice_reshape(signing_env):
    """Slice-control failure must not cascade into actuator failures."""
    d, bus, http = _make_dispatcher(_ChaosTransport([
        ("/slices/", "500"),
    ]))
    try:
        outcomes = await d.dispatch_plan(_six_action_plan())
    finally:
        await http.aclose()

    by_action = {o.invocation.action_id: o for o in outcomes}
    assert by_action["slice_reshape"].effect is ActionEffect.FAILURE
    for a in ("power_cutoff", "hvac_isolate", "notify_responders", "display_alert"):
        assert by_action[a].effect is ActionEffect.SUCCESS, (
            f"unrelated action {a} must not degrade when slice controller fails"
        )


@pytest.mark.asyncio
async def test_connect_error_records_failure_not_crash(signing_env):
    """A raw ConnectError inside a handler must land as an audit, not escape."""
    d, bus, http = _make_dispatcher(_ChaosTransport([
        ("/equipment/", "exception"),
    ]))
    try:
        outcomes = await d.dispatch_plan(_six_action_plan())
    finally:
        await http.aclose()

    assert len(outcomes) == len(bus.audits)
    # display_alert doesn't hit actuators, still succeeds.
    by_action = {o.invocation.action_id: o for o in outcomes}
    assert by_action["display_alert"].effect is ActionEffect.SUCCESS


# ---------------------------------------------------------------------------
# Group B: ingestion-path malformed input never crashes the pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_anomaly_is_skipped(signing_env):
    d, bus, http = _make_dispatcher(_ChaosTransport([]))
    try:
        # A parse failure returns None; nothing should be dispatched.
        parsed = d._parse_anomaly({b"data": b"{ not valid json"})
        assert parsed is None
        assert bus.audits == []
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_malformed_plan_is_skipped(signing_env):
    d, bus, http = _make_dispatcher(_ChaosTransport([]))
    try:
        parsed = d._parse_plan({b"data": b"{ not valid json"})
        assert parsed is None
        assert bus.audits == []
    finally:
        await http.aclose()


# ---------------------------------------------------------------------------
# Group C: Phase-1 protocol construction under adversarial inputs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_trigger_reason_still_produces_valid_plan(signing_env):
    """A trigger_reason that matches no rule must still yield a schema-valid
    protocol plan (informational-only, but dispatchable)."""
    d, bus, http = _make_dispatcher(_ChaosTransport([]))
    try:
        anomaly = AnomalyScore(
            composite_score=0.8,
            contributing_signals=[
                ContributingSignal(source="sensor:unknown", weight=0.8, description="?"),
            ],
            threshold_exceeded=True,
            trigger_reason="reactor_malfunction",    # not in the rule set
            trigger_id="t-unknown",
            timestamp=NOW,
        )
        await d._dispatch_phase1(anomaly)
    finally:
        await http.aclose()

    dispatched = {a["action_id"] for a in bus.audits}
    assert dispatched, "generic protocol must still emit at least one action"
    # Generic protocol is informational — must NOT include actuator escalation.
    assert "power_cutoff" not in dispatched
    assert "door_lock" not in dispatched


@pytest.mark.asyncio
async def test_compound_trigger_dispatches_union_of_protocols(signing_env):
    """thermal_threshold + gas_threshold in the same trigger fires both."""
    d, bus, http = _make_dispatcher(_ChaosTransport([]))
    try:
        anomaly = AnomalyScore(
            composite_score=1.0,
            contributing_signals=[
                ContributingSignal(source="sensor:thermal", weight=0.6),
                ContributingSignal(source="sensor:gas", weight=0.6),
            ],
            threshold_exceeded=True,
            trigger_reason="thermal_threshold|gas_threshold",
            trigger_id="t-compound",
            timestamp=NOW,
        )
        await d._dispatch_phase1(anomaly)
    finally:
        await http.aclose()

    dispatched = {a["action_id"] for a in bus.audits}
    assert "power_cutoff" in dispatched        # from fire branch
    assert "hvac_isolate" in dispatched        # both branches agree
    assert "door_lock" in dispatched           # fire OR gas (medical override absent)


@pytest.mark.asyncio
async def test_below_threshold_anomaly_does_not_dispatch(signing_env):
    d, bus, http = _make_dispatcher(_ChaosTransport([]))
    try:
        anomaly = AnomalyScore(
            composite_score=0.2, contributing_signals=[],
            threshold_exceeded=False,
            trigger_reason="thermal_threshold",
            trigger_id="t-below", timestamp=NOW,
        )
        await d._dispatch_phase1(anomaly)
    finally:
        await http.aclose()
    assert bus.audits == []


# ---------------------------------------------------------------------------
# Group D: every emitted audit is signed and self-verifies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_dispatched_audit_is_signed(signing_env):
    from shared.audit_signing import verify_entry

    d, bus, http = _make_dispatcher(_ChaosTransport([]))
    try:
        await d.dispatch_plan(_six_action_plan())
    finally:
        await http.aclose()

    assert bus.audits
    for entry in bus.audits:
        assert entry.get("signature"), "every audit must be signed"
        assert verify_entry(entry), "signature must verify with the configured key"
