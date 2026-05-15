"""Camera ingestors.

One asyncio task per camera. Each task opens its source, pulls frames at the
configured fps, JPEG-encodes them, and publishes to the bus. Real RTSP URLs
and local file sources share the cv2.VideoCapture code path. Synthetic mode
generates frames programmatically so we don't need a binary asset checked in.

This is intentionally the same code path for production RTSP and development
file/synthetic — only the source URL changes.
"""

from __future__ import annotations

import asyncio
import time
from itertools import count

import cv2
import numpy as np
from loguru import logger

from .bus import Bus
from .scenario import CameraConfig, CameraSourceKind


class _SyntheticSource:
    """Generates a small moving test pattern. No external assets needed."""

    def __init__(self, width: int, height: int) -> None:
        self._w = width
        self._h = height
        self._tick = count()

    def read(self) -> tuple[bool, np.ndarray]:
        t = next(self._tick)
        frame = np.full((self._h, self._w, 3), 32, dtype=np.uint8)
        # moving rectangle
        x = (t * 7) % max(1, self._w - 80)
        cv2.rectangle(frame, (x, 80), (x + 80, 160), (0, 200, 255), -1)
        # frame counter overlay
        cv2.putText(
            frame,
            f"AXON synthetic t={t}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        return True, frame

    def release(self) -> None:  # parity with cv2.VideoCapture
        return None


class _StillImageSource:
    """Loops a single JPEG/PNG as if it were a video stream.

    Resizes the baked-in image to the configured camera resolution so the
    on-the-wire payload matches what the scenario declares.
    """

    def __init__(self, path: str, width: int, height: int) -> None:
        image = cv2.imread(path)
        if image is None:
            raise FileNotFoundError(f"still_image source: unreadable file '{path}'")
        self._frame = cv2.resize(image, (width, height))

    def read(self) -> tuple[bool, np.ndarray]:
        return True, self._frame.copy()

    def release(self) -> None:
        return None


def _open_source(config: CameraConfig):
    if config.kind is CameraSourceKind.SYNTHETIC:
        return _SyntheticSource(config.width, config.height)
    if config.kind is CameraSourceKind.STILL_IMAGE:
        if config.url is None:
            raise ValueError(f"camera '{config.id}' kind=still_image requires 'url' (file path)")
        return _StillImageSource(config.url, config.width, config.height)
    if config.url is None:
        raise ValueError(f"camera '{config.id}' kind={config.kind.value} requires 'url'")
    src: str | int = config.url
    return cv2.VideoCapture(src)


class CameraIngestor:
    def __init__(self, bus: Bus, config: CameraConfig) -> None:
        self.bus = bus
        self.config = config
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.active = False

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=f"camera:{self.config.id}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except asyncio.TimeoutError:
                self._task.cancel()

    async def _run(self) -> None:
        cap = _open_source(self.config)
        # cv2.VideoCapture.isOpened() returns False for unreadable URLs; synthetic source has no such method.
        is_opened = getattr(cap, "isOpened", lambda: True)
        if not is_opened():
            logger.error(
                "camera {} failed to open source kind={} url={}",
                self.config.id, self.config.kind.value, self.config.url,
            )
            return

        self.active = True
        period = 1.0 / self.config.fps
        frame_id = 0
        next_t = time.monotonic()
        try:
            while not self._stop.is_set():
                ok, frame = await asyncio.to_thread(cap.read)
                if not ok or frame is None:
                    # file source EOF: loop back to start; rtsp: brief backoff.
                    if self.config.kind is CameraSourceKind.FILE:
                        await asyncio.to_thread(cap.set, cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    await asyncio.sleep(0.05)
                    continue

                ok, buf = await asyncio.to_thread(
                    cv2.imencode, ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                )
                if not ok:
                    continue

                await self.bus.publish_frame(
                    camera_id=self.config.id,
                    frame_id=frame_id,
                    timestamp_ns=time.time_ns(),
                    width=frame.shape[1],
                    height=frame.shape[0],
                    fmt="jpeg",
                    data=bytes(buf),
                )
                frame_id += 1

                next_t += period
                now = time.monotonic()
                sleep_for = next_t - now
                if sleep_for < -period:  # behind by more than one frame; skip ahead
                    next_t = now
                elif sleep_for > 0:
                    await asyncio.sleep(sleep_for)
        finally:
            self.active = False
            cap.release()


class CameraManager:
    def __init__(self, bus: Bus, configs: list[CameraConfig]) -> None:
        self._ingestors = [CameraIngestor(bus, c) for c in configs]

    async def start(self) -> None:
        for ig in self._ingestors:
            await ig.start()

    async def stop(self) -> None:
        await asyncio.gather(*(ig.stop() for ig in self._ingestors), return_exceptions=True)

    def status(self) -> list[dict]:
        return [{"id": ig.config.id, "active": ig.active} for ig in self._ingestors]
