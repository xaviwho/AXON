"""LLM client wrappers for Layer D.

Same two-backend pattern as Layer C:

  `stub`  — deterministic, calls `fallback.build_fallback_plan(...)` to
            return a protocol-compliant ActionPlan with confidence 1.0.
            What runs on the dev box and in CI; what the real LLM
            mirrors during demos.
  `vllm`  — production. POSTs an OpenAI-compatible chat-completion
            request to a vLLM-served Llama 3.1-8B-Instruct (or Qwen
            2.5-7B-Instruct) endpoint. Output is parsed + library-
            validated by `parser.parse_plan`. One correction-prompt
            retry on validation failure; final fall-back via
            `fallback.build_fallback_plan` per CLAUDE.md fail-safe.

Both return a fully-validated `ActionPlan`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger

from shared.action_library import ActionLibrary
from shared.schemas.actions import ActionPlan
from shared.schemas.scene import SceneDescription

from .fallback import build_fallback_plan
from .parser import PlanParseError, parse_plan
from .prompts import (
    SYSTEM_PROMPT,
    render_correction_prompt,
    render_user_prompt,
)


@dataclass
class PlanRequest:
    scene: SceneDescription
    trigger_reason: str
    rag_context: str


class LLMClient(ABC):
    @property
    @abstractmethod
    def mode(self) -> str: ...

    @abstractmethod
    async def generate_plan(self, req: PlanRequest) -> ActionPlan: ...


# ---- stub -------------------------------------------------------------------


class StubLLMClient(LLMClient):
    """Deterministic protocol-driven planner — ignores model entirely."""

    mode = "stub"

    def __init__(self, library: ActionLibrary) -> None:
        self._library = library

    async def generate_plan(self, req: PlanRequest) -> ActionPlan:
        return build_fallback_plan(
            scene=req.scene,
            trigger_reason=req.trigger_reason,
            library=self._library,
            reason_note="stub-rule protocol",
        )


# ---- production vLLM-backed client -----------------------------------------


class VLLMOpenAIClient(LLMClient):
    """Calls a vLLM-served LLM via OpenAI-compatible /v1/chat/completions.

    Validation pipeline matches Prompt 6's safety constraints:
      - top-level ActionPlan schema (Pydantic)
      - per-action ActionLibrary.validate(...)
      - on failure: one retry with a correction prompt
      - final failure OR confidence < floor → fallback safety protocol
    """

    mode = "vllm"

    def __init__(
        self,
        library: ActionLibrary,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float,
        temperature: float,
        max_parse_retries: int,
        confidence_floor: float,
    ) -> None:
        self._library = library
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout_seconds
        self._temperature = temperature
        self._max_retries = max_parse_retries
        self._confidence_floor = confidence_floor

    async def generate_plan(self, req: PlanRequest) -> ActionPlan:
        user_prompt = render_user_prompt(
            scene_json=req.scene.model_dump(mode="json"),
            trigger_reason=req.trigger_reason,
            rag_context=req.rag_context,
            library=self._library,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        last_err: str | None = None
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            for attempt in range(self._max_retries + 1):
                try:
                    text = await self._chat(http, messages)
                except httpx.HTTPError as exc:
                    logger.warning("agent http error on {}: {}", req.scene.trigger_id, exc)
                    return build_fallback_plan(
                        scene=req.scene,
                        trigger_reason=req.trigger_reason,
                        library=self._library,
                        reason_note=f"vlm http error: {exc}",
                    )
                try:
                    plan = parse_plan(
                        text, library=self._library, trigger_id=req.scene.trigger_id
                    )
                except PlanParseError as exc:
                    last_err = str(exc)
                    logger.warning(
                        "agent parse failure attempt={} trigger={}: {}",
                        attempt, req.scene.trigger_id, last_err,
                    )
                    if attempt < self._max_retries:
                        messages = [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": render_correction_prompt(
                                    last_err, self._library
                                ),
                            },
                        ]
                    continue

                if plan.confidence < self._confidence_floor:
                    logger.info(
                        "agent fallback (low confidence) trigger={} conf={}",
                        req.scene.trigger_id, plan.confidence,
                    )
                    return build_fallback_plan(
                        scene=req.scene,
                        trigger_reason=req.trigger_reason,
                        library=self._library,
                        reason_note=(
                            f"agent confidence {plan.confidence:.2f} < "
                            f"{self._confidence_floor} → fallback"
                        ),
                    )
                return plan

        return build_fallback_plan(
            scene=req.scene,
            trigger_reason=req.trigger_reason,
            library=self._library,
            reason_note=(
                f"vlm output failed validation after "
                f"{self._max_retries + 1} attempts: {last_err}"
            ),
        )

    async def _chat(self, http: httpx.AsyncClient, messages: list[dict[str, Any]]) -> str:
        body = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "response_format": {"type": "json_object"},
        }
        r = await http.post(
            f"{self._base_url}/chat/completions", json=body, headers=self._headers
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


# ---- factory ----------------------------------------------------------------


def make_client(*, mode: str, library: ActionLibrary, **kwargs: Any) -> LLMClient:
    if mode == "stub":
        return StubLLMClient(library)
    if mode == "vllm":
        return VLLMOpenAIClient(library, **kwargs)
    raise ValueError(f"unknown AXON_LLM_MODE: {mode!r}; expected 'stub' or 'vllm'")


__all__ = [
    "LLMClient",
    "PlanRequest",
    "StubLLMClient",
    "VLLMOpenAIClient",
    "make_client",
]
