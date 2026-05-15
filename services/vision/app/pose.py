"""MediaPipe Pose Landmarker wrapper + simple posture classifier.

We use MediaPipe Tasks PoseLandmarker (the newer API) configured for static
single-image inference. For the MVP we classify each detected person as
`standing` or `prone`. `fallen` is a transition state that requires
temporal context — we mark it as TODO and document in services/vision/README.md.

Posture rule (single-frame heuristic):
  - Compute mean shoulder and mean hip in normalized (0..1) coordinates.
  - Angle of the torso vector relative to vertical:
      θ = atan2(|dx|, |dy|) — small θ → torso is vertical → standing.
  - θ < 30° → standing; θ > 60° → prone; otherwise unknown.
The thresholds are intentionally wide to be robust to noisy keypoints.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from loguru import logger


@dataclass(frozen=True)
class PoseKeypoint:
    name: str
    x: float
    y: float
    z: float
    visibility: float


@dataclass(frozen=True)
class Pose:
    person_id: str
    keypoints: list[PoseKeypoint]
    posture: str       # "standing" | "prone" | "unknown"
    confidence: float = field(default=0.0)


# MediaPipe Pose Landmarker emits 33 keypoints in this order; we name the
# ones we actually use for the posture rule.
_LANDMARK_NAMES: list[str] = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb",
    "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
]
LEFT_SHOULDER = _LANDMARK_NAMES.index("left_shoulder")
RIGHT_SHOULDER = _LANDMARK_NAMES.index("right_shoulder")
LEFT_HIP = _LANDMARK_NAMES.index("left_hip")
RIGHT_HIP = _LANDMARK_NAMES.index("right_hip")


def _classify_posture(keypoints: list[PoseKeypoint]) -> str:
    ls, rs = keypoints[LEFT_SHOULDER], keypoints[RIGHT_SHOULDER]
    lh, rh = keypoints[LEFT_HIP], keypoints[RIGHT_HIP]
    if min(ls.visibility, rs.visibility, lh.visibility, rh.visibility) < 0.4:
        return "unknown"
    shoulder = ((ls.x + rs.x) / 2.0, (ls.y + rs.y) / 2.0)
    hip = ((lh.x + rh.x) / 2.0, (lh.y + rh.y) / 2.0)
    dx = shoulder[0] - hip[0]
    dy = shoulder[1] - hip[1]
    # atan2(|dx|, |dy|): 0 when torso is purely vertical, π/2 when horizontal.
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return "unknown"
    theta = math.degrees(math.atan2(abs(dx), abs(dy)))
    if theta < 30.0:
        return "standing"
    if theta > 60.0:
        return "prone"
    return "unknown"


class PoseEstimator:
    def __init__(
        self,
        task_path: str,
        *,
        max_poses: int = 2,
        min_detection_conf: float = 0.3,
        min_presence_conf: float = 0.3,
    ) -> None:
        # Imported lazily so the posture-classifier unit tests don't require
        # mediapipe on the host venv.
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python.vision import (
            PoseLandmarker,
            PoseLandmarkerOptions,
            RunningMode,
        )

        self._mp = mp
        options = PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=task_path),
            running_mode=RunningMode.IMAGE,
            num_poses=max_poses,
            min_pose_detection_confidence=min_detection_conf,
            min_pose_presence_confidence=min_presence_conf,
        )
        self._lm = PoseLandmarker.create_from_options(options)
        logger.info("pose landmarker loaded: {}", task_path)

    def detect(self, image_bgr: np.ndarray) -> list[Pose]:
        mp = self._mp
        rgb = image_bgr[:, :, ::-1].copy()      # MediaPipe expects RGB; .copy() ensures contiguous
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._lm.detect(mp_image)

        poses: list[Pose] = []
        for idx, landmarks in enumerate(result.pose_landmarks or []):
            kps = [
                PoseKeypoint(
                    name=_LANDMARK_NAMES[i] if i < len(_LANDMARK_NAMES) else f"kp_{i}",
                    x=lm.x,
                    y=lm.y,
                    z=lm.z,
                    visibility=lm.visibility,
                )
                for i, lm in enumerate(landmarks)
            ]
            posture = _classify_posture(kps)
            # Use mean visibility as a coarse confidence signal.
            mean_vis = float(np.mean([k.visibility for k in kps])) if kps else 0.0
            poses.append(
                Pose(
                    person_id=f"anon-{idx}",
                    keypoints=kps,
                    posture=posture,
                    confidence=mean_vis,
                )
            )
        return poses

    def close(self) -> None:
        self._lm.close()
