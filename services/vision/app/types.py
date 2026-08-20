"""Shared vision types — kept import-free so both YOLOv10 (onnxruntime)
and zero-shot (transformers) detectors can produce the same shape without
one dragging in the other's heavy dependencies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    x: float        # top-left in original-image pixel coords
    y: float
    width: float
    height: float


__all__ = ["Detection"]
