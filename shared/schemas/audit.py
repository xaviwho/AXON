from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .enums import ActionEffect


class AuditEntry(BaseModel):
    timestamp: datetime
    severity: int = Field(ge=0, le=5)
    layer_d_trace: str = Field(min_length=1, description="Full reasoning trace from Layer D")
    action_id: str = Field(min_length=1)
    effect: ActionEffect
    agent_confidence: float = Field(ge=0.0, le=1.0)
    trigger_id: str | None = None
    parameters: dict[str, Any] | None = None
    latency_ms: float | None = Field(default=None, ge=0.0)
