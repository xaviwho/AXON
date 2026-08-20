"""ActionPlan dispatcher — two-phase Pi_g / Pi_d split.

Subscribes to two streams:

  axon:anomalies (Phase 1, gated path Pi_g):
    An AnomalyScore is the trigger. The dispatcher immediately synthesizes
    the protocol plan F(beta) via `shared.protocols.build_protocol` and
    dispatches it. This is the actuation-critical path — it does not wait
    for the deliberative stage (VLM + agent).

  axon:plans (Phase 2, deliberative supersedence Pi_d):
    The agent's refined ActionPlan arrives on the same trigger_id later.
    The dispatcher computes the delta against Phase-1's dispatched action
    set (by canonical (action_id, parameters) key) and fires only the
    delta as Phase 2, so each physical action is invoked at most once and
    each audit record carries the phase that produced it.

If a plan arrives without a prior anomaly on the same trigger (direct
`dispatch_plan()` calls, or an out-of-order run), the full plan is
dispatched as Phase 1 — preserves prior single-consumer behavior.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections import OrderedDict
from datetime import datetime, timezone

import httpx
from loguru import logger
from pydantic import ValidationError

from shared.action_library import ActionLibrary
from shared.audit_signing import sign_entry
from shared.bus import ANOMALY_STREAM, PLAN_STREAM, Bus
from shared.protocols import build_protocol
from shared.schemas.actions import ActionInvocation, ActionPlan
from shared.schemas.anomaly import AnomalyScore
from shared.schemas.audit import AuditEntry
from shared.schemas.enums import ActionEffect

from .handlers import HANDLERS, ActionOutcome, HandlerContext
from .telemetry import ActionTelemetry

# Cap on how many trigger_ids we remember Phase-1 dispatch sets for. Under
# the production 10 s emission cooldown a run of 256 recent triggers covers
# ~40 min of continuous activation, well above any plausible Phase-1 to
# Phase-2 gap.
_TRIGGER_CACHE_MAX = 256


def _canonical_key(inv: ActionInvocation) -> str:
    """Stable dedupe key: identical action_id + parameters → identical key."""
    return f"{inv.action_id}:{json.dumps(inv.parameters, sort_keys=True, default=str)}"


class NetworkMode:
    """Per-call network-condition simulator for the Wi-Fi vs URLLC comparison demo.

    `urllc` (default) is a no-op. `wifi` injects `base_ms + U(0, jitter_ms)`
    of artificial delay before each action handler runs, so the dispatcher's
    measured per-action latency includes the simulated contention.
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
        library: ActionLibrary,
        actuators_url: str,
        slice_control_url: str,
        timeout_seconds: float,
        max_concurrent_plans: int = 5,
        network: NetworkMode | None = None,
    ) -> None:
        self._bus = bus
        self._http = http
        self._telemetry = telemetry
        self._library = library
        self._actuators_url = actuators_url.rstrip("/")
        self._slice_control_url = slice_control_url.rstrip("/")
        self._timeout = timeout_seconds
        self._sem = asyncio.Semaphore(max_concurrent_plans)
        self.network = network or NetworkMode()
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        self._inflight: set[asyncio.Task] = set()
        # trigger_id -> set of canonical action keys dispatched in Phase 1
        self._phase1_by_trigger: OrderedDict[str, set[str]] = OrderedDict()
        self.active = False
        self.processed_total = 0
        self.phase1_total = 0
        self.phase2_total = 0
        self.last_trigger_id: str | None = None

    async def start(self) -> None:
        self._stop.clear()
        self._tasks = [
            asyncio.create_task(self._run_anomalies(), name="action-anomaly-consumer"),
            asyncio.create_task(self._run_plans(), name="action-plan-consumer"),
        ]

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            try:
                await asyncio.wait_for(task, timeout=3.0)
            except asyncio.TimeoutError:
                task.cancel()
        if self._inflight:
            await asyncio.gather(*self._inflight, return_exceptions=True)

    # ---- Phase 1: anomaly → immediate protocol dispatch ---------------------

    async def _run_anomalies(self) -> None:
        self.active = True
        logger.info("action anomaly consumer running (Phase 1 / Pi_g)")
        try:
            async for stream, _id, fields in self._bus.consume_streams(
                [ANOMALY_STREAM], block_ms=200
            ):
                if self._stop.is_set():
                    break
                if not stream or not fields:
                    continue
                anomaly = self._parse_anomaly(fields)
                if anomaly is None:
                    continue
                task = asyncio.create_task(
                    self._dispatch_phase1(anomaly),
                    name=f"action:phase1:{anomaly.trigger_id}",
                )
                self._inflight.add(task)
                task.add_done_callback(self._inflight.discard)
        finally:
            self.active = False

    def _parse_anomaly(self, fields: dict[bytes, bytes]) -> AnomalyScore | None:
        raw = fields.get(b"data")
        if raw is None:
            return None
        try:
            return AnomalyScore.model_validate_json(raw)
        except ValidationError as exc:
            logger.warning("action: malformed AnomalyScore on bus: {}", exc)
            return None

    async def _dispatch_phase1(self, anomaly: AnomalyScore) -> None:
        if not anomaly.threshold_exceeded:
            return
        plan = build_protocol(
            trigger_id=anomaly.trigger_id,
            trigger_reason=anomaly.trigger_reason,
            library=self._library,
            zone="unknown",
            reason_note="phase-1 gated protocol",
            timestamp=anomaly.timestamp,
        )
        keys = {_canonical_key(a) for a in plan.actions}
        self._remember_phase1(anomaly.trigger_id, keys)
        self.phase1_total += 1
        await self._dispatch_actions(plan, plan.actions, phase=1)

    def _remember_phase1(self, trigger_id: str, keys: set[str]) -> None:
        self._phase1_by_trigger[trigger_id] = keys
        self._phase1_by_trigger.move_to_end(trigger_id)
        while len(self._phase1_by_trigger) > _TRIGGER_CACHE_MAX:
            self._phase1_by_trigger.popitem(last=False)

    # ---- Phase 2: refined-plan supersedence ---------------------------------

    async def _run_plans(self) -> None:
        logger.info("action plan consumer running (Phase 2 / Pi_d supersedence)")
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
                self._dispatch_phase2(plan),
                name=f"action:phase2:{plan.trigger_id}",
            )
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

    def _parse_plan(self, fields: dict[bytes, bytes]) -> ActionPlan | None:
        raw = fields.get(b"data")
        if raw is None:
            return None
        try:
            return ActionPlan.model_validate_json(raw)
        except ValidationError as exc:
            logger.warning("action: malformed ActionPlan on bus: {}", exc)
            return None

    async def _dispatch_phase2(self, plan: ActionPlan) -> None:
        prior = self._phase1_by_trigger.get(plan.trigger_id)
        if prior is None:
            # No Phase 1 fired for this trigger — treat as a standalone
            # dispatch so lone-plan callers keep working.
            await self._dispatch_actions(plan, plan.actions, phase=1)
            return
        delta = [a for a in plan.actions if _canonical_key(a) not in prior]
        if not delta:
            logger.info(
                "action plan supersedence: trigger={} refined plan is subset of Phase 1 — nothing to dispatch",
                plan.trigger_id,
            )
            return
        self.phase2_total += 1
        await self._dispatch_actions(plan, delta, phase=2)

    # ---- public entry point used by tests -----------------------------------

    async def dispatch_plan(self, plan: ActionPlan) -> list[ActionOutcome]:
        """Dispatch every action in `plan` as Phase 1 (no anomaly precedence)."""
        return await self._dispatch_actions(plan, plan.actions, phase=1)

    # ---- shared dispatch core ----------------------------------------------

    async def _dispatch_actions(
        self, plan: ActionPlan, actions: list[ActionInvocation], *, phase: int
    ) -> list[ActionOutcome]:
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
                    *(self._run_one(ctx, inv) for inv in actions),
                    return_exceptions=False,
                )
            finally:
                plan_elapsed = time.monotonic() - plan_start
                self._telemetry.plan_latency.observe(plan_elapsed)
                self._telemetry.in_flight.dec()

            for outcome in outcomes:
                self._telemetry.action_latency.labels(
                    action_id=outcome.invocation.action_id,
                    effect=outcome.effect.value,
                ).observe(outcome.latency_ms / 1000.0)
                self._telemetry.actions_total.labels(
                    action_id=outcome.invocation.action_id,
                    effect=outcome.effect.value,
                ).inc()
                await self._write_audit(plan, outcome, phase=phase)

            self.processed_total += 1
            self.last_trigger_id = plan.trigger_id
            success_count = sum(1 for o in outcomes if o.effect is ActionEffect.SUCCESS)
            logger.info(
                "action dispatch trigger={} phase={} actions={} success={}/{} elapsed={:.1f}ms",
                plan.trigger_id, phase,
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
        await self.network.apply()
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

    async def _write_audit(
        self, plan: ActionPlan, outcome: ActionOutcome, *, phase: int
    ) -> None:
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
            phase=phase,
        )
        payload = entry.model_dump(mode="json")
        payload["signature"] = sign_entry(payload)
        await self._bus.publish_audit(payload)


__all__ = ["ActionDispatcher", "NetworkMode"]
