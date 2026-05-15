"""Multiplexed WebSocket — relays bus events + slice-state events to the dashboard.

Clients connect once; the server fans them out anomaly / scene / plan /
audit / alert events from the bus tailer, plus pass-through messages
from the slice-control mock's WebSocket. The dashboard renders all of
them with no further round-tripping.
"""

from __future__ import annotations

import asyncio
import json

import websockets
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from loguru import logger

from ..settings import settings

router = APIRouter()


async def _slice_relay(hub, stop: asyncio.Event) -> None:
    """Reconnecting relay from the slice-control WebSocket into the hub."""
    base = settings.service_urls["slice_control_mock"].replace("http", "ws")
    url = f"{base}/ws"
    backoff = 1.0
    while not stop.is_set():
        try:
            async with websockets.connect(url) as ws:
                logger.info("slice WS relay connected: {}", url)
                backoff = 1.0
                while not stop.is_set():
                    text = await ws.recv()
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    hub.publish("slice", payload)
        except (OSError, websockets.WebSocketException) as exc:
            logger.warning("slice WS relay disconnected ({}); retry in {}s", exc, backoff)
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 30.0)


@router.websocket("/live")
async def live_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    hub = websocket.app.state.hub
    queue = hub.subscribe()
    try:
        # Send a hello + recent snapshot so a late-joining client has context.
        await websocket.send_json({"event": "hello",
                                   "payload": {"snapshot": hub.snapshot(limit=50)}})
        while True:
            msg = await queue.get()
            await websocket.send_json(msg)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(queue)
