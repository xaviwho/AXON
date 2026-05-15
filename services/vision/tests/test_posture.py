"""Posture classifier unit tests — keypoint geometry only, no model load."""

from services.vision.app.pose import (
    LEFT_HIP,
    LEFT_SHOULDER,
    PoseKeypoint,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    _classify_posture,
)


def _kps(positions: dict[int, tuple[float, float]]) -> list[PoseKeypoint]:
    out: list[PoseKeypoint] = []
    for i in range(33):
        if i in positions:
            x, y = positions[i]
            vis = 0.9
        else:
            x, y, vis = 0.5, 0.5, 0.9
        out.append(PoseKeypoint(name=f"kp_{i}", x=x, y=y, z=0.0, visibility=vis))
    return out


def test_standing_shoulders_above_hips():
    kps = _kps({
        LEFT_SHOULDER:  (0.45, 0.30),
        RIGHT_SHOULDER: (0.55, 0.30),
        LEFT_HIP:       (0.46, 0.60),
        RIGHT_HIP:      (0.54, 0.60),
    })
    assert _classify_posture(kps) == "standing"


def test_prone_shoulders_beside_hips():
    kps = _kps({
        LEFT_SHOULDER:  (0.20, 0.50),
        RIGHT_SHOULDER: (0.20, 0.55),
        LEFT_HIP:       (0.80, 0.50),
        RIGHT_HIP:      (0.80, 0.55),
    })
    assert _classify_posture(kps) == "prone"


def test_low_visibility_returns_unknown():
    kps = _kps({
        LEFT_SHOULDER:  (0.4, 0.3),
        RIGHT_SHOULDER: (0.6, 0.3),
        LEFT_HIP:       (0.4, 0.6),
        RIGHT_HIP:      (0.6, 0.6),
    })
    for idx in (LEFT_SHOULDER, RIGHT_SHOULDER):
        kps[idx] = PoseKeypoint(
            name=kps[idx].name, x=kps[idx].x, y=kps[idx].y, z=0.0, visibility=0.1
        )
    assert _classify_posture(kps) == "unknown"
