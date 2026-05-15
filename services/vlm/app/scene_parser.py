"""Robust SceneDescription parser.

The model is allowed to be sloppy in surface form — wrapped JSON in
markdown fences, leading/trailing prose, adversarial text overlays that
the model attempted to obey — but its parsed output must validate
against the SceneDescription Pydantic schema or be rejected.

This is the second line of defense against prompt injection: even if the
model is fully compromised, anything it returns that isn't a valid
SceneDescription is discarded.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from loguru import logger
from pydantic import ValidationError

from shared.schemas.scene import SceneDescription

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class SceneParseError(ValueError):
    """Raised when a model response cannot be coerced into a SceneDescription."""


def _extract_json_blob(text: str) -> str:
    """Best-effort isolation of a JSON object from a (possibly noisy) model response."""
    # 1. ```json … ``` fences
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    # 2. If the first significant character is '[' or anything other than '{',
    #    the response is structurally wrong; refuse before searching deeper.
    stripped = text.lstrip()
    if not stripped:
        raise SceneParseError("empty response")
    if stripped[0] != "{":
        # Top-level must be an object; arrays / scalars / prose-only are
        # all spec violations. Don't quietly dig out a nested object.
        if stripped[0] == "[":
            raise SceneParseError("top-level JSON is an array, expected object")
        # else: leading prose — fall through to brace-finder for the
        # "free-form prefix + valid object" case.
    # 3. First {...} balanced object
    start = text.find("{")
    if start == -1:
        raise SceneParseError("no JSON object found in response")
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise SceneParseError("unbalanced braces — no JSON object found")


def parse_scene(
    raw: str, *, trigger_id: str, location_default: str = "unknown"
) -> SceneDescription:
    """Strict parse. Raises `SceneParseError` if the response isn't a valid SceneDescription."""
    try:
        blob = _extract_json_blob(raw)
    except SceneParseError:
        raise

    try:
        data = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise SceneParseError(f"invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise SceneParseError(f"top-level JSON must be an object, got {type(data).__name__}")

    # The model is allowed to omit trigger_id / location / timestamp —
    # we backfill from the live context so the validated message remains
    # internally consistent with the bus.
    data.setdefault("trigger_id", trigger_id)
    data.setdefault("location", location_default)
    data.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

    try:
        return SceneDescription(**data)
    except ValidationError as exc:
        raise SceneParseError(str(exc)) from exc


def fallback_scene(
    *, trigger_id: str, trigger_reason: str, location: str = "unknown", note: str = ""
) -> SceneDescription:
    """Last-resort SceneDescription used when the model produces unparseable output.

    Layer D still receives a structurally-valid message — the engine can
    proceed to a rule-based safety protocol per CLAUDE.md fail-safe rules.
    """
    return SceneDescription(
        people_present=[],
        hazards=[],
        equipment_state=[],
        location=location,
        contextual_factors={
            "fallback": True,
            "trigger_reason": trigger_reason,
            "note": note or "model output failed schema validation; using degraded scene",
        },
        trigger_id=trigger_id,
        timestamp=datetime.now(timezone.utc),
    )


__all__ = [
    "SceneParseError",
    "fallback_scene",
    "parse_scene",
]
