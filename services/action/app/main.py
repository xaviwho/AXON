"""Action dispatcher entrypoint."""

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from loguru import logger
from pydantic import BaseModel, Field

from shared.action_library import ActionLibrary
from shared.bus import Bus

from .dispatcher import ActionDispatcher, NetworkMode
from .settings import settings
from .telemetry import ActionTelemetry


class NetworkModeRequest(BaseModel):
    mode: str = Field(pattern="^(urllc|wifi)$")
    base_ms: float = Field(default=0.0, ge=0.0, le=2000.0)
    jitter_ms: float = Field(default=0.0, ge=0.0, le=2000.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    telemetry = ActionTelemetry(service_name=settings.service_name)
    library = ActionLibrary.load()
    bus = await Bus.connect(settings.redis_url)
    # One persistent HTTP client for the whole service — connection pooling
    # is what keeps per-action latency under our 50 ms plan budget.
    http = httpx.AsyncClient(timeout=settings.http_timeout_seconds)
    dispatcher = ActionDispatcher(
        bus=bus,
        http=http,
        telemetry=telemetry,
        library=library,
        actuators_url=settings.actuators_url,
        slice_control_url=settings.slice_control_url,
        timeout_seconds=settings.http_timeout_seconds,
        max_concurrent_plans=settings.max_concurrent_plans,
        phase1_zone=settings.phase1_zone,
        phase1_enabled=settings.phase1_enabled,
    )
    await dispatcher.start()

    app.state.bus = bus
    app.state.http = http
    app.state.dispatcher = dispatcher
    app.state.telemetry = telemetry
    logger.info("action dispatcher started")
    try:
        yield
    finally:
        logger.info("action dispatcher shutting down")
        await dispatcher.stop()
        await http.aclose()
        await bus.close()


app = FastAPI(title="axon-action", lifespan=lifespan)


@app.get("/health")
def health(request: Request) -> dict:
    d: ActionDispatcher = request.app.state.dispatcher
    return {
        "service": settings.service_name,
        "status": "ok",
        "redis_connected": request.app.state.bus.healthy,
        "active": d.active,
        "processed_total": d.processed_total,
        "phase1_total": d.phase1_total,
        "phase2_total": d.phase2_total,
        "phase1_enabled": d.phase1_enabled,
        "last_trigger_id": d.last_trigger_id,
        "max_concurrent_plans": settings.max_concurrent_plans,
        "actuators_url": settings.actuators_url,
        "slice_control_url": settings.slice_control_url,
        "network": d.network.snapshot(),
    }


@app.post("/admin/network")
def set_network(request: Request, body: NetworkModeRequest) -> dict:
    """Flip the dispatcher between URLLC (no-op) and Wi-Fi (delayed) modes.

    Used by demos/scenarios/wifi_vs_5g.py to compare end-to-end action
    latency under matching workload but different network conditions.
    """
    d: ActionDispatcher = request.app.state.dispatcher
    d.network.configure(mode=body.mode, base_ms=body.base_ms, jitter_ms=body.jitter_ms)
    logger.info("network mode flipped: {}", d.network.snapshot())
    return d.network.snapshot()


@app.get("/metrics")
def metrics(request: Request) -> Response:
    body, ct = request.app.state.telemetry.render_prometheus()
    return Response(content=body, media_type=ct)
