"""Fusion service entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from loguru import logger

from shared.bus import Bus
from shared.scenario import load_scenario

from .fusion import FusionEngine
from .rules import load_config
from .settings import settings
from .telemetry import FusionTelemetry


@asynccontextmanager
async def lifespan(app: FastAPI):
    telemetry = FusionTelemetry(
        service_name=settings.service_name,
        activation_window=settings.activation_window_seconds,
    )
    config = load_config(settings.rules_path)
    if settings.cooldown_override_seconds is not None:
        logger.warning(
            "fusion: cooldown override active ({}s); for harness use only",
            settings.cooldown_override_seconds,
        )
        config = config.model_copy(
            update={"emission_cooldown_seconds": settings.cooldown_override_seconds}
        )
    scenario = load_scenario(settings.scenario_path)
    camera_ids = [c.id for c in scenario.cameras]

    logger.info(
        "fusion starting scenario='{}' cameras={} threshold={} cooldown={}s",
        scenario.name, camera_ids, config.trigger_threshold,
        config.emission_cooldown_seconds,
    )

    bus = await Bus.connect(settings.redis_url)
    engine = FusionEngine(
        bus,
        config,
        telemetry,
        camera_ids=camera_ids,
        eval_tick_ms=settings.eval_tick_ms,
    )
    await engine.start()

    app.state.bus = bus
    app.state.engine = engine
    app.state.telemetry = telemetry
    app.state.config = config
    app.state.scenario = scenario
    try:
        yield
    finally:
        logger.info("fusion shutting down")
        await engine.stop()
        await bus.close()


app = FastAPI(title="axon-fusion", lifespan=lifespan)


@app.get("/health")
def health(request: Request) -> dict:
    engine: FusionEngine = request.app.state.engine
    return {
        "service": settings.service_name,
        "status": "ok",
        "scenario": request.app.state.scenario.name,
        "redis_connected": request.app.state.bus.healthy,
        "engine_active": engine.active,
        "last_score": round(engine.last_score, 3),
        "last_trigger": (
            None if engine.last_emission is None else {
                "trigger_id": engine.last_emission.trigger_id,
                "trigger_reason": engine.last_emission.trigger_reason,
                "score": engine.last_emission.score,
            }
        ),
        "trigger_threshold": request.app.state.config.trigger_threshold,
        "rules": [r.id for r in request.app.state.config.rules],
    }


@app.get("/metrics")
def metrics(request: Request) -> Response:
    body, ct = request.app.state.telemetry.render_prometheus()
    return Response(content=body, media_type=ct)
