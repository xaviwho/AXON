"""Prometheus instrumentation for Layer 4 (action dispatcher)."""

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

# Buckets sized for: HTTP roundtrip (~ms), full-plan dispatch (~tens of ms),
# slow remote actuator (~hundreds of ms), timeout edge (~s).
_LATENCY_BUCKETS = (
    0.001, 0.005, 0.010, 0.020, 0.050, 0.100,
    0.250, 0.500, 1.000, 2.000, 5.000,
)


class ActionTelemetry:
    def __init__(self, service_name: str = "axon-action") -> None:
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        self.tracer = trace.get_tracer(service_name)

        self.registry = CollectorRegistry()
        self.action_latency = Histogram(
            "axon_action_dispatch_seconds",
            "Per-action handler latency",
            labelnames=("action_id", "effect"),
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.plan_latency = Histogram(
            "axon_action_plan_seconds",
            "Per-plan total dispatch latency (all actions in parallel)",
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.actions_total = Counter(
            "axon_action_actions_total",
            "Actions dispatched",
            labelnames=("action_id", "effect"),
            registry=self.registry,
        )
        self.plans_total = Counter(
            "axon_action_plans_total",
            "ActionPlans dispatched",
            registry=self.registry,
        )
        self.in_flight = Gauge(
            "axon_action_in_flight",
            "Plans being dispatched concurrently",
            registry=self.registry,
        )

    def render_prometheus(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


__all__ = ["ActionTelemetry"]
