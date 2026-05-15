from datetime import datetime

from pydantic import BaseModel, Field


class ContributingSignal(BaseModel):
    source: str = Field(min_length=1, description="e.g. 'vision:fire', 'sensor:gas', 'pose:prone'")
    weight: float = Field(ge=0.0)
    description: str | None = None


class AnomalyScore(BaseModel):
    composite_score: float = Field(ge=0.0, le=1.0)
    contributing_signals: list[ContributingSignal] = Field(default_factory=list)
    threshold_exceeded: bool
    trigger_reason: str = Field(min_length=1)
    trigger_id: str = Field(min_length=1)
    timestamp: datetime
