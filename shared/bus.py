"""Internal pub/sub via Redis Streams — shared across services.

Stream layout (all binary-safe; payloads are utf-8 JSON unless noted):

  axon:frames:<camera_id>   per-camera frame stream (fields below)
                            published by services/sensing
  axon:sensors              shared sensor stream
                            field: data (JSON SensorReading)
  axon:detections           shared object-detection stream
                            field: data (JSON VisionDetection)
  axon:poses                shared pose-observation stream
                            field: data (JSON PoseObservation)
  axon:anomalies            shared anomaly-score stream (Prompt 4+)

Per-frame fields on axon:frames:<camera_id>:
  camera_id, frame_id, timestamp_ns, width, height, fmt, data (binary JPEG)

Skip-ahead consumer semantics: `consume_latest_frames` always returns the
newest available message after a blocking wait, discarding any backlog.
This is the contract per Prompt 3: "Skip frames if behind, never queue
indefinitely."
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger
from redis import asyncio as aioredis

FRAME_STREAM_FMT = "axon:frames:{camera_id}"
SENSOR_STREAM = "axon:sensors"
DETECTION_STREAM = "axon:detections"
POSE_STREAM = "axon:poses"
ANOMALY_STREAM = "axon:anomalies"
SCENE_STREAM = "axon:scenes"
PLAN_STREAM = "axon:plans"
AUDIT_STREAM = "axon:audit"
ALERT_STREAM = "axon:alerts"
TRIGGER_KEY_FMT = "axon:trigger:{trigger_id}"


class Bus:
    """Single async Redis Streams handle. Cheap to construct, share across tasks."""

    def __init__(
        self,
        client: aioredis.Redis,
        *,
        frame_maxlen: int = 300,
        sensor_maxlen: int = 5000,
        detection_maxlen: int = 5000,
        pose_maxlen: int = 5000,
        anomaly_maxlen: int = 1000,
        scene_maxlen: int = 1000,
        plan_maxlen: int = 1000,
        audit_maxlen: int = 10000,
        alert_maxlen: int = 5000,
        trigger_ttl_seconds: int = 300,
    ) -> None:
        self._client = client
        self._frame_maxlen = frame_maxlen
        self._sensor_maxlen = sensor_maxlen
        self._detection_maxlen = detection_maxlen
        self._pose_maxlen = pose_maxlen
        self._anomaly_maxlen = anomaly_maxlen
        self._scene_maxlen = scene_maxlen
        self._plan_maxlen = plan_maxlen
        self._audit_maxlen = audit_maxlen
        self._alert_maxlen = alert_maxlen
        self._trigger_ttl_seconds = trigger_ttl_seconds
        self._healthy = False

    @classmethod
    async def connect(cls, url: str, **kwargs: int) -> "Bus":
        client = aioredis.from_url(url, decode_responses=False)
        bus = cls(client, **kwargs)
        await bus._client.ping()
        bus._healthy = True
        logger.info("redis bus connected: {}", url)
        return bus

    @property
    def healthy(self) -> bool:
        return self._healthy

    # --- publishers ----------------------------------------------------------

    async def publish_frame(
        self,
        *,
        camera_id: str,
        frame_id: int,
        timestamp_ns: int,
        width: int,
        height: int,
        fmt: str,
        data: bytes,
    ) -> None:
        await self._client.xadd(
            FRAME_STREAM_FMT.format(camera_id=camera_id),
            {
                "camera_id": camera_id,
                "frame_id": str(frame_id),
                "timestamp_ns": str(timestamp_ns),
                "width": str(width),
                "height": str(height),
                "fmt": fmt,
                "data": data,
            },
            maxlen=self._frame_maxlen,
            approximate=True,
        )

    async def publish_sensor(self, payload: dict[str, Any]) -> None:
        await self._client.xadd(
            SENSOR_STREAM,
            {"data": json.dumps(payload).encode("utf-8")},
            maxlen=self._sensor_maxlen,
            approximate=True,
        )

    async def publish_detection(self, payload: dict[str, Any]) -> None:
        await self._client.xadd(
            DETECTION_STREAM,
            {"data": json.dumps(payload).encode("utf-8")},
            maxlen=self._detection_maxlen,
            approximate=True,
        )

    async def publish_pose(self, payload: dict[str, Any]) -> None:
        await self._client.xadd(
            POSE_STREAM,
            {"data": json.dumps(payload).encode("utf-8")},
            maxlen=self._pose_maxlen,
            approximate=True,
        )

    async def publish_anomaly(self, payload: dict[str, Any]) -> None:
        await self._client.xadd(
            ANOMALY_STREAM,
            {"data": json.dumps(payload).encode("utf-8")},
            maxlen=self._anomaly_maxlen,
            approximate=True,
        )

    async def publish_scene(self, payload: dict[str, Any]) -> None:
        await self._client.xadd(
            SCENE_STREAM,
            {"data": json.dumps(payload).encode("utf-8")},
            maxlen=self._scene_maxlen,
            approximate=True,
        )

    async def publish_plan(self, payload: dict[str, Any]) -> None:
        await self._client.xadd(
            PLAN_STREAM,
            {"data": json.dumps(payload).encode("utf-8")},
            maxlen=self._plan_maxlen,
            approximate=True,
        )

    async def publish_audit(self, payload: dict[str, Any]) -> None:
        await self._client.xadd(
            AUDIT_STREAM,
            {"data": json.dumps(payload).encode("utf-8")},
            maxlen=self._audit_maxlen,
            approximate=True,
        )

    async def publish_alert(self, payload: dict[str, Any]) -> None:
        await self._client.xadd(
            ALERT_STREAM,
            {"data": json.dumps(payload).encode("utf-8")},
            maxlen=self._alert_maxlen,
            approximate=True,
        )

    # --- trigger cache (read by Layer C to retrieve incident context) --------

    async def cache_trigger_context(
        self,
        *,
        trigger_id: str,
        score: float,
        trigger_reason: str,
        timestamp_iso: str,
        contributing_signals: list[dict[str, Any]],
        frame_refs: dict[str, list[str]],   # camera_id → list[stream_entry_id]
        sensor_refs: dict[str, dict[str, Any]],
    ) -> None:
        key = TRIGGER_KEY_FMT.format(trigger_id=trigger_id)
        payload = {
            "score": str(score),
            "trigger_reason": trigger_reason,
            "timestamp": timestamp_iso,
            "contributing_signals": json.dumps(contributing_signals).encode("utf-8"),
            "frame_refs": json.dumps(frame_refs).encode("utf-8"),
            "sensor_refs": json.dumps(sensor_refs).encode("utf-8"),
        }
        await self._client.hset(key, mapping=payload)
        await self._client.expire(key, self._trigger_ttl_seconds)

    async def latest_frame_entry_ids(self, camera_id: str, count: int = 4) -> list[str]:
        """Return the most recent N frame-stream entry IDs for one camera.

        Used by the fusion engine at trigger time to snapshot the frames Layer C
        will analyze. The IDs are stable handles into axon:frames:<camera_id>.
        """
        stream = FRAME_STREAM_FMT.format(camera_id=camera_id)
        items = await self._client.xrevrange(stream, count=count)
        return [item[0].decode() for item in items]

    async def fetch_trigger_context(self, trigger_id: str) -> dict[str, Any] | None:
        """Read the trigger-context hash written by fusion. Returns None if expired."""
        key = TRIGGER_KEY_FMT.format(trigger_id=trigger_id)
        raw = await self._client.hgetall(key)
        if not raw:
            return None
        out: dict[str, Any] = {}
        for k, v in raw.items():
            field = k.decode()
            if field in ("contributing_signals", "frame_refs", "sensor_refs"):
                out[field] = json.loads(v.decode("utf-8"))
            elif field == "score":
                out[field] = float(v.decode())
            else:
                out[field] = v.decode()
        return out

    async def fetch_frame(self, camera_id: str, entry_id: str) -> bytes | None:
        """Return the JPEG bytes for a specific frame entry, or None if evicted."""
        stream = FRAME_STREAM_FMT.format(camera_id=camera_id)
        items = await self._client.xrange(stream, min=entry_id, max=entry_id)
        if not items:
            return None
        _, fields = items[0]
        data = fields.get(b"data")
        return bytes(data) if data is not None else None

    async def fetch_frames_by_refs(
        self, frame_refs: dict[str, list[str]], *, max_per_camera: int = 4
    ) -> list[tuple[str, str, bytes]]:
        """Pull JPEG bytes for the entry IDs cached at trigger time.

        Returns [(camera_id, entry_id, jpeg_bytes), …] in stream order.
        Silently drops entries whose frame has been evicted from the
        ring (MAXLEN), so a slow Layer C still gets whatever survived.
        """
        out: list[tuple[str, str, bytes]] = []
        for camera_id, entry_ids in frame_refs.items():
            for entry_id in entry_ids[:max_per_camera]:
                data = await self.fetch_frame(camera_id, entry_id)
                if data is not None:
                    out.append((camera_id, entry_id, data))
        return out

    # --- consumers -----------------------------------------------------------

    async def consume_latest_frames(
        self, camera_id: str, *, block_ms: int = 500, batch: int = 64
    ) -> AsyncIterator[dict[bytes, bytes]]:
        """Yield only the newest frame received since the last yield.

        We use Redis XREAD with a batch read, then deliberately discard all
        but the newest entry — that's the "skip if behind" contract. The
        cursor advances to that newest entry, so older queued frames are
        skipped on the next read too.
        """
        stream = FRAME_STREAM_FMT.format(camera_id=camera_id)
        last_id: bytes | str = "$"
        while True:
            resp = await self._client.xread({stream: last_id}, count=batch, block=block_ms)
            if not resp:
                continue
            _, entries = resp[0]
            if not entries:
                continue
            entry_id, fields = entries[-1]   # newest in the batch
            last_id = entry_id
            yield fields

    async def consume_streams(
        self,
        stream_names: list[str],
        *,
        block_ms: int = 100,
        count: int = 100,
        start_id: str = "$",
    ) -> AsyncIterator[tuple[str, str, dict[bytes, bytes]]]:
        """Sequentially yield messages from multiple streams (no skip-ahead).

        Unlike `consume_latest_frames`, this preserves every message — fusion
        and the console persister both need the full signal stream.

        Cursor handling is the subtle bit: passing literal "$" on every XREAD
        makes redis re-resolve to *current end of stream* each call, so any
        events that arrived on a low-traffic stream between two XREADs get
        silently skipped. We pin each cursor by reading the stream's current
        last-id once at startup; thereafter each cursor advances strictly
        forward as messages are consumed.
        """
        cursors: dict[str, str] = {}
        for name in stream_names:
            if start_id == "$":
                items = await self._client.xrevrange(name, count=1)
                cursors[name] = items[0][0].decode() if items else "0"
            else:
                cursors[name] = start_id
        while True:
            resp = await self._client.xread(cursors, block=block_ms, count=count)
            if not resp:
                yield "", "", {}    # heartbeat tick on idle, lets caller re-evaluate
                continue
            for stream_b, entries in resp:
                stream = stream_b.decode()
                for entry_id_b, fields in entries:
                    entry_id = entry_id_b.decode()
                    cursors[stream] = entry_id
                    yield stream, entry_id, fields

    async def close(self) -> None:
        await self._client.aclose()
        self._healthy = False


__all__ = [
    "ALERT_STREAM",
    "ANOMALY_STREAM",
    "AUDIT_STREAM",
    "Bus",
    "DETECTION_STREAM",
    "FRAME_STREAM_FMT",
    "PLAN_STREAM",
    "POSE_STREAM",
    "SCENE_STREAM",
    "SENSOR_STREAM",
    "TRIGGER_KEY_FMT",
]
