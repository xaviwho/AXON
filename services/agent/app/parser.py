"""Robust ActionPlan parser with bounded-action-library enforcement.

The model output passes through two validation gates:
  1. ActionPlan Pydantic schema (top-level structure + types)
  2. `ActionLibrary.validate(...)` for every contained ActionInvocation
     (action_id present in the library; parameters match the per-action
     JSON Schema; no `additionalProperties`)

Either gate's failure raises `PlanParseError`, which the caller converts
into a single correction-prompt retry per Prompt 6.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from pydantic import ValidationError

from shared.action_library import (
    ActionLibrary,
    ActionParameterError,
    UnknownActionError,
)
from shared.schemas.actions import ActionInvocation, ActionPlan

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class PlanParseError(ValueError):
    """Raised when a model response can't be coerced into a valid, library-bound ActionPlan."""


def _extract_json_blob(text: str) -> str:
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    stripped = text.lstrip()
    if not stripped:
        raise PlanParseError("empty response")
    if stripped[0] != "{":
        if stripped[0] == "[":
            raise PlanParseError("top-level JSON is an array, expected object")
        # else: leading prose — fall through
    start = text.find("{")
    if start == -1:
        raise PlanParseError("no JSON object found in response")
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
    raise PlanParseError("unbalanced braces — no JSON object found")


def parse_plan(
    raw: str,
    *,
    library: ActionLibrary,
    trigger_id: str,
) -> ActionPlan:
    """Strict parse + library binding. Raises `PlanParseError` on any failure."""
    try:
        blob = _extract_json_blob(raw)
    except PlanParseError:
        raise
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise PlanParseError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanParseError(f"top-level JSON must be an object, got {type(data).__name__}")

    # Backfill identity / time fields if the model omitted them — these are
    # known from outside the model and must not be invented by it.
    data.setdefault("trigger_id", trigger_id)
    data.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    data.setdefault("audit_metadata", {})
    data["audit_metadata"].setdefault("layer_d_trace", data.get("rationale", ""))

    try:
        plan = ActionPlan(**data)
    except ValidationError as exc:
        raise PlanParseError(f"ActionPlan schema validation failed: {exc}") from exc

    # Second gate: every action_id + parameters set must be in the library.
    errors: list[str] = []
    for inv in plan.actions:
        try:
            library.validate(inv)
        except (UnknownActionError, ActionParameterError) as exc:
            errors.append(str(exc))
    if errors:
        raise PlanParseError(
            "action library violations:\n  - " + "\n  - ".join(errors)
        )

    return plan


__all__ = ["PlanParseError", "parse_plan"]
