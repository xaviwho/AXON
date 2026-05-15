"""Sensing service entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from loguru import logger

from .bus import Bus
from .camera import CameraManager
from .mqtt_subscriber import MqttIngestor
from .scenario import load_scenario
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    scenario = load_scenario(settings.scenario_path)
    logger.info(
        "sensing starting scenario='{}' cameras={} sensors={}",
        scenario.name,
        [c.id for c in scenario.cameras],
        [s.id for s in scenario.sensors],
    )

    bus = await Bus.connect(
        settings.redis_url,
        frame_maxlen=settings.frame_stream_maxlen,
        sensor_maxlen=settings.sensor_stream_maxlen,
    )
    cameras = CameraManager(bus, scenario.cameras)
    mqtt = MqttIngestor(
        bus,
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        client_id=settings.mqtt_client_id,
        sensors=scenario.sensors,
    )

    await cameras.start()
    await mqtt.start()

    app.state.bus = bus
    app.state.cameras = cameras
    app.state.mqtt = mqtt
    app.state.scenario = scenario
    try:
        yield
    finally:
        logger.info("sensing shutting down")
        await cameras.stop()
        await mqtt.stop()
        await bus.close()


app = FastAPI(title="axon-sensing", lifespan=lifespan)


@app.get("/health")
def health(request: Request) -> dict:
    return {
        "service": settings.service_name,
        "status": "ok",
        "scenario": request.app.state.scenario.name,
        "redis_connected": request.app.state.bus.healthy,
        "mqtt_connected": request.app.state.mqtt.connected,
        "cameras": request.app.state.cameras.status(),
    }
