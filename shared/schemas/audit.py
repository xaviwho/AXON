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
    # phase=1: Pi_g gated protocol dispatched on anomaly arrival (F(beta)).
    # phase=2: Pi_d refined-plan supersedence (delta over the phase-1 set).
    # Direct dispatch_plan() calls (no prior anomaly) also stamp phase=1.
    phase: int = Field(default=1, ge=1, le=2)
    # HMAC-SHA256 hex signature computed by the dispatcher at publish time
    # over the canonical form of the entry (see shared/audit_signing.py).
    # Persisters verify this on ingest and mark tampered rows accordingly.
    signature: str | None = Field(default=None, min_length=64, max_length=64)
