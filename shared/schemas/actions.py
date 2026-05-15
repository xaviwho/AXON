from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ActionInvocation(BaseModel):
    # action_id must reference an entry in shared/action_library/library.json.
    # Library validation is performed by shared.action_library.wrappers.ActionLibrary
    # at dispatch time, not inside this model — the model is intentionally
    # transport-friendly.
    action_id: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    requested_latency_ms: int = Field(gt=0)


class ActionPlan(BaseModel):
    severity: int = Field(ge=0, le=5)
    actions: list[ActionInvocation]
    rationale: str = Field(min_length=1)
    notification_targets: list[str] = Field(default_factory=list)
    audit_metadata: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    trigger_id: str = Field(min_length=1)
    timestamp: datetime
