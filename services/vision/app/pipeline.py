"""Per-camera inference pipeline.

Subscribes to one camera's frame stream, runs YOLOv10 + Pose Landmarker per
frame, publishes VisionDetection and PoseObservation back to the bus, and
records latency + counters via telemetry. Each camera gets its own asyncio
task; if it falls behind, the shared bus's consume_latest_frames discards
backlog so we never accumulate stale frames.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import cv2
import numpy as np
from loguru import logger

from shared.bus import Bus
from shared.schemas.vision import BoundingBox, Keypoint, PoseObservation, VisionDetection

from .pose import PoseEstimator
from .telemetry import Telemetry
from .yolo import YoloV10
from .zero_shot import ZeroShotDetector


class CameraPipeline:
    def __init__(
        self,
        camera_id: str,
        bus: Bus,
        yolo: YoloV10,
        pose: PoseEstimator,
        telemetry: Telemetry,
        zero_shot: ZeroShotDetector | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.bus = bus
        self.yolo = yolo
        self.pose = pose
        self.zero_shot = zero_shot
        self.telemetry = telemetry
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.active = False

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=f"vision:{self.camera_id}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=3.0)
            except asyncio.TimeoutError:
                self._task.cancel()

    async def _run(self) -> None:
        self.active = True
        logger.info("vision pipeline starting for camera={}", self.camera_id)
        try:
            async for fields in self.bus.consume_latest_frames(self.camera_id):
                if self._stop.is_set():
                    break
                await self._process(fields)
        finally:
            self.active = False

    async def _process(self, fields: dict[bytes, bytes]) -> None:
        frame_id = int(fields[b"frame_id"])
        ts_ns = int(fields[b"timestamp_ns"])
        ts = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)

        buf = np.frombuffer(fields[b"data"], dtype=np.uint8)
        image = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if image is None:
            logger.warning("vision: undecodable frame on {}", self.camera_id)
            return

        self.telemetry.frames_total.labels(camera_id=self.camera_id).inc()

        # YOLOv10 — synchronous, push to a worker thread to keep loop responsive.
        with self.telemetry.inference_span("yolo", self.camera_id):
            detections = await asyncio.to_thread(self.yolo.detect, image)

        # Pose Landmarker — same pattern.
        with self.telemetry.inference_span("pose", self.camera_id):
            poses = await asyncio.to_thread(self.pose.detect, image)

        # Zero-shot head for the classes YOLOv10 does not carry.
        if self.zero_shot is not None and self.zero_shot.active:
            with self.telemetry.inference_span("zero_shot", self.camera_id):
                zs = await asyncio.to_thread(self.zero_shot.detect, image)
            detections = list(detections) + list(zs)

        await self._publish_detections(detections, frame_id, ts)
        await self._publish_poses(poses, ts)

    async def _publish_detections(
        self, dets, frame_id: int, ts: datetime
    ) -> None:
        for d in dets:
            msg = VisionDetection(
                object_class=d.class_name,
                bbox=BoundingBox(x=d.x, y=d.y, width=d.width, height=d.height),
                confidence=d.confidence,
                timestamp=ts,
                camera_id=self.camera_id,
                frame_id=str(frame_id),
            )
            await self.bus.publish_detection(msg.model_dump(mode="json"))
            self.telemetry.detections_total.labels(
                camera_id=self.camera_id, class_name=d.class_name
            ).inc()

    async def _publish_poses(self, poses, ts: datetime) -> None:
        for p in poses:
            keypoints = [
                Keypoint(name=kp.name, x=kp.x, y=kp.y, z=kp.z, visibility=kp.visibility)
                for kp in p.keypoints
            ]
            obs = PoseObservation(
                keypoints=keypoints,
                confidence=p.confidence,
                person_id=p.person_id,
                timestamp=ts,
                posture=p.posture,
                camera_id=self.camera_id,
            )
            await self.bus.publish_pose(obs.model_dump(mode="json"))
            self.telemetry.poses_total.labels(
                camera_id=self.camera_id, posture=p.posture
            ).inc()


class VisionWorker:
    def __init__(
        self,
        bus: Bus,
        camera_ids: list[str],
        yolo: YoloV10,
        pose: PoseEstimator,
        telemetry: Telemetry,
        zero_shot: ZeroShotDetector | None = None,
    ) -> None:
        self._pipelines = [
            CameraPipeline(cam, bus, yolo, pose, telemetry, zero_shot)
            for cam in camera_ids
        ]

    async def start(self) -> None:
        for p in self._pipelines:
            await p.start()

    async def stop(self) -> None:
        await asyncio.gather(*(p.stop() for p in self._pipelines), return_exceptions=True)

    def status(self) -> list[dict]:
        return [{"camera_id": p.camera_id, "active": p.active} for p in self._pipelines]
