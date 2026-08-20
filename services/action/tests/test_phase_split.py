"""Two-phase Pi_g / Pi_d split (methodology Eq. 1 literalized).

Verifies:
  1. An anomaly alone triggers a Phase-1 protocol dispatch (F(beta)) with
     phase=1 stamped on every audit.
  2. A subsequent refined plan on the same trigger_id dispatches only the
     delta as phase=2 (actions matching Phase 1 by (action_id, params) are
     suppressed).
  3. The medical override survives Phase 1 (no door_lock when
     person_prone_persistent is in beta).
  4. A plan arriving without a prior anomaly still dispatches (as phase=1),
     preserving direct-call backwards compatibility.
"""

from datetime import datetime, timezone

import httpx
import pytest

from services.action.app.dispatcher import ActionDispatcher
from services.action.app.telemetry import ActionTelemetry
from services.actuators_mock.app.main import app as actuators_app
from services.slice_control_mock.app.main import app as slice_app
from shared.action_library import ActionLibrary
from shared.schemas.actions import ActionInvocation, ActionPlan
from shared.schemas.anomaly import AnomalyScore, ContributingSignal
from shared.schemas.enums import ActionEffect

NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


class _MultiHostTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self._slice = httpx.ASGITransport(app=slice_app)
        self._actuators = httpx.ASGITransport(app=actuators_app)

    async def handle_async_request(self, request):
        host = request.url.host or ""
        if "slice" in host:
            return await self._slice.handle_async_request(request)
        return await self._actuators.handle_async_request(request)


class _MemoryBus:
    healthy = True

    def __init__(self):
        self.alerts: list[dict] = []
        self.audits: list[dict] = []

    async def publish_alert(self, payload):
        self.alerts.append(payload)

    async def publish_audit(self, payload):
        self.audits.append(payload)


@pytest.fixture
async def dispatcher():
    http = httpx.AsyncClient(transport=_MultiHostTransport(), timeout=5.0)
    bus = _MemoryBus()
    tel = ActionTelemetry()
    d = ActionDispatcher(
        bus=bus, http=http, telemetry=tel,
        library=ActionLibrary.load(),
        actuators_url="http://actuators-mock:8000",
        slice_control_url="http://slice-control-mock:8000",
        timeout_seconds=5.0, max_concurrent_plans=5,
    )
    try:
        yield d, bus
    finally:
        await http.aclose()


def _anomaly(reason: str, trigger_id: str = "t-phase") -> AnomalyScore:
    return AnomalyScore(
        composite_score=0.6,
        contributing_signals=[
            ContributingSignal(source="sensor:thermal", weight=0.6, description=reason),
        ],
        threshold_exceeded=True,
        trigger_reason=reason,
        trigger_id=trigger_id,
        timestamp=NOW,
    )


@pytest.mark.asyncio
async def test_anomaly_dispatches_phase1_protocol(dispatcher):
    d, bus = dispatcher
    await d._dispatch_phase1(_anomaly("thermal_threshold"))

    assert d.phase1_total == 1
    assert bus.audits, "phase-1 must emit at least one audit"
    # Every audit stamped phase=1
    assert all(a["phase"] == 1 for a in bus.audits)
    # Fire protocol produces power_cutoff among others
    dispatched_ids = {a["action_id"] for a in bus.audits}
    assert "power_cutoff" in dispatched_ids
    assert "slice_reshape" in dispatched_ids
    # Trigger cached for later supersedence
    assert "t-phase" in d._phase1_by_trigger


@pytest.mark.asyncio
async def test_medical_phase1_strips_door_lock(dispatcher):
    d, bus = dispatcher
    await d._dispatch_phase1(_anomaly("person_prone_persistent", trigger_id="t-med"))

    dispatched_ids = {a["action_id"] for a in bus.audits}
    assert "door_lock" not in dispatched_ids, (
        "medical override must strip door_lock from Phase-1 protocol"
    )
    assert "door_unlock" in dispatched_ids


@pytest.mark.asyncio
async def test_phase2_dispatches_only_delta(dispatcher):
    """Refined plan on same trigger_id → only novel actions dispatch as phase=2."""
    d, bus = dispatcher
    trigger = "t-delta"
    await d._dispatch_phase1(_anomaly("thermal_threshold", trigger_id=trigger))
    phase1_count = len(bus.audits)
    assert phase1_count > 0

    # Refined plan: one identical action (dedupe) + one novel one (should fire).
    refined = ActionPlan(
        severity=4,
        actions=[
            # Identical to a Phase-1 action → suppressed
            ActionInvocation(
                action_id="power_cutoff",
                parameters={"zone_id": "unknown"},
                requested_latency_ms=80,
            ),
            # Novel action → dispatched as phase=2
            ActionInvocation(
                action_id="video_stream_to_responder",
                parameters={"camera_id": "cam-A", "responder_id": "resp-1",
                            "duration_seconds": 30},
                requested_latency_ms=200,
            ),
        ],
        rationale="agent refinement adds a video stream",
        audit_metadata={"layer_d_trace": "phase-2 supersedence"},
        confidence=0.9,
        trigger_id=trigger,
        timestamp=NOW,
    )
    await d._dispatch_phase2(refined)

    delta_audits = bus.audits[phase1_count:]
    assert len(delta_audits) == 1, (
        f"only the novel action should fire; got {[a['action_id'] for a in delta_audits]}"
    )
    assert delta_audits[0]["action_id"] == "video_stream_to_responder"
    assert delta_audits[0]["phase"] == 2
    assert d.phase2_total == 1


@pytest.mark.asyncio
async def test_phase2_subset_of_phase1_is_noop(dispatcher):
    """Refined plan entirely contained in Phase 1 → nothing new dispatches."""
    d, bus = dispatcher
    trigger = "t-subset"
    await d._dispatch_phase1(_anomaly("thermal_threshold", trigger_id=trigger))
    baseline = len(bus.audits)

    subset = ActionPlan(
        severity=4,
        actions=[
            ActionInvocation(
                action_id="power_cutoff",
                parameters={"zone_id": "unknown"},
                requested_latency_ms=80,
            ),
        ],
        rationale="agent refinement adds nothing new",
        audit_metadata={"layer_d_trace": "phase-2 noop"},
        confidence=0.9,
        trigger_id=trigger,
        timestamp=NOW,
    )
    await d._dispatch_phase2(subset)

    assert len(bus.audits) == baseline
    assert d.phase2_total == 0


@pytest.mark.asyncio
async def test_plan_without_prior_anomaly_dispatches_as_phase1(dispatcher):
    """Backwards compat: lone plan (no matching anomaly) fires as phase=1."""
    d, bus = dispatcher
    plan = ActionPlan(
        severity=2,
        actions=[
            ActionInvocation(
                action_id="display_alert",
                parameters={"severity": 2, "message": "standalone"},
                requested_latency_ms=200,
            ),
        ],
        rationale="lone plan",
        audit_metadata={"layer_d_trace": "standalone"},
        confidence=1.0,
        trigger_id="t-lone",
        timestamp=NOW,
    )
    await d._dispatch_phase2(plan)

    assert len(bus.audits) == 1
    assert bus.audits[0]["phase"] == 1
    assert bus.audits[0]["effect"] == ActionEffect.SUCCESS.value
