"""Roll-up status endpoint — hits each service's /health concurrently."""

from __future__ import annotations

import asyncio
import time

import httpx
from fastapi import APIRouter, Request

from ..settings import settings

router = APIRouter()


async def _probe(http: httpx.AsyncClient, name: str, base: str) -> dict:
    start = time.monotonic()
    try:
        r = await http.get(f"{base}/health", timeout=settings.health_timeout_seconds)
        elapsed_ms = (time.monotonic() - start) * 1000
        if r.status_code // 100 == 2:
            body = r.json()
            return {
                "name": name, "status": "ok", "latency_ms": round(elapsed_ms, 1),
                "detail": body,
            }
        return {
            "name": name, "status": "error",
            "latency_ms": round(elapsed_ms, 1),
            "detail": {"http_status": r.status_code, "body": r.text[:200]},
        }
    except httpx.HTTPError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "name": name, "status": "unreachable",
            "latency_ms": round(elapsed_ms, 1),
            "detail": {"error": str(exc)},
        }


@router.get("/status")
async def status(request: Request) -> dict:
    http: httpx.AsyncClient = request.app.state.http
    probes = await asyncio.gather(
        *(_probe(http, name, base) for name, base in settings.service_urls.items())
    )
    db_counts = await request.app.state.db.counts()
    return {
        "services": probes,
        "db": db_counts,
        "recent_events": request.app.state.hub.snapshot(limit=20),
    }
