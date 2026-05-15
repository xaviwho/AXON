"""Mock HFR Ieum 5G+ slice-control API.

Surface chosen to match the proposal's expected real API so swapping the
backend at HFR-mentorship time is just changing the URL. The WebSocket
at /ws is what the AXON Console (Prompt 8) tails to visualize live
reshapes during a demo.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, Field

from .state import SliceStore

_STORE = SliceStore()


class PriorityChange(BaseModel):
    priority: int = Field(ge=1, le=10)


class PreemptRequest(BaseModel):
    duration_seconds: int = Field(ge=1, le=3600)
    reason: str = Field(min_length=1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("slice_control_mock starting")
    app.state.store = _STORE
    yield
    logger.info("slice_control_mock shutting down")


app = FastAPI(title="axon-slice-control-mock", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"service": "slice_control_mock", "status": "ok",
            "subscribers": len(_STORE._subscribers),
            "revision": _STORE.state.revision}


@app.get("/slices/state")
def get_state() -> dict:
    return _STORE.snapshot()


@app.post("/slices/{slice_id}/priority")
async def set_priority(slice_id: str, body: PriorityChange) -> dict:
    if slice_id not in ("eMBB", "URLLC", "mMTC"):
        raise HTTPException(status_code=404, detail=f"unknown slice '{slice_id}'")
    state = await _STORE.set_priority(slice_id, body.priority)
    return state.model_dump(mode="json")


@app.post("/slices/preempt")
async def preempt(body: PreemptRequest) -> dict:
    state = await _STORE.preempt(body.duration_seconds, body.reason)
    return state.model_dump(mode="json")


@app.post("/slices/preempt/clear")
async def clear_preempt() -> dict:
    state = await _STORE.clear_preempt()
    return state.model_dump(mode="json")


@app.websocket("/ws")
async def ws_state(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = _STORE.subscribe()
    try:
        # Initial snapshot for late joiners.
        await websocket.send_json({
            "event": "snapshot",
            "detail": {},
            "state": _STORE.snapshot(),
        })
        while True:
            payload = await queue.get()
            await websocket.send_text(payload)
    except WebSocketDisconnect:
        pass
    finally:
        _STORE.unsubscribe(queue)
