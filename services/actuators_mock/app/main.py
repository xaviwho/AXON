"""Mock equipment / door / HVAC actuator endpoints.

Stand-in for the customer-side IoT control plane that the AXON dispatcher
talks to over HTTP. Each endpoint records the call in-memory and returns
success. In production these endpoints are physically distinct services
provided by the customer; we mock them here to verify the dispatcher's
contract surface.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

_HISTORY: list[dict] = []


class PowerCutoffRequest(BaseModel):
    zone_id: str = Field(min_length=1)
    equipment_ids: list[str] | None = None


class DoorRequest(BaseModel):
    zone_id: str = Field(min_length=1)


class HVACRequest(BaseModel):
    zone_id: str = Field(min_length=1)


def _record(kind: str, zone: str, params: dict) -> dict:
    entry = {
        "kind": kind,
        "zone_id": zone,
        "parameters": params,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _HISTORY.append(entry)
    if len(_HISTORY) > 1000:
        del _HISTORY[: len(_HISTORY) - 1000]
    logger.info("actuators_mock {} zone={} params={}", kind, zone, params)
    return entry


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("actuators_mock starting")
    yield


app = FastAPI(title="axon-actuators-mock", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"service": "actuators_mock", "status": "ok", "call_count": len(_HISTORY)}


@app.get("/history")
def history(limit: int = 50) -> list[dict]:
    return _HISTORY[-limit:]


@app.post("/equipment/power_cutoff")
def power_cutoff(req: PowerCutoffRequest) -> dict:
    entry = _record("power_cutoff", req.zone_id,
                    {"equipment_ids": req.equipment_ids or []})
    return {"status": "ok", "applied": entry}


@app.post("/door/lock")
def door_lock(req: DoorRequest) -> dict:
    entry = _record("door_lock", req.zone_id, {})
    return {"status": "ok", "applied": entry}


@app.post("/door/unlock")
def door_unlock(req: DoorRequest) -> dict:
    entry = _record("door_unlock", req.zone_id, {})
    return {"status": "ok", "applied": entry}


@app.post("/hvac/isolate")
def hvac_isolate(req: HVACRequest) -> dict:
    entry = _record("hvac_isolate", req.zone_id, {})
    return {"status": "ok", "applied": entry}


@app.post("/failure/{kind}/{zone}")
def trigger_failure(kind: str, zone: str) -> dict:
    """Test hook: fail-injection used by dispatcher tests."""
    raise HTTPException(status_code=500, detail=f"simulated failure: {kind} {zone}")
