"""AXON service template. Copy this directory to bootstrap a new layer service."""

import os

from fastapi import FastAPI
from loguru import logger
from pydantic import BaseModel

SERVICE_NAME = os.environ.get("AXON_SERVICE_NAME", "template")

app = FastAPI(title=f"axon-{SERVICE_NAME}")


class HealthResponse(BaseModel):
    service: str
    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(service=SERVICE_NAME, status="ok")


@app.on_event("startup")
def _startup() -> None:
    logger.info("axon service '{}' starting", SERVICE_NAME)
