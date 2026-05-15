"""Orchestrates one scenario end-to-end against a running docker-compose stack.

Steps:
  1. Load the scenario YAML.
  2. Verify redis + mosquitto + sensing reachable.
  3. Launch the sensor simulator + stream inspector concurrently for the
     scenario's duration.
  4. Print a summary and exit non-zero if nothing was ingested.

Assumes `docker compose up -d redis mosquitto sensing` has already been
run by the Makefile. This script does not manage container lifecycle.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
import websockets
import yaml
from loguru import logger
from redis import asyncio as aioredis

from demos.mock_data import sensor_simulator, stream_inspector

SCENARIO_DIR = Path(__file__).parent / "scenarios"


async def _tail_slice_ws(url: str, duration: int, events: list[dict]) -> None:
    """Sit on the slice-control WebSocket for `duration` seconds, log events."""
    try:
        async with websockets.connect(url) as ws:
            deadline = asyncio.get_event_loop().time() + duration
            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=max(0.1, remaining))
                except asyncio.TimeoutError:
                    continue
                try:
                    payload = json.loads(msg)
                except json.JSONDecodeError:
                    continue
                events.append(payload)
                if payload.get("event") != "snapshot":
                    logger.warning(
                        "SLICE event={} detail={}",
                        payload.get("event"), payload.get("detail"),
                    )
    except (OSError, websockets.WebSocketException) as exc:
        logger.warning("slice WS unavailable ({}); skipping slice tail", exc)


async def _wait_for_sensing(url: str, timeout: float) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await client.get(url)
                if r.status_code == 200 and r.json().get("redis_connected"):
                    logger.info("sensing healthy: {}", r.json())
                    return
            except (httpx.HTTPError, ValueError) as exc:
                last_err = exc
            await asyncio.sleep(0.5)
    raise RuntimeError(f"sensing /health unreachable after {timeout}s ({last_err})")


async def run(
    scenario_name: str,
    *,
    redis_url: str,
    mqtt_host: str,
    mqtt_port: int,
    sensing_url: str,
    slice_ws_url: str = "ws://localhost:8002/ws",
    duration_override: int | None = None,
) -> int:
    scenario_path = SCENARIO_DIR / f"{scenario_name}.yaml"
    if not scenario_path.exists():
        logger.error("no such scenario: {}", scenario_path)
        return 2

    raw = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    duration = duration_override or int(raw.get("duration_seconds", 60))
    cameras = [c["id"] for c in raw.get("cameras") or []]

    logger.info("orchestrator: waiting for sensing /health")
    await _wait_for_sensing(sensing_url, timeout=30.0)

    slice_events: list[dict] = []
    inspector_task = asyncio.create_task(
        stream_inspector.run(redis_url, cameras, duration),
        name="inspector",
    )
    simulator_task = asyncio.create_task(
        sensor_simulator.run(
            scenario_path,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            duration_override=duration,
        ),
        name="simulator",
    )
    slice_ws_task = asyncio.create_task(
        _tail_slice_ws(slice_ws_url, duration, slice_events),
        name="slice-ws-tail",
    )
    counts, _, _ = await asyncio.gather(inspector_task, simulator_task, slice_ws_task)

    frame_total = sum(v for k, v in counts.items() if k.startswith("frames:"))
    sensor_total = sum(v for k, v in counts.items() if k.startswith("sensor:"))
    detection_total = counts.get("detections_total", 0)
    pose_total = counts.get("poses_total", 0)
    anomaly_total = counts.get("anomalies_total", 0)
    scene_total = counts.get("scenes_total", 0)
    plan_total = counts.get("plans_total", 0)
    audit_total = counts.get("audits_total", 0)
    alert_total = counts.get("alerts_total", 0)
    slice_change_events = [e for e in slice_events
                           if e.get("event") not in (None, "snapshot")]
    logger.info(
        "orchestrator: frames={} sensors={} detections={} poses={} "
        "anomalies={} scenes={} plans={} audits={} alerts={} slice_events={}",
        frame_total, sensor_total, detection_total, pose_total,
        anomaly_total, scene_total, plan_total,
        audit_total, alert_total, len(slice_change_events),
    )

    # Latency check: pull each trigger's cached sensor_refs from Redis and
    # diff (emission_ts - earliest_contributing_input_ts). This is the
    # "fire detection → trigger" gap that Prompt 4 needs ≤ 200 ms.
    if anomaly_total:
        anomalies = counts.get("_anomalies", []) or []
        client = aioredis.from_url(redis_url, decode_responses=False)
        try:
            for a in anomalies:
                emission_iso = a["timestamp"]
                emission_ts = datetime.fromisoformat(emission_iso.replace("Z", "+00:00"))
                contrib_sources = {s["source"] for s in a.get("contributing_signals", [])}
                cache_key = f"axon:trigger:{a['trigger_id']}"
                raw_refs = await client.hget(cache_key, "sensor_refs")
                input_ts: datetime | None = None
                if raw_refs is not None:
                    refs = json.loads(raw_refs.decode("utf-8"))
                    for sid, reading in refs.items():
                        src = f"sensor:{reading['sensor_type']}:{sid}"
                        if src in contrib_sources:
                            ts = datetime.fromisoformat(
                                reading["timestamp"].replace("Z", "+00:00")
                            )
                            if input_ts is None or ts < input_ts:
                                input_ts = ts
                latency_ms: float | None = None
                if input_ts is not None:
                    latency_ms = (emission_ts - input_ts).total_seconds() * 1000
                logger.info(
                    "  trigger_id={} score={:.2f} reason='{}' "
                    "latency={}ms signals={}",
                    a["trigger_id"], a["composite_score"], a["trigger_reason"],
                    f"{latency_ms:.1f}" if latency_ms is not None else "?",
                    [s["source"] for s in a.get("contributing_signals", [])],
                )
        finally:
            await client.aclose()

    # Scene latency: time between anomaly emission and the matching SceneDescription
    # arriving on axon:scenes (Layer C end-to-end wall-clock).
    if scene_total:
        scenes = counts.get("_scenes", []) or []
        anomalies_by_id = {a["trigger_id"]: a for a in (counts.get("_anomalies", []) or [])}
        for sc in scenes:
            tid = sc["trigger_id"]
            scene_ts = datetime.fromisoformat(sc["timestamp"].replace("Z", "+00:00"))
            anom = anomalies_by_id.get(tid)
            if anom is None:
                logger.info("  scene trigger_id={} (no matching anomaly captured)", tid)
                continue
            anom_ts = datetime.fromisoformat(anom["timestamp"].replace("Z", "+00:00"))
            delta_ms = (scene_ts - anom_ts).total_seconds() * 1000
            logger.info(
                "  scene trigger_id={} hazards={} latency_from_anomaly={:.1f}ms",
                tid,
                [h["hazard_type"] for h in sc.get("hazards", [])],
                delta_ms,
            )

    # Plan latency: time between SceneDescription emission and the matching
    # ActionPlan arriving on axon:plans (Layer D end-to-end wall-clock).
    if plan_total:
        plans = counts.get("_plans", []) or []
        scenes_by_id = {sc["trigger_id"]: sc for sc in (counts.get("_scenes", []) or [])}
        for pl in plans:
            tid = pl["trigger_id"]
            plan_ts = datetime.fromisoformat(pl["timestamp"].replace("Z", "+00:00"))
            sc = scenes_by_id.get(tid)
            if sc is None:
                logger.info("  plan trigger_id={} (no matching scene captured)", tid)
                continue
            scene_ts = datetime.fromisoformat(sc["timestamp"].replace("Z", "+00:00"))
            delta_ms = (plan_ts - scene_ts).total_seconds() * 1000
            actions = [a["action_id"] for a in pl.get("actions", [])]
            fallback = pl.get("audit_metadata", {}).get("fallback") is True
            logger.info(
                "  plan trigger_id={} severity={} confidence={:.2f} fallback={} "
                "actions={} latency_from_scene={:.1f}ms",
                tid, pl["severity"], pl["confidence"], fallback,
                actions, delta_ms,
            )

    # Layer 4 dispatch latency: ActionPlan → first audit entry for that trigger.
    if audit_total:
        audits = counts.get("_audits", []) or []
        plans_by_id = {pl["trigger_id"]: pl for pl in (counts.get("_plans", []) or [])}
        by_trigger: dict[str, list[dict]] = {}
        for a in audits:
            by_trigger.setdefault(a["trigger_id"], []).append(a)
        for tid, entries in by_trigger.items():
            pl = plans_by_id.get(tid)
            if pl is None:
                continue
            plan_ts = datetime.fromisoformat(pl["timestamp"].replace("Z", "+00:00"))
            first_audit_ts = min(
                datetime.fromisoformat(a["timestamp"].replace("Z", "+00:00"))
                for a in entries
            )
            last_audit_ts = max(
                datetime.fromisoformat(a["timestamp"].replace("Z", "+00:00"))
                for a in entries
            )
            actions = [a["action_id"] for a in pl.get("actions", [])]
            effects = {a["action_id"]: a["effect"] for a in entries}
            logger.info(
                "  dispatch trigger_id={} actions={} first_audit_delay={:.1f}ms "
                "all_audits_within={:.1f}ms effects={}",
                tid, actions,
                (first_audit_ts - plan_ts).total_seconds() * 1000,
                (last_audit_ts - plan_ts).total_seconds() * 1000,
                effects,
            )

    if slice_change_events:
        logger.info(
            "  slice WS reshape events: {}",
            [(e.get("event"), e.get("detail")) for e in slice_change_events],
        )

    if frame_total == 0 and cameras:
        logger.error("orchestrator: zero frames ingested for cameras={}", cameras)
        return 3
    if sensor_total == 0 and raw.get("sensors"):
        logger.error("orchestrator: zero sensor readings ingested")
        return 4
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", help="scenario name, e.g. 'mock_idle'")
    parser.add_argument("--redis-url", default="redis://localhost:6380/0")
    parser.add_argument("--mqtt-host", default="localhost")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--sensing-url", default="http://localhost:8001/health")
    parser.add_argument("--duration", type=int, default=None)
    args = parser.parse_args()
    rc = asyncio.run(
        run(
            args.scenario,
            redis_url=args.redis_url,
            mqtt_host=args.mqtt_host,
            mqtt_port=args.mqtt_port,
            sensing_url=args.sensing_url,
            duration_override=args.duration,
        )
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
