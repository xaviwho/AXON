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

        # Lifetime scalars exposed via `snapshot()` for the /gating endpoint
        # and for direct read-out by the latency harness. These mirror the
        # corresponding Prometheus counters so the harness does not need to
        # scrape and parse the /metrics text format between runs.
        self._eval_count = 0
        self._over_count = 0
        self._activation_count = 0

    def record_evaluation(self, score: float, above_threshold: bool) -> None:
        now = time.monotonic()
        self.evaluations_total.inc()
        self.composite_score.set(score)
        self._eval_count += 1
        if above_threshold:
            self._over_count += 1
        self._eval_history.append((now, above_threshold))
        cutoff = now - self._activation_window
        while self._eval_history and self._eval_history[0][0] < cutoff:
            self._eval_history.popleft()
        if self._eval_history:
            rate = sum(1 for _, a in self._eval_history if a) / len(self._eval_history)
            self.activation_rate.set(rate)

    def record_activation(self) -> None:
        """Called once per emitted AnomalyScore (post-cooldown gate crossing)."""
        self.activations_total.inc()
        self._activation_count += 1

    def snapshot(self) -> dict[str, float | int]:
        """Read-out for the /gating endpoint and the latency harness.

        ``gate_ratio`` is Pr[gamma(t) = 1] per methodology Eq. (6): the
        share of evaluation ticks that emit (both threshold-crossing AND
        cooldown-elapsed). ``over_threshold_ratio`` is the pre-cooldown
        share for callers that want to reason about the raw rule-hit rate.
        """
        return {
            "evaluations_total": self._eval_count,
            "over_threshold_total": self._over_count,
            "activations_total": self._activation_count,
            "over_threshold_ratio": (
                self._over_count / self._eval_count if self._eval_count else 0.0
            ),
            "gate_ratio": (
                self._activation_count / self._eval_count if self._eval_count else 0.0
            ),
        }

    def render_prometheus(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


__all__ = ["FusionTelemetry"]
