"""Rules editor — reads + writes the fusion rules YAML.

GET is open; PUT requires admin JWT. PUT validates the new content
against the fusion service's own schema before writing, so the file on
disk is never left in a state that would crash fusion.
"""

from __future__ import annotations

from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request

from services.fusion.app.rules import FusionConfig

from ..auth import require_admin
from ..settings import settings

router = APIRouter()


@router.get("/rules")
async def get_rules() -> dict:
    text = settings.rules_path.read_text(encoding="utf-8")
    return {
        "path": str(settings.rules_path),
        "yaml": text,
        "parsed": yaml.safe_load(text),
    }


@router.put("/rules")
async def put_rules(
    body: dict,
    _admin: Annotated[dict, Depends(require_admin)],
) -> dict:
    new_yaml = body.get("yaml")
    if not isinstance(new_yaml, str) or not new_yaml.strip():
        raise HTTPException(status_code=400, detail="body must include non-empty 'yaml' field")
    try:
        parsed = yaml.safe_load(new_yaml)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"invalid YAML: {exc}") from exc
    try:
        FusionConfig(**parsed)
    except Exception as exc:    # noqa: BLE001 — surface pydantic + everything else cleanly
        raise HTTPException(status_code=400, detail=f"invalid fusion config: {exc}") from exc

    settings.rules_path.write_text(new_yaml, encoding="utf-8")
    return {
        "status": "ok",
        "path": str(settings.rules_path),
        "reload_required": True,
        "note": "restart the fusion service to load the new rules",
    }
