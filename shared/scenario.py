"""Scenario YAML loader — shared across services.

A scenario is the single source of truth for which cameras and which
sensors are active for one demo run. Sensing publishes from these
sources; downstream layers (vision, fusion) consume by the same IDs.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from shared.schemas.enums import SensorType


class CameraSourceKind(str, Enum):
    RTSP = "rtsp"
    FILE = "file"
    SYNTHETIC = "synthetic"
    # `still_image`: loop a single image as if it were a video stream.
    # Used by mock scenarios that need YOLO/Pose to produce real detections
    # without requiring a user-supplied video clip.
    STILL_IMAGE = "still_image"


class CameraConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: CameraSourceKind
    url: str | None = None                # rtsp:// or file path
    fps: int = Field(default=15, ge=1, le=60)
    width: int = Field(default=640, ge=64, le=4096)
    height: int = Field(default=360, ge=64, le=4096)


class SensorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: SensorType
    topic: str
    unit: str = "unit"
    # `trace` is consumed only by the mock sensor simulator (the live
    # sensing service ignores it). Kept here so the typed Scenario loader
    # doesn't reject scenarios that drive synthetic anomalies.
    trace: dict[str, Any] | None = None


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    duration_seconds: int = Field(default=60, ge=1, le=3600)
    cameras: list[CameraConfig] = Field(default_factory=list)
    sensors: list[SensorConfig] = Field(default_factory=list)


def load_scenario(path: Path) -> Scenario:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Scenario(**raw)


__all__ = [
    "CameraConfig",
    "CameraSourceKind",
    "Scenario",
    "SensorConfig",
    "load_scenario",
]
