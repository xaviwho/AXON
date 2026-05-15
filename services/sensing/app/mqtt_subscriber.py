"""MQTT subscriber.

Subscribes to each configured sensor's topic on the mosquitto broker. Inbound
JSON messages are parsed into SensorReading and forwarded to the bus. Same
code path will work against the customer's real broker at the testbed; we
just change the host/port via env.

Wire format expected on each topic:
    {"value": <float>, "unit": "<str>", "timestamp": "<iso8601>"}

The sensor_id and sensor_type come from the scenario's SensorConfig binding;
the simulator (demos/mock_data/sensor_simulator.py) writes the same shape.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import aiomqtt
from loguru import logger
from pydantic import ValidationError

from shared.schemas.sensors import SensorReading

from .bus import Bus
from .scenario import SensorConfig


class MqttIngestor:
    def __init__(
        self,
        bus: Bus,
        host: str,
        port: int,
        client_id: str,
        sensors: list[SensorConfig],
    ) -> None:
        self.bus = bus
        self.host = host
        self.port = port
        self.client_id = client_id
        self._by_topic = {s.topic: s for s in sensors}
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.connected = False

    async def start(self) -> None:
        if not self._by_topic:
            logger.info("mqtt ingestor: no sensors configured, skipping")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="mqtt-ingestor")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except asyncio.TimeoutError:
                self._task.cancel()

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=self.host,
                    port=self.port,
                    identifier=self.client_id,
                ) as client:
                    self.connected = True
                    backoff = 1.0
                    for topic in self._by_topic:
                        await client.subscribe(topic)
                        logger.info("mqtt subscribed: {}", topic)

                    async for msg in client.messages:
                        if self._stop.is_set():
                            break
                        await self._handle(str(msg.topic), bytes(msg.payload))
            except aiomqtt.MqttError as exc:
                self.connected = False
                if self._stop.is_set():
                    break
                logger.warning("mqtt error: {} — reconnecting in {}s", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
        self.connected = False

    async def _handle(self, topic: str, payload: bytes) -> None:
        cfg = self._by_topic.get(topic)
        if cfg is None:
            logger.debug("mqtt: dropping message on unsubscribed topic {}", topic)
            return
        try:
            raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("mqtt: bad payload on {}: {}", topic, exc)
            return

        ts_raw = raw.get("timestamp")
        if ts_raw is None:
            ts = datetime.now(timezone.utc)
        else:
            try:
                ts = datetime.fromisoformat(ts_raw)
            except ValueError:
                ts = datetime.now(timezone.utc)

        try:
            reading = SensorReading(
                sensor_id=cfg.id,
                sensor_type=cfg.type,
                value=float(raw["value"]),
                unit=raw.get("unit", cfg.unit),
                timestamp=ts,
            )
        except (KeyError, ValueError, ValidationError) as exc:
            logger.warning("mqtt: invalid sensor reading on {}: {}", topic, exc)
            return

        await self.bus.publish_sensor(reading.model_dump(mode="json"))
