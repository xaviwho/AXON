"""Prometheus instrumentation for Layer C."""

from __future__ import annotations

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
    Gauge,
    Histogram,
    generate_latest,
)

# Buckets span the Jetson Orin (1.2–1.8 s), RTX 4090 (0.6–0.9 s), stub
# (~ms) and degraded (≥ several s) regimes so all show up in a useful place.
_LATENCY_BUCKETS = (
    0.005, 0.010, 0.025, 0.050, 0.100, 0.250,
    0.500, 0.750, 1.000, 1.500, 2.000, 3.000, 5.000, 10.000,
)


class VLMTelemetry:
    def __init__(self, service_name: str = "axon-vlm") -> None:
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        self.tracer = trace.get_tracer(service_name)

        self.registry = CollectorRegistry()
        self.generation_latency = Histogram(
            "axon_vlm_generation_seconds",
            "End-to-end Layer C generation latency",
            labelnames=("mode", "outcome"),
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.scenes_total = Counter(
            "axon_vlm_scenes_total",
            "SceneDescriptions published",
            labelnames=("mode", "outcome"),
            registry=self.registry,
        )
        self.in_flight = Gauge(
            "axon_vlm_in_flight",
            "Current number of triggers being processed concurrently",
            registry=self.registry,
        )
        self.queue_overflow_total = Counter(
            "axon_vlm_queue_overflow_total",
            "Triggers dropped due to the concurrency cap saturating beyond limit",
            registry=self.registry,
        )

    def render_prometheus(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


__all__ = ["VLMTelemetry"]
