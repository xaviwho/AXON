"""Validator for ActionInvocations against the bounded action library.

Layer D's reasoning output is parsed into an `ActionInvocation` (transport
schema). Before the action dispatcher executes it, the invocation MUST pass
`ActionLibrary.validate(...)`. Validation is intentionally strict:

- An unknown `action_id` raises `UnknownActionError` (Layer D hallucinated
  an action not in the bounded library).
- Parameters that do not match the per-action JSON Schema raise
  `ActionParameterError`.

Both errors carry human-readable messages suitable for the agent's
correction-retry prompt path described in Prompt 6.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from shared.schemas.actions import ActionInvocation
from shared.schemas.enums import LatencyClass, PermissionLevel

LIBRARY_PATH = Path(__file__).with_name("library.json")


class ActionDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parameters_schema: dict[str, Any]
    latency_class: LatencyClass
    permission_level: PermissionLevel
    audit_requirements: list[str] = Field(default_factory=list)


class UnknownActionError(ValueError):
    """Raised when an ActionInvocation references an action_id not in the library."""


class ActionParameterError(ValueError):
    """Raised when an ActionInvocation's parameters fail per-action JSON Schema validation."""


@dataclass(frozen=True)
class _LoadedAction:
    definition: ActionDefinition
    validator: Draft202012Validator


class ActionLibrary:
    """In-memory view of the bounded action library, loaded once at process start."""

    def __init__(self, actions: dict[str, ActionDefinition]) -> None:
        self._entries: dict[str, _LoadedAction] = {
            name: _LoadedAction(
                definition=defn,
                validator=Draft202012Validator(defn.parameters_schema),
            )
            for name, defn in actions.items()
        }

    @classmethod
    def load(cls, path: Path | None = None) -> ActionLibrary:
        path = path or LIBRARY_PATH
        raw = json.loads(path.read_text(encoding="utf-8"))
        actions = {
            name: ActionDefinition(**defn) for name, defn in raw["actions"].items()
        }
        return cls(actions)

    def __contains__(self, action_id: str) -> bool:
        return action_id in self._entries

    def __getitem__(self, action_id: str) -> ActionDefinition:
        return self._entries[action_id].definition

    def __iter__(self) -> Iterator[ActionDefinition]:
        return (e.definition for e in self._entries.values())

    def names(self) -> list[str]:
        return list(self._entries)

    def validate(self, invocation: ActionInvocation) -> None:
        """Raise UnknownActionError or ActionParameterError if the invocation is not executable."""

        entry = self._entries.get(invocation.action_id)
        if entry is None:
            raise UnknownActionError(
                f"Action '{invocation.action_id}' is not in the bounded action library. "
                f"Known actions: {sorted(self._entries)}."
            )
        errors = list(entry.validator.iter_errors(invocation.parameters))
        if errors:
            details = "; ".join(
                f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
                for err in errors
            )
            raise ActionParameterError(
                f"Parameters for action '{invocation.action_id}' failed validation: {details}."
            )


__all__ = [
    "ActionDefinition",
    "ActionLibrary",
    "ActionParameterError",
    "LIBRARY_PATH",
    "UnknownActionError",
]
