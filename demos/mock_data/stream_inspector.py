"""Simple Redis Streams consumer used to inspect what sensing and vision publish.

Tails the frame, sensor, detection, and pose streams concurrently for a
fixed duration, prints one summary line per useful event, and returns a
Counter with totals. Used by the orchestrator and by hand for sanity
checks. Does not decode JPEG payloads — just reports their size.

Usage:
    python -m demos.mock_data.stream_inspector \\
        --redis-url redis://localhost:6380/0 \\
        --cameras cam-01 \\
        --duration 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter

from loguru import logger
from redis import asyncio as aioredis

SENSOR_STREAM = "axon:sensors"
DETECTION_STREAM = "axon:detections"
POSE_STREAM = "axon:poses"
ANOMALY_STREAM = "axon:anomalies"
SCENE_STREAM = "axon:scenes"
PLAN_STREAM = "axon:plans"
AUDIT_STREAM = "axon:audit"
ALERT_STREAM = "axon:alerts"


async def _initial_cursors(client: aioredis.Redis, names: list[str]) -> dict[str, str]:
    """Resolve "$" to a stable concrete ID for each stream.

    Using literal "$" on every XREAD call makes redis re-resolve to the
    current end of stream each invocation — events that arrive between two
    calls on a low-traffic stream (anomalies fire once per 10 s) get
    silently skipped. Pin cursors at startup instead.
    """
    cursors: dict[str, str] = {}
    for name in names:
        items = await client.xrevrange(name, count=1)
        cursors[name] = items[0][0].decode() if items else "0"
    return cursors


async def _read_loop(
    client: aioredis.Redis,
    cameras: list[str],
    deadline: float,
    counts: Counter,
) -> None:
    names = [f"axon:frames:{cam}" for cam in cameras]
    names += [SENSOR_STREAM, DETECTION_STREAM, POSE_STREAM,
              ANOMALY_STREAM, SCENE_STREAM, PLAN_STREAM,
              AUDIT_STREAM, ALERT_STREAM]
    streams = await _initial_cursors(client, names)
    while time.monotonic() < deadline:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        block_ms = min(1000, remaining_ms)
        resp = await client.xread(streams, block=block_ms, count=20)
        if not resp:
            continue
        for raw_stream, entries in resp:
            stream = raw_stream.decode()
            for entry_id, fields in entries:
                streams[stream] = entry_id.decode()
                if stream == SENSOR_STREAM:
                    payload = json.loads(fields[b"data"].decode("utf-8"))
                    counts[f"sensor:{payload['sensor_id']}"] += 1
                    logger.info(
                        "sensor[{}] {}={} {}",
                        payload["sensor_type"],
                        payload["sensor_id"],
                        round(payload["value"], 3),
                        payload["unit"],
                    )
                elif stream == DETECTION_STREAM:
                    payload = json.loads(fields[b"data"].decode("utf-8"))
                    counts[f"detection:{payload['object_class']}"] += 1
                    counts["detections_total"] += 1
                    if counts["detections_total"] % 5 == 1:
                        logger.info(
                            "detection {} on {}: conf={:.2f}",
                            payload["object_class"],
                            payload["camera_id"],
                            payload["confidence"],
                        )
                elif stream == POSE_STREAM:
                    payload = json.loads(fields[b"data"].decode("utf-8"))
                    posture = payload.get("posture", "unknown")
                    counts[f"pose:{posture}"] += 1
                    counts["poses_total"] += 1
                    if counts["poses_total"] % 5 == 1:
                        logger.info(
                            "pose person={} posture={} conf={:.2f}",
                            payload["person_id"], posture, payload["confidence"],
                        )
                elif stream == ANOMALY_STREAM:
                    payload = json.loads(fields[b"data"].decode("utf-8"))
                    counts["anomalies_total"] += 1
                    counts[f"trigger_reason:{payload['trigger_reason']}"] += 1
                    counts.setdefault("_anomalies", []).append(payload)
                    logger.warning(
                        "ANOMALY trigger_id={} score={:.2f} reason='{}'",
                        payload["trigger_id"], payload["composite_score"], payload["trigger_reason"],
                    )
                elif stream == SCENE_STREAM:
                    payload = json.loads(fields[b"data"].decode("utf-8"))
                    counts["scenes_total"] += 1
                    counts.setdefault("_scenes", []).append(payload)
                    hazards = [h["hazard_type"] for h in payload.get("hazards", [])]
                    logger.warning(
                        "SCENE trigger_id={} hazards={} people={} location={}",
                        payload["trigger_id"], hazards,
                        len(payload.get("people_present", [])),
                        payload.get("location"),
                    )
                elif stream == PLAN_STREAM:
                    payload = json.loads(fields[b"data"].decode("utf-8"))
                    counts["plans_total"] += 1
                    counts.setdefault("_plans", []).append(payload)
                    logger.warning(
                        "PLAN trigger_id={} severity={} confidence={:.2f} actions={}",
                        payload["trigger_id"], payload["severity"],
                        payload["confidence"],
                        [a["action_id"] for a in payload.get("actions", [])],
                    )
                elif stream == AUDIT_STREAM:
                    payload = json.loads(fields[b"data"].decode("utf-8"))
                    counts["audits_total"] += 1
                    counts[f"audit:{payload['action_id']}:{payload['effect']}"] += 1
                    counts.setdefault("_audits", []).append(payload)
                    logger.info(
                        "AUDIT trigger={} action={} effect={} latency={:.1f}ms",
                        payload["trigger_id"], payload["action_id"],
                        payload["effect"], payload.get("latency_ms", 0.0),
                    )
                elif stream == ALERT_STREAM:
                    payload = json.loads(fields[b"data"].decode("utf-8"))
                    counts["alerts_total"] += 1
                    counts.setdefault("_alerts", []).append(payload)
                    logger.warning(
                        "ALERT trigger={} severity={} zone={} message='{}'",
                        payload["trigger_id"], payload.get("severity"),
                        payload.get("zone_id"), payload.get("message"),
                    )
                else:
                    camera_id = fields[b"camera_id"].decode()
                    frame_id = fields[b"frame_id"].decode()
                    size = len(fields[b"data"])
                    counts[f"frames:{camera_id}"] += 1
                    if counts[f"frames:{camera_id}"] % 30 == 1:
                        logger.info(
                            "frame {} #{} {}x{} {} bytes",
                            camera_id, frame_id,
                            fields[b"width"].decode(),
                            fields[b"height"].decode(),
                            size,
                        )


async def run(redis_url: str, cameras: list[str], duration: int) -> Counter:
    counts: Counter = Counter()
    client = aioredis.from_url(redis_url, decode_responses=False)
    deadline = time.monotonic() + duration
    try:
        await client.ping()
        await _read_loop(client, cameras, deadline, counts)
    finally:
        await client.aclose()
    logger.info("inspector summary: {}", dict(counts))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis-url", default="redis://localhost:6380/0")
    parser.add_argument("--cameras", nargs="*", default=[])
    parser.add_argument("--duration", type=int, default=60)
    args = parser.parse_args()
    asyncio.run(run(args.redis_url, args.cameras, args.duration))


if __name__ == "__main__":
    main()
