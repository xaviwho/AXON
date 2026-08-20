"""Zero-shot detector wiring — tests exercise the off-mode contract and
the prompt/class mapping without downloading the OWL-ViTv2 weights."""

from __future__ import annotations

import numpy as np

from services.vision.app.zero_shot import (
    DEFAULT_PROMPT_MAP,
    ZeroShotConfig,
    ZeroShotDetector,
)


def test_off_mode_is_no_op_and_never_loads_model():
    d = ZeroShotDetector(ZeroShotConfig(mode="off"))
    assert d.active is False
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    assert d.detect(img) == []
    # The lazy loader must not have run — no torch/transformers touched.
    assert d._model is None
    assert d._processor is None


def test_supported_classes_match_prompt_map():
    d = ZeroShotDetector(ZeroShotConfig(mode="off"))
    assert d.supported_classes == [cls for _, cls in DEFAULT_PROMPT_MAP]


def test_prompt_map_covers_deferred_yolov10_classes():
    """CLAUDE.md defers fire/smoke/ppe/equipment; each must be prompt-covered."""
    classes = {cls for _, cls in DEFAULT_PROMPT_MAP}
    for name in ("fire", "smoke", "ppe_compliant", "ppe_violation", "equipment_in_use"):
        assert name in classes, f"deferred YOLOv10 class {name!r} not in zero-shot prompts"


def test_prompt_map_class_names_align_with_fusion_rules():
    """Class labels must match fusion/rules.yaml — otherwise no rule fires."""
    from pathlib import Path

    import yaml

    rules_path = Path(__file__).resolve().parents[3] / "services" / "fusion" / "rules.yaml"
    rules = yaml.safe_load(rules_path.read_text())
    referenced_classes: set[str] = set()
    for r in rules.get("rules", []):
        if r.get("kind") == "vision_class":
            referenced_classes.update(r.get("classes") or [])
        if r.get("kind") == "vision_class_pair":
            referenced_classes.add(r.get("class_a"))
            referenced_classes.add(r.get("class_b"))

    zs_classes = {cls for _, cls in DEFAULT_PROMPT_MAP}
    covered = referenced_classes & zs_classes
    # At least the CLAUDE.md-deferred set must be covered so activating
    # zero-shot immediately makes those rules fireable.
    assert {"fire", "smoke", "ppe_violation", "equipment_in_use"} <= covered


def test_custom_prompt_map_overrides_default():
    custom = [("thick black smoke", "smoke")]
    d = ZeroShotDetector(ZeroShotConfig(mode="off"), prompt_map=custom)
    assert d.supported_classes == ["smoke"]
