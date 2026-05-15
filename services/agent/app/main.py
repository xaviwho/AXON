"""Agent service entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from loguru import logger

from shared.action_library import ActionLibrary
from shared.bus import Bus

from .client import make_client
from .consumer import PlanConsumer
from .rag import KnowledgeBase
from .settings import settings
from .telemetry import AgentTelemetry


@asynccontextmanager
async def lifespan(app: FastAPI):
    telemetry = AgentTelemetry(service_name=settings.service_name)
    library = ActionLibrary.load()
    knowledge_base = KnowledgeBase.load(settings.knowledge_base_dir)
    logger.info(
        "agent: loaded {} action(s), {} kb section(s)",
        len(library.names()), len(knowledge_base),
    )

    bus = await Bus.connect(settings.redis_url)
    client = make_client(
        mode=settings.llm_mode,
        library=library,
        base_url=settings.llm_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        temperature=settings.llm_temperature,
        max_parse_retries=settings.max_parse_retries,
        confidence_floor=settings.confidence_floor,
    )
    consumer = PlanConsumer(
        bus=bus,
        client=client,
        knowledge_base=knowledge_base,
        library=library,
        telemetry=telemetry,
        max_concurrent=settings.max_concurrent_scenes,
        rag_max_sections=settings.rag_max_sections,
    )
    await consumer.start()

    app.state.bus = bus
    app.state.client = client
    app.state.consumer = consumer
    app.state.telemetry = telemetry
    app.state.library = library
    app.state.knowledge_base = knowledge_base
    logger.info(
        "agent service started: mode={} max_concurrent={}",
        client.mode, settings.max_concurrent_scenes,
    )
    try:
        yield
    finally:
        logger.info("agent shutting down")
        await consumer.stop()
        await bus.close()


app = FastAPI(title="axon-agent", lifespan=lifespan)


@app.get("/health")
def health(request: Request) -> dict:
    c: PlanConsumer = request.app.state.consumer
    return {
        "service": settings.service_name,
        "status": "ok",
        "mode": request.app.state.client.mode,
        "redis_connected": request.app.state.bus.healthy,
        "consumer_active": c.active,
        "processed_total": c.processed_total,
        "last_trigger_id": c.last_trigger_id,
        "max_concurrent": settings.max_concurrent_scenes,
        "library_size": len(request.app.state.library.names()),
        "kb_sections": len(request.app.state.knowledge_base),
        "confidence_floor": settings.confidence_floor,
    }


@app.get("/metrics")
def metrics(request: Request) -> Response:
    body, ct = request.app.state.telemetry.render_prometheus()
    return Response(content=body, media_type=ct)
