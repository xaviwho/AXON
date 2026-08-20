"""Shared plumbing for the in-process benchmarks.

Each benchmark instantiates the real ``ActionDispatcher`` and drives it
through an ASGI-mounted pair of mocks (``actuators_mock`` +
``slice_control_mock``). This is the same pattern the existing tests use;
the only difference is that we time it and capture outputs.

No Docker, no Redis, no network — the numbers reproduce on any machine
with the dev-extras installed. That reproducibility is intentional: the
paper needs numbers a reviewer can regenerate.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Deterministic HMAC key for every benchmark run so the signing overhead
# and verify-round-trip numbers are reproducible.
os.environ.setdefault("AXON_AUDIT_SIGNING_KEY", "b" * 64)

NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


class MemoryBus:
    """Bus stub matching the surface `ActionDispatcher` touches for tests."""

    healthy = True

    def __init__(self) -> None:
        self.alerts: list[dict] = []
        self.audits: list[dict] = []

    async def publish_alert(self, payload):
        self.alerts.append(payload)

    async def publish_audit(self, payload):
        self.audits.append(payload)


class MultiHostTransport(httpx.AsyncBaseTransport):
    """Route httpx requests to the actuators or slice ASGI app by host substring."""

    def __init__(self) -> None:
        from services.actuators_mock.app.main import app as actuators_app
        from services.slice_control_mock.app.main import app as slice_app

        self._slice = httpx.ASGITransport(app=slice_app)
        self._actuators = httpx.ASGITransport(app=actuators_app)

    async def handle_async_request(self, request):
        host = request.url.host or ""
        if "slice" in host:
            return await self._slice.handle_async_request(request)
        return await self._actuators.handle_async_request(request)


@dataclass
class DispatcherHandle:
    dispatcher: object
    bus: MemoryBus
    http: httpx.AsyncClient

    async def close(self) -> None:
        await self.http.aclose()


async def make_dispatcher(*, network_mode: str = "urllc",
                          base_ms: float = 0.0, jitter_ms: float = 0.0):
    from services.action.app.dispatcher import ActionDispatcher, NetworkMode
    from services.action.app.telemetry import ActionTelemetry
    from shared.action_library import ActionLibrary

    http = httpx.AsyncClient(transport=MultiHostTransport(), timeout=5.0)
    bus = MemoryBus()
    tel = ActionTelemetry()
    net = NetworkMode()
    net.configure(mode=network_mode, base_ms=base_ms, jitter_ms=jitter_ms)
    d = ActionDispatcher(
        bus=bus, http=http, telemetry=tel,
        library=ActionLibrary.load(),
        actuators_url="http://actuators-mock:8000",
        slice_control_url="http://slice-control-mock:8000",
        timeout_seconds=5.0, max_concurrent_plans=8,
        network=net,
    )
    return DispatcherHandle(dispatcher=d, bus=bus, http=http)


def anomaly(trigger_id: str, reason: str, score: float = 0.7):
    from shared.schemas.anomaly import AnomalyScore, ContributingSignal

    return AnomalyScore(
        composite_score=score,
        contributing_signals=[
            ContributingSignal(source="sensor:thermal", weight=score, description=reason),
        ],
        threshold_exceeded=True,
        trigger_reason=reason,
        trigger_id=trigger_id,
        timestamp=NOW,
    )


def percentile(xs, q: float) -> float:
    return float(np.percentile(xs, q)) if xs else float("nan")


def savefig(fig, name: str) -> Path:
    out = RESULTS_DIR / name
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out


def dump_json(name: str, data) -> Path:
    out = RESULTS_DIR / name
    out.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return out


# Palette matching the existing latency.png so plots read as a family.
COLORS = {
    "urllc": "#1e3a8a",
    "wifi": "#dc2626",
    "wifi_heavy": "#7c2d12",
    "phase1": "#1e3a8a",
    "phase2": "#0891b2",
    "success": "#16a34a",
    "failure": "#dc2626",
    "timeout": "#ea580c",
    "semantic": "#7c3aed",
    "keyword": "#64748b",
}


def run(coro):
    return asyncio.run(coro)
