"""YOLOv10 ONNX wrapper.

The Ultralytics YOLOv10 export already has end-to-end NMS baked in — the
model output is the final, sorted, NMS-filtered detection list:
    output[0] shape: (1, max_dets, 6) = (x1, y1, x2, y2, score, class_id)

Coordinates are in pixel space of the model input (typically 640×640 after
letterbox padding). We undo the letterbox to map back to the original frame.
"""

from __future__ import annotations

import cv2
import numpy as np
import onnxruntime as ort
from loguru import logger

from .coco_classes import COCO_CLASSES
from .types import Detection

__all__ = ["Detection", "YoloV10"]


def _resolve_providers(preference: str) -> list[str]:
    available = ort.get_available_providers()
    if preference == "cpu":
        return ["CPUExecutionProvider"]
    if preference == "cuda" and "CUDAExecutionProvider" in available:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    # auto: prefer CUDA when available
    if "CUDAExecutionProvider" in available:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


class YoloV10:
    def __init__(
        self,
        onnx_path: str,
        *,
        input_size: int = 640,
        conf_threshold: float = 0.25,
        provider: str = "auto",
    ) -> None:
        providers = _resolve_providers(provider)
        self.session = ort.InferenceSession(onnx_path, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.active_provider = self.session.get_providers()[0]
        logger.info(
            "yolov10 loaded: path={} provider={} input_size={}",
            onnx_path, self.active_provider, input_size,
        )

    # ---- preprocessing ------------------------------------------------------

    def _letterbox(self, image: np.ndarray) -> tuple[np.ndarray, float, tuple[int, int]]:
        h, w = image.shape[:2]
        s = self.input_size
        scale = min(s / h, s / w)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        pad_x, pad_y = (s - new_w) // 2, (s - new_h) // 2
        canvas = np.full((s, s, 3), 114, dtype=np.uint8)
        canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized
        return canvas, scale, (pad_x, pad_y)

    def _preprocess(self, image: np.ndarray) -> tuple[np.ndarray, float, tuple[int, int]]:
        canvas, scale, pad = self._letterbox(image)
        # BGR → RGB → 0..1 → CHW → batch
        chw = canvas[:, :, ::-1].astype(np.float32, copy=False) / 255.0
        chw = np.transpose(chw, (2, 0, 1))
        return np.expand_dims(chw, axis=0), scale, pad

    # ---- inference ----------------------------------------------------------

    def detect(self, image: np.ndarray) -> list[Detection]:
        """Run inference on a BGR (cv2) image; return scaled detections."""
        tensor, scale, (pad_x, pad_y) = self._preprocess(image)
        outputs = self.session.run(None, {self.input_name: tensor})
        # YOLOv10 export: first output is (1, max_dets, 6).
        raw = outputs[0]
        if raw.ndim != 3 or raw.shape[-1] != 6:
            raise RuntimeError(f"unexpected YOLOv10 output shape: {raw.shape}")

        h, w = image.shape[:2]
        detections: list[Detection] = []
        for row in raw[0]:
            score = float(row[4])
            if score < self.conf_threshold:
                continue
            x1 = (float(row[0]) - pad_x) / scale
            y1 = (float(row[1]) - pad_y) / scale
            x2 = (float(row[2]) - pad_x) / scale
            y2 = (float(row[3]) - pad_y) / scale
            x1 = max(0.0, min(x1, w - 1))
            y1 = max(0.0, min(y1, h - 1))
            x2 = max(0.0, min(x2, w - 1))
            y2 = max(0.0, min(y2, h - 1))
            cls_id = int(row[5])
            class_name = COCO_CLASSES[cls_id] if 0 <= cls_id < len(COCO_CLASSES) else f"cls_{cls_id}"
            detections.append(
                Detection(
                    class_id=cls_id,
                    class_name=class_name,
                    confidence=score,
                    x=x1,
                    y=y1,
                    width=max(1.0, x2 - x1),
                    height=max(1.0, y2 - y1),
                )
            )
        return detections
