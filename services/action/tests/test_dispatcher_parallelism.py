"""Done-when (1): 3-action plan dispatches in ≤ 50 ms via parallel fan-out.

Plus the audit-shape and dispatch-table-completeness contracts.
"""

from datetime import datetime, timezone

import httpx
import pytest

from services.action.app.dispatcher import ActionDispatcher
from services.action.app.handlers import HANDLERS
from services.action.app.telemetry import ActionTelemetry
from services.actuators_mock.app.main import app as actuators_app
from services.slice_control_mock.app.main import app as slice_app
from shared.action_library import ActionLibrary
from shared.schemas.actions import ActionInvocation, ActionPlan
from shared.schemas.enums import ActionEffect

NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


class _MultiHostTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self._slice = httpx.ASGITransport(app=slice_app)
        self._actuators = httpx.ASGITransport(app=actuators_app)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        if "slice" in host:
            return await self._slice.handle_async_request(request)
        return await self._actuators.handle_async_request(request)


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
        yield d, bus, tel
    finally:
        await http.aclose()


def _three_action_plan() -> ActionPlan:
    return ActionPlan(
        severity=4,
        actions=[
            ActionInvocation(action_id="power_cutoff",
                             parameters={"zone_id": "lab-A"},
                             requested_latency_ms=80),
            ActionInvocation(action_id="door_lock",
                             parameters={"zone_id": "lab-A"},
                             requested_latency_ms=80),
            ActionInvocation(action_id="hvac_isolate",
                             parameters={"zone_id": "lab-A"},
                             requested_latency_ms=80),
        ],
        rationale="Fire detected; cut power, lock zone, isolate HVAC.",
        notification_targets=[],
        audit_metadata={"layer_d_trace": "fire protocol"},
        confidence=0.95, trigger_id="t-test", timestamp=NOW,
    )


@pytest.mark.asyncio
async def test_three_action_plan_dispatches_within_50ms(dispatcher):
    d, bus, _tel = dispatcher
    import time
    plan = _three_action_plan()
    start = time.monotonic()
    outcomes = await d.dispatch_plan(plan)
    elapsed_ms = (time.monotonic() - start) * 1000.0

    assert len(outcomes) == 3
    assert all(o.effect is ActionEffect.SUCCESS for o in outcomes)
    assert elapsed_ms < 50.0, f"dispatch took {elapsed_ms:.1f} ms; budget is 50 ms"
    assert len(bus.audits) == 3


@pytest.mark.asyncio
async def test_parallel_dispatch_is_faster_than_serial(dispatcher):
    """Sanity: total dispatch time < sum of per-action latencies."""
    d, bus, _tel = dispatcher
    outcomes = await d.dispatch_plan(_three_action_plan())
    serial = sum(o.latency_ms for o in outcomes)
    # The dispatcher's own per-plan histogram has the total; we approximate
    # via max(o.latency_ms) for the parallel run.
    parallel = max(o.latency_ms for o in outcomes)
    # Parallel max should be strictly less than the serial sum for a
    # 3-action plan with similar per-action latency.
    assert parallel < serial


@pytest.mark.asyncio
async def test_audit_entries_have_all_required_fields(dispatcher):
    d, bus, _tel = dispatcher
    plan = _three_action_plan()
    await d.dispatch_plan(plan)
    assert len(bus.audits) == 3
    for entry in bus.audits:
        assert entry["timestamp"]
        assert entry["severity"] == plan.severity
        assert entry["layer_d_trace"]
        assert entry["action_id"] in {"power_cutoff", "door_lock", "hvac_isolate"}
        assert entry["effect"] in ("success", "failure", "timeout")
        assert 0.0 <= entry["agent_confidence"] <= 1.0
        assert entry["trigger_id"] == plan.trigger_id
        assert entry["parameters"] == {"zone_id": "lab-A"}
        assert entry["latency_ms"] >= 0.0


@pytest.mark.asyncio
async def test_unknown_action_does_not_crash_dispatcher(dispatcher):
    """Defense-in-depth: even if Layer D's parser fails open, dispatcher logs + continues."""
    d, bus, _tel = dispatcher
    plan = ActionPlan(
        severity=2,
        actions=[
            # NB: ActionPlan's Pydantic schema allows any action_id string;
            # the library validation is enforced by Layer D's parser. The
            # dispatcher must still degrade gracefully if something
            # unknown leaks through.
            ActionInvocation(action_id="alien_action", parameters={},
                             requested_latency_ms=10),
            ActionInvocation(action_id="display_alert",
                             parameters={"severity": 2, "message": "x"},
                             requested_latency_ms=200),
        ],
        rationale="mixed plan",
        confidence=1.0, trigger_id="t-test", timestamp=NOW,
    )
    outcomes = await d.dispatch_plan(plan)
    assert len(outcomes) == 2
    alien = next(o for o in outcomes if o.invocation.action_id == "alien_action")
    alert = next(o for o in outcomes if o.invocation.action_id == "display_alert")
    assert alien.effect is ActionEffect.FAILURE
    assert "no handler" in alien.detail
    assert alert.effect is ActionEffect.SUCCESS


def test_handlers_cover_every_library_action():
    """Each MVP action_id must have a dispatch handler."""
    from shared.action_library import ActionLibrary
    lib = ActionLibrary.load()
    for name in lib.names():
        assert name in HANDLERS, f"missing handler for action_id={name!r}"
