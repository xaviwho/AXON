"""OpenTelemetry tracing + Prometheus metrics for Layer A inference.

Every inference call goes through `inference_span(...)` and records its
latency on a Prometheus Histogram. The Prometheus registry is exposed at
`/metrics` on the FastAPI app.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

# Latency buckets cover the proposal's target range (15 ms) up to clearly
# unacceptable (1 s) so p95/p99 land in a useful bucket.
_LATENCY_BUCKETS = (
    0.005, 0.010, 0.015, 0.020, 0.025, 0.035, 0.050,
    0.075, 0.100, 0.150, 0.250, 0.500, 1.000,
)


class Telemetry:
    def __init__(self, service_name: str = "axon-vision") -> None:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        self.tracer = trace.get_tracer(service_name)

        self.registry = CollectorRegistry()
        self.inference_latency = Histogram(
            "axon_vision_inference_seconds",
            "Per-stage inference latency",
            labelnames=("stage",),
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.frames_total = Counter(
            "axon_vision_frames_total",
            "Frames consumed",
            labelnames=("camera_id",),
            registry=self.registry,
        )
        self.detections_total = Counter(
            "axon_vision_detections_total",
            "VisionDetections published",
            labelnames=("camera_id", "class_name"),
            registry=self.registry,
        )
        self.poses_total = Counter(
            "axon_vision_poses_total",
            "PoseObservations published",
            labelnames=("camera_id", "posture"),
            registry=self.registry,
        )

    @contextlib.contextmanager
    def inference_span(self, stage: str, camera_id: str) -> Iterator[None]:
        with self.tracer.start_as_current_span(f"vision.{stage}") as span:
            span.set_attribute("axon.stage", stage)
            span.set_attribute("axon.camera_id", camera_id)
            with self.inference_latency.labels(stage=stage).time():
                yield

    def render_prometheus(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


telemetry: Telemetry | None = None


def init_telemetry(service_name: str = "axon-vision") -> Telemetry:
    global telemetry
    if telemetry is None:
        telemetry = Telemetry(service_name)
    return telemetry
