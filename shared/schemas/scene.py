from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PersonObservation(BaseModel):
    person_id: str = Field(min_length=1)
    posture: str = Field(min_length=1, description="standing | prone | fallen | seated | unknown")
    location: str | None = None
    ppe_compliant: bool | None = None


class HazardObservation(BaseModel):
    hazard_type: str = Field(min_length=1, description="fire | smoke | gas_leak | chemical_spill | ...")
    severity: str = Field(min_length=1, description="low | medium | high")
    location: str | None = None
    notes: str | None = None


class EquipmentState(BaseModel):
    equipment_id: str = Field(min_length=1)
    state: str = Field(min_length=1, description="in_use | idle | fault | offline")
    location: str | None = None


class SceneDescription(BaseModel):
    people_present: list[PersonObservation] = Field(default_factory=list)
    hazards: list[HazardObservation] = Field(default_factory=list)
    equipment_state: list[EquipmentState] = Field(default_factory=list)
    location: str = Field(min_length=1)
    contextual_factors: dict[str, Any] = Field(default_factory=dict)
    trigger_id: str = Field(min_length=1)
    timestamp: datetime
