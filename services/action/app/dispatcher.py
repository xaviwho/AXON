"""ActionPlan dispatcher.

Subscribes to `axon:plans`. For each plan, fires every contained
ActionInvocation in parallel via asyncio.gather (we have no declared
inter-action dependencies in the MVP library), records per-action
AuditEntries on `axon:audit`, and reports per-action + per-plan latency.

Done-when for Prompt 7: a 3-action plan must dispatch in ≤ 50 ms. Parallel
fan-out with HTTP mocks on the same compose network achieves this with a
wide margin.
"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timezone

import httpx
from loguru import logger
from pydantic import ValidationError

from shared.bus import PLAN_STREAM, Bus
from shared.schemas.actions import ActionInvocation, ActionPlan
from shared.schemas.audit import AuditEntry
from shared.schemas.enums import ActionEffect

from .handlers import HANDLERS, ActionOutcome, HandlerContext
from .telemetry import ActionTelemetry


class NetworkMode:
    """Per-call network-condition simulator for the Wi-Fi vs URLLC comparison demo.

    `urllc` (default) is a no-op. `wifi` injects `base_ms + U(0, jitter_ms)`
    of artificial delay before each action handler runs, so the dispatcher's
    measured per-action latency includes the simulated contention. The
    underlying handler code is unchanged.

    Flipped via the runtime `POST /admin/network` endpoint — no restart.
    """

    def __init__(self) -> None:
        self.mode: str = "urllc"
        self.base_ms: float = 0.0
        self.jitter_ms: float = 0.0
        self._rng = random.Random(0xAA00)

    def configure(self, *, mode: str, base_ms: float = 0.0, jitter_ms: float = 0.0) -> None:
        self.mode = mode
        self.base_ms = base_ms
        self.jitter_ms = jitter_ms

    async def apply(self) -> None:
        if self.mode == "urllc" or (self.base_ms <= 0 and self.jitter_ms <= 0):
            return
        delay_ms = self.base_ms + self._rng.uniform(0.0, self.jitter_ms)
        await asyncio.sleep(delay_ms / 1000.0)

    def snapshot(self) -> dict:
        return {"mode": self.mode, "base_ms": self.base_ms, "jitter_ms": self.jitter_ms}


class ActionDispatcher:
    def __init__(
        self,
        *,
        bus: Bus,
        http: httpx.AsyncClient,
        telemetry: ActionTelemetry,
        actuators_url: str,
        slice_control_url: str,
        timeout_seconds: float,
        max_concurrent_plans: int = 5,
        network: NetworkMode | None = None,
    ) -> None:
        self._bus = bus
        self._http = http
        self._telemetry = telemetry
        self._actuators_url = actuators_url.rstrip("/")
        self._slice_control_url = slice_control_url.rstrip("/")
        self._timeout = timeout_seconds
        self._sem = asyncio.Semaphore(max_concurrent_plans)
        self.network = network or NetworkMode()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._inflight: set[asyncio.Task] = set()
        self.active = False
        self.processed_total = 0
        self.last_trigger_id: str | None = None

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="action-dispatcher")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=3.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        if self._inflight:
            await asyncio.gather(*self._inflight, return_exceptions=True)

    async def _run(self) -> None:
        self.active = True
        logger.info("action dispatcher running")
        try:
            async for stream, _id, fields in self._bus.consume_streams(
                [PLAN_STREAM], block_ms=200
            ):
                if self._stop.is_set():
                    break
                if not stream or not fields:
                    continue
                plan = self._parse_plan(fields)
                if plan is None:
                    continue
                task = asyncio.create_task(
                    self._dispatch_plan(plan),
                    name=f"action:plan:{plan.trigger_id}",
                )
                self._inflight.add(task)
                task.add_done_callback(self._inflight.discard)
        finally:
            self.active = False

    def _parse_plan(self, fields: dict[bytes, bytes]) -> ActionPlan | None:
        raw = fields.get(b"data")
        if raw is None:
            return None
        try:
            return ActionPlan.model_validate_json(raw)
        except ValidationError as exc:
            logger.warning("action: malformed ActionPlan on bus: {}", exc)
            return None

    async def dispatch_plan(self, plan: ActionPlan) -> list[ActionOutcome]:
        """Public entry — used by both the consumer loop and unit tests."""
        return await self._dispatch_plan(plan)

    async def _dispatch_plan(self, plan: ActionPlan) -> list[ActionOutcome]:
        async with self._sem:
            self._telemetry.in_flight.inc()
            self._telemetry.plans_total.inc()
            plan_start = time.monotonic()
            ctx = HandlerContext(
                http=self._http,
                bus=self._bus,
                actuators_url=self._actuators_url,
                slice_control_url=self._slice_control_url,
                timeout_seconds=self._timeout,
                plan=plan,
            )
            try:
                outcomes = await asyncio.gather(
                    *(self._run_one(ctx, inv) for inv in plan.actions),
                    return_exceptions=False,
                )
            finally:
                plan_elapsed = time.monotonic() - plan_start
                self._telemetry.plan_latency.observe(plan_elapsed)
                self._telemetry.in_flight.dec()

            # Emit audit + per-action metrics after all dispatches return so
            # the parallel section is purely IO-bound and tight.
            for outcome in outcomes:
                self._telemetry.action_latency.labels(
                    action_id=outcome.invocation.action_id,
                    effect=outcome.effect.value,
                ).observe(outcome.latency_ms / 1000.0)
                self._telemetry.actions_total.labels(
                    action_id=outcome.invocation.action_id,
                    effect=outcome.effect.value,
                ).inc()
                await self._write_audit(plan, outcome)

            self.processed_total += 1
            self.last_trigger_id = plan.trigger_id
            success_count = sum(1 for o in outcomes if o.effect is ActionEffect.SUCCESS)
            logger.info(
                "action plan dispatched trigger={} actions={} success={}/{} elapsed={:.1f}ms",
                plan.trigger_id,
                [o.invocation.action_id for o in outcomes],
                success_count, len(outcomes),
                plan_elapsed * 1000.0,
            )
            return outcomes

    async def _run_one(
        self, ctx: HandlerContext, inv: ActionInvocation
    ) -> ActionOutcome:
        handler = HANDLERS.get(inv.action_id)
        if handler is None:
            # Layer D's parser should have rejected this; defensive guard.
            logger.warning(
                "action: no handler for action_id='{}' (trigger={})",
                inv.action_id, ctx.plan.trigger_id,
            )
            return ActionOutcome(
                invocation=inv,
                effect=ActionEffect.FAILURE,
                latency_ms=0.0,
                detail=f"no handler for action_id={inv.action_id}",
            )
        await self.network.apply()    # simulates Wi-Fi contention when enabled
        try:
            return await handler(ctx, inv)
        except Exception as exc:    # noqa: BLE001 — handlers must never escape
            logger.exception(
                "action handler crashed action={} trigger={}: {}",
                inv.action_id, ctx.plan.trigger_id, exc,
            )
            return ActionOutcome(
                invocation=inv,
                effect=ActionEffect.FAILURE,
                latency_ms=0.0,
                detail=f"handler crashed: {type(exc).__name__}: {exc}",
            )

    async def _write_audit(self, plan: ActionPlan, outcome: ActionOutcome) -> None:
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            severity=plan.severity,
            layer_d_trace=(
                plan.audit_metadata.get("layer_d_trace")
                or plan.rationale
                or "(no trace)"
            ),
            action_id=outcome.invocation.action_id,
            effect=outcome.effect,
            agent_confidence=plan.confidence,
            trigger_id=plan.trigger_id,
            parameters=outcome.invocation.parameters,
            latency_ms=outcome.latency_ms,
        )
        await self._bus.publish_audit(entry.model_dump(mode="json"))


__all__ = ["ActionDispatcher"]
