"""Sensing-side re-export of the shared scenario loader.

The implementation lives in shared/scenario.py — kept here so existing
imports inside services/sensing don't need touching.
"""

from shared.scenario import (
    CameraConfig,
    CameraSourceKind,
    Scenario,
    SensorConfig,
    load_scenario,
)

__all__ = [
    "CameraConfig",
    "CameraSourceKind",
    "Scenario",
    "SensorConfig",
    "load_scenario",
]
