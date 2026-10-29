"""Publishes synthetic sensor readings to mosquitto per a scenario YAML.

Each sensor can declare a `trace` block specifying how its value evolves
over time. Two trace kinds are supported:

  steady (default if no trace block is given)
      value = baseline + N(0, noise)

  spike
      value = baseline + N(0, noise)
      except during each [at_seconds, at_seconds + hold_seconds] window when
      value = spike_value (no noise) — for fire / gas / collapse events.

Usage:
    python -m demos.mock_data.sensor_simulator <scenario.yaml> \\
        --mqtt-host localhost --mqtt-port 1883 [--duration N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiomqtt
import yaml
from loguru import logger

from shared.schemas.enums import SensorType

if sys.platform == "win32":
    # aiomqtt needs loop.add_reader/add_writer, which Windows' default
    # Proactor loop lacks. Every demo entrypoint imports this module before
    # asyncio.run(), so the policy is in place when the loop is created.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DEFAULT_BASELINES: dict[SensorType, tuple[float, float, str]] = {
    SensorType.GAS: (0.2, 0.05, "ppm"),
    SensorType.THERMAL: (22.0, 0.3, "degC"),
    SensorType.ENV: (45.0, 1.0, "%RH"),
    SensorType.EQUIPMENT: (0.0, 0.01, "state"),
}


def _payload(value: float, unit: str, ts: datetime) -> bytes:
    return json.dumps(
        {"value": value, "unit": unit, "timestamp": ts.isoformat()}
    ).encode("utf-8")


def _trace_value(
    trace: dict[str, Any] | None,
    baseline: float,
    noise: float,
    elapsed: float,
    rng: random.Random,
) -> float:
    if not trace:
        return baseline + rng.gauss(0.0, noise)
    kind = trace.get("kind", "steady")
    base = trace.get("baseline", baseline)
    n = trace.get("noise", noise)
    if kind == "steady":
        return base + rng.gauss(0.0, n)
    if kind == "spike":
        for spike in trace.get("spikes", []):
            start = float(spike["at_seconds"])
            hold = float(spike.get("hold_seconds", 1.0))
            if start <= elapsed < start + hold:
                return float(spike["value"])
        return base + rng.gauss(0.0, n)
    raise ValueError(f"unknown sensor trace kind: {kind}")


async def run(
    scenario_path: Path,
    *,
    mqtt_host: str,
    mqtt_port: int,
    rate_hz: float = 2.0,
    duration_override: int | None = None,
) -> None:
    scenario = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    sensors = scenario.get("sensors") or []
    duration = duration_override or int(scenario.get("duration_seconds", 60))

    if not sensors:
        logger.info("simulator: scenario {} declares no sensors", scenario_path)
        return

    logger.info(
        "simulator: scenario={} duration={}s sensors={}",
        scenario.get("name"), duration, [s["id"] for s in sensors],
    )

    period = 1.0 / rate_hz
    start = time.monotonic()
    deadline = start + duration

    async with aiomqtt.Client(hostname=mqtt_host, port=mqtt_port) as client:
        rng = random.Random(0xA0E0)
        while time.monotonic() < deadline:
            elapsed = time.monotonic() - start
            now = datetime.now(timezone.utc)
            for s in sensors:
                sensor_type = SensorType(s["type"])
                baseline, default_noise, default_unit = DEFAULT_BASELINES[sensor_type]
                unit = s.get("unit", default_unit)
                value = _trace_value(s.get("trace"), baseline, default_noise, elapsed, rng)
                await client.publish(s["topic"], _payload(value, unit, now), qos=0)
            await asyncio.sleep(period)

    logger.info("simulator: finished {}s run", duration)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--mqtt-host", default="localhost")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--rate-hz", type=float, default=2.0)
    parser.add_argument("--duration", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(
        run(
            args.scenario,
            mqtt_host=args.mqtt_host,
            mqtt_port=args.mqtt_port,
            rate_hz=args.rate_hz,
            duration_override=args.duration,
        )
    )


if __name__ == "__main__":
    main()
