"""Prometheus instrumentation for Layer D."""

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

_LATENCY_BUCKETS = (
    0.005, 0.010, 0.025, 0.050, 0.100, 0.250,
    0.500, 0.750, 1.000, 1.500, 2.000, 3.000, 5.000, 10.000,
)


class AgentTelemetry:
    def __init__(self, service_name: str = "axon-agent") -> None:
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        self.tracer = trace.get_tracer(service_name)

        self.registry = CollectorRegistry()
        self.plan_latency = Histogram(
            "axon_agent_plan_seconds",
            "End-to-end Layer D plan-generation latency",
            labelnames=("mode", "outcome"),
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.plans_total = Counter(
            "axon_agent_plans_total",
            "ActionPlans published",
            labelnames=("mode", "outcome"),
            registry=self.registry,
        )
        self.in_flight = Gauge(
            "axon_agent_in_flight",
            "Current scenes being processed concurrently",
            registry=self.registry,
        )
        self.parse_failures_total = Counter(
            "axon_agent_parse_failures_total",
            "Times the model returned output that failed schema or library validation",
            registry=self.registry,
        )
        self.fallbacks_total = Counter(
            "axon_agent_fallbacks_total",
            "Times the rule-based safety protocol replaced the model plan",
            labelnames=("reason",),
            registry=self.registry,
        )

    def render_prometheus(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


__all__ = ["AgentTelemetry"]
