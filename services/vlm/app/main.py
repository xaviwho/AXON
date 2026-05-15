"""VLM service entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from loguru import logger

from shared.bus import Bus

from .client import make_client
from .consumer import SceneConsumer
from .settings import settings
from .telemetry import VLMTelemetry


@asynccontextmanager
async def lifespan(app: FastAPI):
    telemetry = VLMTelemetry(service_name=settings.service_name)
    bus = await Bus.connect(settings.redis_url)
    client = make_client(
        mode=settings.vlm_mode,
        base_url=settings.vlm_url,
        model=settings.vlm_model,
        api_key=settings.vlm_api_key,
        timeout_seconds=settings.vlm_timeout_seconds,
        temperature=settings.vlm_temperature,
        max_parse_retries=settings.max_parse_retries,
    )
    consumer = SceneConsumer(
        bus=bus,
        client=client,
        telemetry=telemetry,
        max_concurrent=settings.max_concurrent_triggers,
        keyframes_per_trigger=settings.keyframes_per_trigger,
    )
    await consumer.start()

    app.state.bus = bus
    app.state.client = client
    app.state.consumer = consumer
    app.state.telemetry = telemetry
    logger.info(
        "vlm service started: mode={} max_concurrent={}",
        client.mode, settings.max_concurrent_triggers,
    )
    try:
        yield
    finally:
        logger.info("vlm shutting down")
        await consumer.stop()
        await bus.close()


app = FastAPI(title="axon-vlm", lifespan=lifespan)


@app.get("/health")
def health(request: Request) -> dict:
    c: SceneConsumer = request.app.state.consumer
    return {
        "service": settings.service_name,
        "status": "ok",
        "mode": request.app.state.client.mode,
        "redis_connected": request.app.state.bus.healthy,
        "consumer_active": c.active,
        "processed_total": c.processed_total,
        "last_trigger_id": c.last_trigger_id,
        "max_concurrent": settings.max_concurrent_triggers,
    }


@app.get("/metrics")
def metrics(request: Request) -> Response:
    body, ct = request.app.state.telemetry.render_prometheus()
    return Response(content=body, media_type=ct)
