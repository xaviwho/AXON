"""Sliding-window state held by the fusion engine.

Holds the recent observation streams (detections, poses, sensor latest) and
the derived "prone streak" state used by the persistent-prone rule.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from shared.schemas.sensors import SensorReading
from shared.schemas.vision import PoseObservation, VisionDetection


@dataclass
class ProneStreak:
    started_at: datetime
    last_seen_at: datetime
    camera_id: str | None


@dataclass
class FusionState:
    window_seconds: float = 5.0
    detections: deque[VisionDetection] = field(default_factory=deque)
    poses: deque[PoseObservation] = field(default_factory=deque)
    sensor_latest: dict[str, SensorReading] = field(default_factory=dict)
    prone_streaks: dict[str, ProneStreak] = field(default_factory=dict)

    def ingest_detection(self, d: VisionDetection) -> None:
        self.detections.append(d)

    def ingest_pose(self, p: PoseObservation) -> None:
        self.poses.append(p)
        # streak update — a missing/changed posture resets the streak.
        if p.posture == "prone":
            streak = self.prone_streaks.get(p.person_id)
            if streak is None:
                self.prone_streaks[p.person_id] = ProneStreak(
                    started_at=p.timestamp,
                    last_seen_at=p.timestamp,
                    camera_id=p.camera_id,
                )
            else:
                streak.last_seen_at = p.timestamp
                streak.camera_id = p.camera_id or streak.camera_id
        else:
            self.prone_streaks.pop(p.person_id, None)

    def ingest_sensor(self, r: SensorReading) -> None:
        self.sensor_latest[r.sensor_id] = r

    def prune(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.window_seconds)
        while self.detections and self.detections[0].timestamp < cutoff:
            self.detections.popleft()
        while self.poses and self.poses[0].timestamp < cutoff:
            self.poses.popleft()
        # Streaks need a longer grace period than the observation window —
        # otherwise a brief drop in pose detections (a missed MediaPipe
        # frame) would erase a 5+ s prone streak. We keep them alive for
        # 3× the window before deciding the person actually left frame.
        streak_cutoff = now - timedelta(seconds=self.window_seconds * 3)
        stale = [
            pid for pid, s in self.prone_streaks.items()
            if s.last_seen_at < streak_cutoff
        ]
        for pid in stale:
            del self.prone_streaks[pid]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
