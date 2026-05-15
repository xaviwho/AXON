"""Per-action handlers.

Each handler takes an `ActionInvocation` and the dispatch context (HTTP
client, bus, plan-level metadata) and returns an `ActionOutcome`. Handlers
never raise — they translate everything into a `success / failure /
timeout` ActionEffect so the dispatcher can write a faithful AuditEntry.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from loguru import logger

from shared.bus import Bus
from shared.schemas.actions import ActionInvocation, ActionPlan
from shared.schemas.enums import ActionEffect


@dataclass
class HandlerContext:
    http: httpx.AsyncClient
    bus: Bus
    actuators_url: str
    slice_control_url: str
    timeout_seconds: float
    plan: ActionPlan


@dataclass
class ActionOutcome:
    invocation: ActionInvocation
    effect: ActionEffect
    latency_ms: float
    detail: str = ""


async def _http_post(
    ctx: HandlerContext, url: str, body: dict
) -> tuple[ActionEffect, str]:
    try:
        r = await ctx.http.post(url, json=body, timeout=ctx.timeout_seconds)
        if r.status_code // 100 == 2:
            return ActionEffect.SUCCESS, f"HTTP {r.status_code}"
        return ActionEffect.FAILURE, f"HTTP {r.status_code}: {r.text[:200]}"
    except httpx.TimeoutException as exc:
        return ActionEffect.TIMEOUT, f"timeout: {exc}"
    except httpx.HTTPError as exc:
        return ActionEffect.FAILURE, f"http error: {exc}"


def _timed_outcome(
    inv: ActionInvocation, effect: ActionEffect, detail: str, start: float
) -> ActionOutcome:
    return ActionOutcome(
        invocation=inv,
        effect=effect,
        latency_ms=(time.monotonic() - start) * 1000.0,
        detail=detail,
    )


# --- equipment / door / HVAC handlers ----------------------------------------


async def handle_power_cutoff(ctx: HandlerContext, inv: ActionInvocation) -> ActionOutcome:
    start = time.monotonic()
    eff, det = await _http_post(
        ctx, f"{ctx.actuators_url}/equipment/power_cutoff", inv.parameters,
    )
    return _timed_outcome(inv, eff, det, start)


async def handle_door_lock(ctx: HandlerContext, inv: ActionInvocation) -> ActionOutcome:
    start = time.monotonic()
    eff, det = await _http_post(
        ctx, f"{ctx.actuators_url}/door/lock", inv.parameters,
    )
    return _timed_outcome(inv, eff, det, start)


async def handle_door_unlock(ctx: HandlerContext, inv: ActionInvocation) -> ActionOutcome:
    start = time.monotonic()
    eff, det = await _http_post(
        ctx, f"{ctx.actuators_url}/door/unlock", inv.parameters,
    )
    return _timed_outcome(inv, eff, det, start)


async def handle_hvac_isolate(ctx: HandlerContext, inv: ActionInvocation) -> ActionOutcome:
    start = time.monotonic()
    eff, det = await _http_post(
        ctx, f"{ctx.actuators_url}/hvac/isolate", inv.parameters,
    )
    return _timed_outcome(inv, eff, det, start)


# --- slice_reshape -----------------------------------------------------------


async def handle_slice_reshape(ctx: HandlerContext, inv: ActionInvocation) -> ActionOutcome:
    start = time.monotonic()
    slices = inv.parameters.get("slices") or []
    detail_lines: list[str] = []
    overall = ActionEffect.SUCCESS
    for s in slices:
        slice_id = s["slice_id"]
        priority = s["priority"]
        url = f"{ctx.slice_control_url}/slices/{slice_id}/priority"
        eff, det = await _http_post(ctx, url, {"priority": priority})
        detail_lines.append(f"{slice_id}->p{priority}: {det}")
        if eff is not ActionEffect.SUCCESS:
            overall = eff    # surface the worst outcome
            break

    duration = inv.parameters.get("duration_seconds")
    if duration is not None and overall is ActionEffect.SUCCESS:
        preempt_url = f"{ctx.slice_control_url}/slices/preempt"
        eff, det = await _http_post(
            ctx, preempt_url,
            {"duration_seconds": int(duration),
             "reason": f"axon trigger {ctx.plan.trigger_id}"},
        )
        detail_lines.append(f"preempt {duration}s: {det}")
        if eff is not ActionEffect.SUCCESS:
            overall = eff

    return _timed_outcome(inv, overall, " | ".join(detail_lines), start)


# --- notify_responders / display_alert / video_stream_to_responder -----------


async def handle_notify_responders(ctx: HandlerContext, inv: ActionInvocation) -> ActionOutcome:
    """MVP behavior: log + audit. Production: SMS/Slack/PagerDuty fan-out."""
    start = time.monotonic()
    targets = inv.parameters.get("targets") or []
    severity = inv.parameters.get("severity")
    message = inv.parameters.get("message", "")
    logger.info(
        "[notify_responders] severity={} targets={} message={}",
        severity, targets, message,
    )
    return _timed_outcome(inv, ActionEffect.SUCCESS,
                          f"logged to {len(targets)} target(s)", start)


async def handle_display_alert(ctx: HandlerContext, inv: ActionInvocation) -> ActionOutcome:
    """Publish an alert event on the bus; console_api (Prompt 8) tails this."""
    start = time.monotonic()
    payload = {
        "trigger_id": ctx.plan.trigger_id,
        "severity": inv.parameters.get("severity"),
        "message": inv.parameters.get("message", ""),
        "zone_id": inv.parameters.get("zone_id"),
    }
    try:
        await ctx.bus.publish_alert(payload)
    except Exception as exc:    # noqa: BLE001
        return _timed_outcome(inv, ActionEffect.FAILURE, f"publish failed: {exc}", start)
    return _timed_outcome(inv, ActionEffect.SUCCESS, "alert published", start)


async def handle_video_stream_to_responder(
    ctx: HandlerContext, inv: ActionInvocation
) -> ActionOutcome:
    """MVP behavior: log + audit. Production: open a WebRTC session."""
    start = time.monotonic()
    logger.info(
        "[video_stream_to_responder] camera_id={} responder_id={}",
        inv.parameters.get("camera_id"),
        inv.parameters.get("responder_id"),
    )
    return _timed_outcome(inv, ActionEffect.SUCCESS, "logged", start)


# --- dispatch table ----------------------------------------------------------


HANDLERS = {
    "power_cutoff": handle_power_cutoff,
    "door_lock": handle_door_lock,
    "door_unlock": handle_door_unlock,
    "hvac_isolate": handle_hvac_isolate,
    "slice_reshape": handle_slice_reshape,
    "notify_responders": handle_notify_responders,
    "display_alert": handle_display_alert,
    "video_stream_to_responder": handle_video_stream_to_responder,
}


__all__ = ["ActionOutcome", "HANDLERS", "HandlerContext"]
