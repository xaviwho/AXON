"""Audit + incident routes — read-only, anyone-can-call."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

router = APIRouter()


def _db(request: Request):
    return request.app.state.db


@router.get("/audit")
async def list_audit(
    request: Request,
    severity: Annotated[int | None, Query(ge=0, le=5)] = None,
    action_id: str | None = None,
    trigger_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    entries, total = await _db(request).list_audits(
        severity=severity, action_id=action_id, trigger_id=trigger_id,
        start=start, end=end, limit=limit, offset=offset,
    )
    return {"total": total, "limit": limit, "offset": offset, "entries": entries}


@router.get("/audit/{audit_id}")
async def get_audit(request: Request, audit_id: int):
    entry = await _db(request).get_audit(audit_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"audit entry {audit_id} not found")
    return entry


@router.get("/incidents")
async def list_incidents(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
):
    return {"incidents": await _db(request).recent_incidents(limit=limit)}


@router.get("/incidents/{trigger_id}")
async def get_incident(request: Request, trigger_id: str):
    incident = await _db(request).get_incident(trigger_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"incident {trigger_id} not found")
    return incident
