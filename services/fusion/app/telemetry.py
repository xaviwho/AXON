"""Prometheus + OpenTelemetry instrumentation for Layer B."""

from __future__ import annotations

import time
from collections import deque

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
    generate_latest,
)


class FusionTelemetry:
    def __init__(self, service_name: str = "axon-fusion", activation_window: int = 60) -> None:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        self.tracer = trace.get_tracer(service_name)

        self.registry = CollectorRegistry()
        self.composite_score = Gauge(
            "axon_fusion_score",
            "Current composite anomaly score in [0, 1]",
            registry=self.registry,
        )
        self.activations_total = Counter(
            "axon_fusion_activations_total",
            "Number of AnomalyScore emissions (threshold crossings, post-cooldown)",
            registry=self.registry,
        )
        self.rule_contributions_total = Counter(
            "axon_fusion_rule_contributions_total",
            "Times each rule contributed a non-zero weight to an evaluation",
            labelnames=("rule_id",),
            registry=self.registry,
        )
        self.activation_rate = Gauge(
            "axon_fusion_activation_rate",
            "Fraction of recent evaluations whose score exceeded the trigger threshold",
            registry=self.registry,
        )
        self.evaluations_total = Counter(
            "axon_fusion_evaluations_total",
            "Total evaluations performed",
            registry=self.registry,
        )

        self._activation_window = activation_window
        self._eval_history: deque[tuple[float, bool]] = deque()

    def record_evaluation(self, score: float, above_threshold: bool) -> None:
        now = time.monotonic()
        self.evaluations_total.inc()
        self.composite_score.set(score)
        self._eval_history.append((now, above_threshold))
        cutoff = now - self._activation_window
        while self._eval_history and self._eval_history[0][0] < cutoff:
            self._eval_history.popleft()
        if self._eval_history:
            rate = sum(1 for _, a in self._eval_history if a) / len(self._eval_history)
            self.activation_rate.set(rate)

    def render_prometheus(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


__all__ = ["FusionTelemetry"]
