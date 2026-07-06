"""Audit + health schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from apps.tooling.api.schemas.common import ORMModel


class AuditOut(ORMModel):
    id: int
    occurred_at: datetime
    user_id: UUID | None = None
    machine_id: UUID | None = None
    event_type: str
    entity_type: str
    entity_id: str
    before_value: dict[str, Any] | None = None
    after_value: dict[str, Any] | None = None
    reason: str | None = None
    success: bool
    error: str | None = None


class HealthMachine(BaseModel):
    id: UUID
    name: str
    focas_connected: bool
    last_polled_at: datetime | None = None
    lag_seconds: float | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    machines: list[HealthMachine]
