"""Vision service entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from loguru import logger

from shared.bus import Bus
from shared.scenario import load_scenario

from .pipeline import VisionWorker
from .pose import PoseEstimator
from .settings import settings
from .telemetry import init_telemetry
from .yolo import YoloV10


@asynccontextmanager
async def lifespan(app: FastAPI):
    telemetry = init_telemetry(settings.service_name)
    scenario = load_scenario(settings.scenario_path)
    camera_ids = [c.id for c in scenario.cameras]
    logger.info(
        "vision starting scenario='{}' cameras={}",
        scenario.name, camera_ids,
    )

    bus = await Bus.connect(settings.redis_url)
    yolo = YoloV10(
        str(settings.yolo_onnx_path),
        input_size=settings.yolo_input_size,
        conf_threshold=settings.yolo_conf_threshold,
        provider=settings.onnx_provider,
    )
    pose = PoseEstimator(str(settings.pose_task_path))
    worker = VisionWorker(bus, camera_ids, yolo, pose, telemetry)
    await worker.start()

    app.state.bus = bus
    app.state.worker = worker
    app.state.telemetry = telemetry
    app.state.yolo = yolo
    app.state.pose = pose
    app.state.scenario = scenario
    try:
        yield
    finally:
        logger.info("vision shutting down")
        await worker.stop()
        pose.close()
        await bus.close()


app = FastAPI(title="axon-vision", lifespan=lifespan)


@app.get("/health")
def health(request: Request) -> dict:
    return {
        "service": settings.service_name,
        "status": "ok",
        "scenario": request.app.state.scenario.name,
        "redis_connected": request.app.state.bus.healthy,
        "yolo_provider": request.app.state.yolo.active_provider,
        "pipelines": request.app.state.worker.status(),
    }


@app.get("/metrics")
def metrics(request: Request) -> Response:
    body, content_type = request.app.state.telemetry.render_prometheus()
    return Response(content=body, media_type=content_type)
