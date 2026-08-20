"""Text-prompted zero-shot detector — the fill-in for classes YOLOv10 does not carry.

CLAUDE.md documents ``fire``, ``smoke``, ``ppe_compliant``, ``ppe_violation``,
``equipment_in_use`` as post-MVP fine-tuning work. Rather than wait for
labelled data, this module runs OWL-ViTv2 (an open-vocabulary detector
from HuggingFace transformers) with a fixed prompt list and re-labels its
predictions to those class names. The output is the same ``Detection``
shape as :mod:`services.vision.app.yolo`, so the pipeline can publish
zero-shot detections through the identical ``VisionDetection`` path.

Two modes:

- ``off`` (default) — the constructor is trivially cheap, ``detect``
  returns an empty list, and no model is loaded. Keeps tests and
  environments without the transformers weights working.
- ``on`` — loads ``google/owlv2-base-patch16-ensemble`` (or the
  configured checkpoint) on first ``detect`` call and runs a single
  text-conditioned forward pass per frame. Predictions above
  ``score_threshold`` are emitted with the mapped class name.

The prompt-to-class map is deliberately conservative: one class per
prompt, and each class name matches an existing fusion rule so no
downstream schema changes are required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from .types import Detection


# Ordered so highest-priority phrasings come first — the mapping walks
# in order and the first prompt matching a detection wins. Keys are the
# text prompts fed to the detector; values are the class names published
# on the bus (must line up with fusion/rules.yaml entries).
DEFAULT_PROMPT_MAP: list[tuple[str, str]] = [
    ("a small flame", "fire"),
    ("visible smoke plume", "smoke"),
    ("worker wearing a hard hat and safety vest", "ppe_compliant"),
    ("worker without a hard hat", "ppe_violation"),
    ("hand-held power tool in use", "equipment_in_use"),
    ("chemical spill on the floor", "chemical_spill"),
]


@dataclass(frozen=True)
class ZeroShotConfig:
    mode: str = "off"                                    # "off" | "on"
    model_name: str = "google/owlv2-base-patch16-ensemble"
    score_threshold: float = 0.15
    device: str = "auto"                                 # "auto" | "cpu" | "cuda"
    max_detections: int = 20


class ZeroShotDetector:
    """OWL-ViTv2-backed zero-shot detector; text prompts → class labels."""

    def __init__(
        self,
        config: ZeroShotConfig | None = None,
        *,
        prompt_map: list[tuple[str, str]] | None = None,
    ) -> None:
        self._cfg = config or ZeroShotConfig()
        self._prompt_map = prompt_map or DEFAULT_PROMPT_MAP
        self._model: Any = None
        self._processor: Any = None
        self._device: str | None = None
        # In "off" mode we deliberately never touch transformers so tests
        # (and any prod deploy without the weights baked in) do not eat
        # the ~1 GB model download.
        self.active = self._cfg.mode == "on"

    def _lazy_load(self) -> None:
        if self._model is not None:
            return
        import torch    # noqa: PLC0415 — local so "off" mode has zero cost
        from transformers import Owlv2ForObjectDetection, Owlv2Processor

        if self._cfg.device == "cuda":
            device = "cuda"
        elif self._cfg.device == "cpu":
            device = "cpu"
        else:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        logger.info(
            "zero-shot detector loading model={} device={}",
            self._cfg.model_name, device,
        )
        self._processor = Owlv2Processor.from_pretrained(self._cfg.model_name)
        self._model = Owlv2ForObjectDetection.from_pretrained(self._cfg.model_name).to(device)
        self._model.eval()
        self._device = device

    def detect(self, image) -> list[Detection]:
        """Run zero-shot detection on a BGR (cv2) image.

        Returns an empty list in ``off`` mode (no model load, ~10 microseconds).
        In ``on`` mode returns library-schema ``Detection`` objects with
        ``class_name`` drawn from :data:`DEFAULT_PROMPT_MAP` and
        ``class_id=-1`` (no COCO id — these are text-conditioned classes).
        """
        if not self.active:
            return []

        import torch    # noqa: PLC0415
        self._lazy_load()

        # OWL-ViTv2 wants RGB PIL-like input; cv2 gives us BGR ndarray.
        # We convert without importing PIL — pass a numpy array and let
        # the processor handle it.
        rgb = image[:, :, ::-1]
        prompts = [self._prompt_map]    # one image, one prompt group
        text_only = [[p for p, _cls in self._prompt_map]]
        with torch.no_grad():
            inputs = self._processor(
                text=text_only, images=rgb, return_tensors="pt",
            ).to(self._device)
            outputs = self._model(**inputs)

        h, w = image.shape[:2]
        target_sizes = torch.tensor([(h, w)], device=self._device)
        results = self._processor.post_process_object_detection(
            outputs=outputs,
            threshold=self._cfg.score_threshold,
            target_sizes=target_sizes,
        )[0]

        boxes = results["boxes"].cpu().numpy()
        scores = results["scores"].cpu().numpy()
        labels = results["labels"].cpu().numpy()

        # Rank by score, keep the top-N after mapping.
        order = scores.argsort()[::-1][: self._cfg.max_detections]
        out: list[Detection] = []
        for idx in order:
            prompt_idx = int(labels[idx])
            if not 0 <= prompt_idx < len(self._prompt_map):
                continue
            _prompt, class_name = self._prompt_map[prompt_idx]
            x1, y1, x2, y2 = (float(v) for v in boxes[idx])
            out.append(
                Detection(
                    class_id=-1,
                    class_name=class_name,
                    confidence=float(scores[idx]),
                    x=max(0.0, min(x1, w - 1)),
                    y=max(0.0, min(y1, h - 1)),
                    width=max(1.0, x2 - x1),
                    height=max(1.0, y2 - y1),
                )
            )
        return out

    @property
    def supported_classes(self) -> list[str]:
        return [cls for _, cls in self._prompt_map]


__all__ = ["DEFAULT_PROMPT_MAP", "Detection", "ZeroShotConfig", "ZeroShotDetector"]
