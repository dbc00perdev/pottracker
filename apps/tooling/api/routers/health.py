"""Health endpoint — no auth (used by monitoring)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.tooling.api.config import API_VERSION
from apps.tooling.api.db import get_session
from apps.tooling.api.schemas.audit import HealthMachine, HealthResponse
from apps.tooling.api.services import machines

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(session: Session = Depends(get_session)) -> HealthResponse:
    rows = machines.health(session)
    return HealthResponse(
        status="ok",
        version=API_VERSION,
        machines=[HealthMachine(**r) for r in rows],
    )
