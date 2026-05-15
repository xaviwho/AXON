from datetime import datetime

from pydantic import BaseModel, Field

from .enums import SensorType


class SensorReading(BaseModel):
    sensor_id: str = Field(min_length=1)
    sensor_type: SensorType
    value: float
    unit: str = Field(min_length=1)
    timestamp: datetime
