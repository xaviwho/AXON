"""Synthetic frame source tests — exercise the dev-loop path without cv2 cameras."""

import cv2
import numpy as np

from services.sensing.app.camera import _SyntheticSource


def test_synthetic_source_yields_decodable_jpeg():
    src = _SyntheticSource(width=320, height=240)
    ok, frame = src.read()
    assert ok
    assert frame.shape == (240, 320, 3)
    assert frame.dtype == np.uint8

    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    assert ok
    decoded = cv2.imdecode(np.frombuffer(bytes(buf), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (240, 320, 3)


def test_synthetic_source_advances_pattern():
    src = _SyntheticSource(width=160, height=120)
    _, f0 = src.read()
    # consume some frames; pattern moves so a later frame must differ pixel-wise.
    for _ in range(20):
        src.read()
    _, fN = src.read()
    assert not np.array_equal(f0, fN)
