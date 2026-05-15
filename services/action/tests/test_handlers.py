"""Per-action handler tests against an in-process mock HTTP server.

We mount the same mock applications the production stack uses
(slice_control_mock and actuators_mock) in an ASGI transport so every
handler is exercised end-to-end without any container.
"""

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from services.action.app.handlers import HANDLERS, HandlerContext
from services.actuators_mock.app.main import app as actuators_app
from services.slice_control_mock.app.main import app as slice_app
from shared.bus import ALERT_STREAM, Bus
from shared.schemas.actions import ActionInvocation, ActionPlan
from shared.schemas.enums import ActionEffect

NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


class _MultiHostTransport(httpx.AsyncBaseTransport):
    """Route requests by hostname to the appropriate in-process app."""

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


def _plan() -> ActionPlan:
    return ActionPlan(
        severity=4,
        actions=[],
        rationale="test",
        confidence=1.0,
        trigger_id="t-test",
        timestamp=NOW,
    )


@pytest.fixture
async def ctx():
    http = httpx.AsyncClient(transport=_MultiHostTransport(), timeout=5.0)
    try:
        yield HandlerContext(
            http=http,
            bus=_MemoryBus(),
            actuators_url="http://actuators-mock:8000",
            slice_control_url="http://slice-control-mock:8000",
            timeout_seconds=5.0,
            plan=_plan(),
        )
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_power_cutoff_returns_success(ctx):
    inv = ActionInvocation(
        action_id="power_cutoff",
        parameters={"zone_id": "lab-A"},
        requested_latency_ms=80,
    )
    out = await HANDLERS["power_cutoff"](ctx, inv)
    assert out.effect is ActionEffect.SUCCESS
    assert out.latency_ms > 0


@pytest.mark.asyncio
async def test_door_lock_and_unlock(ctx):
    lock = ActionInvocation(action_id="door_lock", parameters={"zone_id": "lab-A"},
                            requested_latency_ms=80)
    unlock = ActionInvocation(action_id="door_unlock", parameters={"zone_id": "lab-A"},
                              requested_latency_ms=80)
    out_l = await HANDLERS["door_lock"](ctx, lock)
    out_u = await HANDLERS["door_unlock"](ctx, unlock)
    assert out_l.effect is ActionEffect.SUCCESS
    assert out_u.effect is ActionEffect.SUCCESS


@pytest.mark.asyncio
async def test_hvac_isolate(ctx):
    inv = ActionInvocation(action_id="hvac_isolate", parameters={"zone_id": "lab-A"},
                           requested_latency_ms=80)
    out = await HANDLERS["hvac_isolate"](ctx, inv)
    assert out.effect is ActionEffect.SUCCESS


@pytest.mark.asyncio
async def test_slice_reshape_applies_priority_and_preempts(ctx):
    inv = ActionInvocation(
        action_id="slice_reshape",
        parameters={
            "slices": [{"slice_id": "URLLC", "priority": 9},
                       {"slice_id": "eMBB", "priority": 3}],
            "duration_seconds": 30,
        },
        requested_latency_ms=60,
    )
    out = await HANDLERS["slice_reshape"](ctx, inv)
    assert out.effect is ActionEffect.SUCCESS
    # Slice state reflects the change.
    r = await ctx.http.get("http://slice-control-mock:8000/slices/state")
    state = r.json()
    assert state["URLLC"]["priority"] == 9
    assert state["eMBB"]["priority"] == 3
    assert state["preempt_active"] is True


@pytest.mark.asyncio
async def test_notify_responders_returns_success(ctx):
    inv = ActionInvocation(
        action_id="notify_responders",
        parameters={"targets": ["ehs@x"], "severity": 4, "message": "fire"},
        requested_latency_ms=300,
    )
    out = await HANDLERS["notify_responders"](ctx, inv)
    assert out.effect is ActionEffect.SUCCESS


@pytest.mark.asyncio
async def test_display_alert_publishes_to_alert_stream(ctx):
    inv = ActionInvocation(
        action_id="display_alert",
        parameters={"severity": 4, "message": "fire in lab-A", "zone_id": "lab-A"},
        requested_latency_ms=300,
    )
    out = await HANDLERS["display_alert"](ctx, inv)
    assert out.effect is ActionEffect.SUCCESS
    assert len(ctx.bus.alerts) == 1
    assert ctx.bus.alerts[0]["message"] == "fire in lab-A"
    assert ctx.bus.alerts[0]["trigger_id"] == "t-test"


@pytest.mark.asyncio
async def test_video_stream_returns_success(ctx):
    inv = ActionInvocation(
        action_id="video_stream_to_responder",
        parameters={"camera_id": "cam-01", "responder_id": "r-1"},
        requested_latency_ms=400,
    )
    out = await HANDLERS["video_stream_to_responder"](ctx, inv)
    assert out.effect is ActionEffect.SUCCESS


@pytest.mark.asyncio
async def test_http_failure_surfaces_as_failure_effect(ctx):
    """Hit the actuators_mock failure-injection route."""
    inv = ActionInvocation(
        action_id="power_cutoff",
        parameters={"zone_id": "lab-A"},
        requested_latency_ms=80,
    )
    # Repoint at the failure endpoint by hand.
    from services.action.app import handlers as h
    original = h._http_post

    async def force_failure(c, _url, body):
        return await original(c, f"{c.actuators_url}/failure/power/lab-A", body)

    h._http_post = force_failure
    try:
        out = await HANDLERS["power_cutoff"](ctx, inv)
    finally:
        h._http_post = original
    assert out.effect is ActionEffect.FAILURE
    assert "500" in out.detail
