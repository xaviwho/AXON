"""Sensing-side re-export of the shared bus.

The implementation lives in shared/bus.py — kept here as a stable import
path so the sensing service's existing imports don't need touching.
"""

from shared.bus import (
    FRAME_STREAM_FMT,
    SENSOR_STREAM,
    Bus,
)

__all__ = ["Bus", "FRAME_STREAM_FMT", "SENSOR_STREAM"]
