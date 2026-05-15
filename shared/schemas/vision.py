from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BoundingBox(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float = Field(ge=0.0)
    y: float = Field(ge=0.0)
    width: float = Field(gt=0.0)
    height: float = Field(gt=0.0)


class VisionDetection(BaseModel):
    object_class: str = Field(min_length=1)
    bbox: BoundingBox
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: datetime
    camera_id: str = Field(min_length=1)
    frame_id: str = Field(min_length=1)


class Keypoint(BaseModel):
    name: str = Field(min_length=1)
    x: float
    y: float
    z: float | None = None
    visibility: float = Field(ge=0.0, le=1.0)


class PoseObservation(BaseModel):
    # person_id is anonymous-by-construction; it identifies a track within a session
    # but cannot be linked to a real-world identity. See CLAUDE.md anti-patterns.
    keypoints: list[Keypoint]
    confidence: float = Field(ge=0.0, le=1.0)
    person_id: str = Field(min_length=1)
    timestamp: datetime
    posture: str = Field(default="unknown", description="standing | prone | unknown")
    camera_id: str | None = None
    frame_id: str | None = None
