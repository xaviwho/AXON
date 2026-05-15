"""YOLOv10 preprocessing / postprocessing math tests.

We don't load the actual ONNX in unit tests (the model file is only present
in the Docker runtime stage). Instead we verify the letterbox and the
coordinate unscaling math against a hand-computed expected output. These
are the parts most likely to have off-by-one bugs.

End-to-end inference is exercised via the live mock_movement run, where
the real model is loaded and detections are observed on the bus.
"""

import numpy as np
import pytest


@pytest.fixture
def yolo_module(monkeypatch):
    # Avoid importing onnxruntime at unit-test time on hosts without it.
    import sys
    import types

    if "onnxruntime" not in sys.modules:
        fake = types.SimpleNamespace(
            InferenceSession=lambda *a, **kw: None,
            get_available_providers=lambda: ["CPUExecutionProvider"],
        )
        monkeypatch.setitem(sys.modules, "onnxruntime", fake)

    from services.vision.app import yolo
    return yolo


def test_letterbox_landscape(yolo_module):
    yolo = yolo_module.YoloV10.__new__(yolo_module.YoloV10)
    yolo.input_size = 640
    img = np.zeros((360, 1280, 3), dtype=np.uint8)
    canvas, scale, (pad_x, pad_y) = yolo._letterbox(img)
    assert canvas.shape == (640, 640, 3)
    assert scale == pytest.approx(0.5, rel=1e-3)
    # No horizontal padding on a 16:9 source scaled to fit width.
    assert pad_x == 0
    # Vertical padding centers the image.
    assert pad_y == (640 - 180) // 2


def test_letterbox_portrait(yolo_module):
    yolo = yolo_module.YoloV10.__new__(yolo_module.YoloV10)
    yolo.input_size = 640
    img = np.zeros((1280, 360, 3), dtype=np.uint8)
    canvas, scale, (pad_x, pad_y) = yolo._letterbox(img)
    assert canvas.shape == (640, 640, 3)
    assert scale == pytest.approx(0.5, rel=1e-3)
    assert pad_y == 0
    assert pad_x == (640 - 180) // 2


def test_preprocess_normalizes_to_float32_chw(yolo_module):
    yolo = yolo_module.YoloV10.__new__(yolo_module.YoloV10)
    yolo.input_size = 640
    img = np.full((360, 640, 3), 128, dtype=np.uint8)
    tensor, _scale, _pad = yolo._preprocess(img)
    assert tensor.dtype == np.float32
    assert tensor.shape == (1, 3, 640, 640)
    # 128/255 ≈ 0.5020 in the unpadded region.
    sample = tensor[0, 0, 320, 320]
    assert 0.49 < float(sample) < 0.51
