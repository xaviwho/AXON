"""VLM client wrappers.

Two interchangeable backends behind the same `VLMClient.generate_scene(...)`
interface:

  `vllm`  — production. POSTs an OpenAI-compatible chat-completion request
            to a vLLM-served Qwen2-VL-7B-Instruct-AWQ endpoint, attaching
            keyframes as base64 data URLs.
  `stub`  — development. Deterministic heuristic from trigger_reason +
            sensor context; never calls a model and never reads image
            content (which is exactly what makes it safe to ship in
            CI / on a 4 GB GPU dev box).

Both return a validated `SceneDescription`. Switch via `AXON_VLM_MODE`.
"""

from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger

from shared.schemas.scene import (
    EquipmentState,
    HazardObservation,
    PersonObservation,
    SceneDescription,
)

from .prompts import (
    SYSTEM_PROMPT,
    render_correction_prompt,
    render_user_prompt,
    summarize_sensors,
)
from .scene_parser import SceneParseError, fallback_scene, parse_scene


@dataclass
class GenerationRequest:
    trigger_id: str
    trigger_reason: str
    sensor_refs: dict[str, dict[str, Any]]
    frames: list[tuple[str, str, bytes]]    # (camera_id, entry_id, jpeg_bytes)
    location_hint: str = "unknown"


class VLMClient(ABC):
    @property
    @abstractmethod
    def mode(self) -> str: ...

    @abstractmethod
    async def generate_scene(self, req: GenerationRequest) -> SceneDescription: ...


# ---- stub -------------------------------------------------------------------


_HAZARD_BY_RULE: dict[str, tuple[str, str]] = {
    "fire_smoke_vision": ("fire", "high"),
    "thermal_threshold": ("fire", "high"),
    "gas_threshold":     ("gas_leak", "high"),
    "ppe_with_equipment": ("ppe_violation", "medium"),
}


class StubVLMClient(VLMClient):
    """Deterministic, image-blind scene synthesizer driven by trigger_reason."""

    mode = "stub"

    async def generate_scene(self, req: GenerationRequest) -> SceneDescription:
        rules = [r for r in req.trigger_reason.split("|") if r]
        hazards: list[HazardObservation] = []
        people: list[PersonObservation] = []
        equipment: list[EquipmentState] = []

        for rule in rules:
            hazard_match = _HAZARD_BY_RULE.get(rule)
            if hazard_match is not None:
                hazards.append(
                    HazardObservation(
                        hazard_type=hazard_match[0],
                        severity=hazard_match[1],
                        location=req.location_hint,
                        notes=f"derived from rule {rule}",
                    )
                )
            if rule == "person_prone_persistent":
                people.append(
                    PersonObservation(person_id="p-stub-0", posture="prone", location=req.location_hint)
                )

        ctx: dict[str, Any] = {
            "stub": True,
            "trigger_reason": req.trigger_reason,
            "frames_available": len(req.frames),
        }
        for sid, reading in req.sensor_refs.items():
            ctx[f"sensor:{sid}"] = f"{reading.get('value', '?')}{reading.get('unit', '')}"

        return SceneDescription(
            people_present=people,
            hazards=hazards,
            equipment_state=equipment,
            location=req.location_hint,
            contextual_factors=ctx,
            trigger_id=req.trigger_id,
            timestamp=datetime.now(timezone.utc),
        )


# ---- real vLLM backend ------------------------------------------------------


class VLLMOpenAIClient(VLMClient):
    """Calls a vLLM-served VL model via OpenAI-compatible /v1/chat/completions.

    Image bytes ride as base64 data URLs. Output text is then parsed
    through scene_parser; on validation failure we retry once with a
    correction prompt, then fall back per fail-safe policy.
    """

    mode = "vllm"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float,
        temperature: float,
        max_parse_retries: int,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout_seconds
        self._temperature = temperature
        self._max_retries = max_parse_retries

    async def generate_scene(self, req: GenerationRequest) -> SceneDescription:
        sensor_summary = summarize_sensors(req.sensor_refs)
        user_prompt = render_user_prompt(
            trigger_reason=req.trigger_reason,
            sensor_summary=sensor_summary,
        )
        messages = self._messages(SYSTEM_PROMPT, user_prompt, req.frames)
        last_err: str | None = None

        async with httpx.AsyncClient(timeout=self._timeout) as http:
            for attempt in range(self._max_retries + 1):
                try:
                    text = await self._chat(http, messages)
                except httpx.HTTPError as exc:
                    logger.warning("vlm http error on trigger {}: {}", req.trigger_id, exc)
                    return fallback_scene(
                        trigger_id=req.trigger_id,
                        trigger_reason=req.trigger_reason,
                        location=req.location_hint,
                        note=f"vlm http error: {exc}",
                    )

                try:
                    return parse_scene(
                        text,
                        trigger_id=req.trigger_id,
                        location_default=req.location_hint,
                    )
                except SceneParseError as exc:
                    last_err = str(exc)
                    logger.warning(
                        "vlm parse failure attempt={} trigger={}: {}",
                        attempt, req.trigger_id, last_err,
                    )
                    if attempt < self._max_retries:
                        messages = self._messages(
                            SYSTEM_PROMPT,
                            render_correction_prompt(last_err),
                            req.frames,
                        )

        return fallback_scene(
            trigger_id=req.trigger_id,
            trigger_reason=req.trigger_reason,
            location=req.location_hint,
            note=f"vlm output failed validation after {self._max_retries + 1} attempts: {last_err}",
        )

    def _messages(
        self,
        system: str,
        user: str,
        frames: list[tuple[str, str, bytes]],
    ) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": user}]
        for _cam, _entry, data in frames:
            b64 = base64.b64encode(data).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                }
            )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ]

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


def make_client(*, mode: str, **kwargs: Any) -> VLMClient:
    if mode == "stub":
        return StubVLMClient()
    if mode == "vllm":
        return VLLMOpenAIClient(**kwargs)
    raise ValueError(f"unknown AXON_VLM_MODE: {mode!r}; expected 'stub' or 'vllm'")


__all__ = [
    "GenerationRequest",
    "StubVLMClient",
    "VLMClient",
    "VLLMOpenAIClient",
    "make_client",
]
