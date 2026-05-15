"""Console API entrypoint — Layer 5 backend."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from shared.bus import Bus

from .db import AuditDB
from .persistence import BusPersister, EventHub
from .routes.audit import router as audit_router
from .routes.auth_router import router as auth_router
from .routes.live import _slice_relay, router as live_router
from .routes.rules import router as rules_router
from .routes.status import router as status_router
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = AuditDB(settings.sqlite_path)
    hub = EventHub()
    bus = await Bus.connect(settings.redis_url)
    http = httpx.AsyncClient()
    persister = BusPersister(bus=bus, db=db, hub=hub)
    await persister.start()

    slice_stop = asyncio.Event()
    slice_task = asyncio.create_task(
        _slice_relay(hub, slice_stop), name="slice-ws-relay"
    )

    app.state.db = db
    app.state.bus = bus
    app.state.http = http
    app.state.hub = hub
    app.state.persister = persister
    logger.info("console_api started")
    try:
        yield
    finally:
        logger.info("console_api shutting down")
        slice_stop.set()
        slice_task.cancel()
        try:
            await slice_task
        except (asyncio.CancelledError, Exception):
            pass
        await persister.stop()
        await http.aclose()
        await bus.close()
        await db.close()


app = FastAPI(title="axon-console-api", lifespan=lifespan)

# Frontend is a separate origin during dev; allow it freely.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(audit_router)
app.include_router(rules_router)
app.include_router(status_router)
app.include_router(live_router)
app.include_router(auth_router)


@app.get("/health")
def health() -> dict:
    return {"service": settings.service_name, "status": "ok"}
