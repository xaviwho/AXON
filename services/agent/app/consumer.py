"""SceneDescription → ActionPlan consumer for Layer D.

Subscribes to `axon:scenes`. For each SceneDescription:
  1. Fetch trigger_reason from the cached trigger context (or fall back
     to `contextual_factors.trigger_reason` if the cache expired).
  2. Retrieve relevant knowledge-base sections via RAG.
  3. Hand off to LLMClient (stub or vLLM-backed) under a semaphore cap.
  4. Publish the resulting ActionPlan to `axon:plans`.

The audit trace lives in `ActionPlan.audit_metadata.layer_d_trace`; the
dispatcher (Prompt 7) reads it when writing per-action AuditEntries.
"""

from __future__ import annotations

import asyncio
import time

from loguru import logger
from pydantic import ValidationError

from shared.bus import SCENE_STREAM, Bus
from shared.schemas.scene import SceneDescription

from .client import LLMClient, PlanRequest
from .fallback import build_fallback_plan
from .rag import KnowledgeBase
from .telemetry import AgentTelemetry


class PlanConsumer:
    def __init__(
        self,
        *,
        bus: Bus,
        client: LLMClient,
        knowledge_base: KnowledgeBase,
        library,    # ActionLibrary; loosely typed to avoid a circular import
        telemetry: AgentTelemetry,
        max_concurrent: int = 5,
        rag_max_sections: int = 6,
    ) -> None:
        self._bus = bus
        self._client = client
        self._kb = knowledge_base
        self._library = library
        self._telemetry = telemetry
        self._sem = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._rag_max_sections = rag_max_sections
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._inflight: set[asyncio.Task] = set()
        self.active = False
        self.processed_total = 0
        self.last_trigger_id: str | None = None

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="agent-consumer")

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
        logger.info(
            "agent consumer running: mode={} kb_sections={} max_concurrent={}",
            self._client.mode, len(self._kb), self._max_concurrent,
        )
        try:
            async for stream, _id, fields in self._bus.consume_streams(
                [SCENE_STREAM], block_ms=200
            ):
                if self._stop.is_set():
                    break
                if not stream or not fields:
                    continue
                scene = self._parse_scene(fields)
                if scene is None:
                    continue
                task = asyncio.create_task(
                    self._handle(scene),
                    name=f"agent:scene:{scene.trigger_id}",
                )
                self._inflight.add(task)
                task.add_done_callback(self._inflight.discard)
        finally:
            self.active = False

    def _parse_scene(self, fields: dict[bytes, bytes]) -> SceneDescription | None:
        raw = fields.get(b"data")
        if raw is None:
            return None
        try:
            return SceneDescription.model_validate_json(raw)
        except ValidationError as exc:
            logger.warning("agent: malformed SceneDescription: {}", exc)
            return None

    async def _handle(self, scene: SceneDescription) -> None:
        async with self._sem:
            self._telemetry.in_flight.inc()
            start = time.monotonic()
            outcome = "ok"
            try:
                trigger_reason = await self._resolve_trigger_reason(scene)
                rag_context = self._render_rag(scene, trigger_reason)
                req = PlanRequest(
                    scene=scene,
                    trigger_reason=trigger_reason,
                    rag_context=rag_context,
                )
                try:
                    plan = await self._client.generate_plan(req)
                except Exception as exc:    # noqa: BLE001
                    logger.exception("agent client error on {}: {}", scene.trigger_id, exc)
                    plan = build_fallback_plan(
                        scene=scene,
                        trigger_reason=trigger_reason,
                        library=self._library,
                        reason_note=f"agent client error: {type(exc).__name__}",
                    )
                    outcome = "client_error"

                if plan.audit_metadata.get("fallback"):
                    outcome = "fallback"
                    self._telemetry.fallbacks_total.labels(
                        reason=plan.audit_metadata.get("trigger_reason") or "unknown"
                    ).inc()

                await self._bus.publish_plan(plan.model_dump(mode="json"))
                self.processed_total += 1
                self.last_trigger_id = scene.trigger_id
                logger.info(
                    "agent plan published trigger={} outcome={} severity={} actions={} confidence={:.2f}",
                    scene.trigger_id, outcome, plan.severity,
                    [a.action_id for a in plan.actions], plan.confidence,
                )
            finally:
                elapsed = time.monotonic() - start
                self._telemetry.in_flight.dec()
                self._telemetry.plan_latency.labels(
                    mode=self._client.mode, outcome=outcome
                ).observe(elapsed)
                self._telemetry.plans_total.labels(
                    mode=self._client.mode, outcome=outcome
                ).inc()

    async def _resolve_trigger_reason(self, scene: SceneDescription) -> str:
        ctx = await self._bus.fetch_trigger_context(scene.trigger_id) or {}
        if ctx.get("trigger_reason"):
            return str(ctx["trigger_reason"])
        ctx_factors = scene.contextual_factors or {}
        return str(ctx_factors.get("trigger_reason") or "unknown")

    def _render_rag(self, scene: SceneDescription, trigger_reason: str) -> str:
        terms: list[str] = [scene.location, trigger_reason]
        terms += [h.hazard_type for h in scene.hazards]
        terms += [p.posture for p in scene.people_present]
        terms += [e.state for e in scene.equipment_state]
        sections = self._kb.retrieve(terms, limit=self._rag_max_sections)
        return "\n\n".join(str(s) for s in sections)


__all__ = ["PlanConsumer"]
