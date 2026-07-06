"""Assignment schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from apps.tooling.api.schemas.common import ORMModel


class AssignmentCreate(BaseModel):
    tool_id: UUID
    machine_id: UUID
    t_number: int = Field(ge=1)
    h_register: int = Field(ge=1)
    d_register: int | None = Field(default=None, ge=1)


class AssignmentUpdate(BaseModel):
    """PATCH register assignment — triggers re-confirmation."""

    t_number: int | None = Field(default=None, ge=1)
    h_register: int | None = Field(default=None, ge=1)
    d_register: int | None = Field(default=None, ge=1)


class ConfirmRequest(BaseModel):
    reason: str | None = None


class AssignmentOut(ORMModel):
    id: UUID
    tool_id: UUID
    tool_short_id: str
    machine_id: UUID
    machine_name: str
    t_number: int
    h_register: int
    d_register: int | None = None
    cached_h_geom_mm: Decimal | None = None
    cached_h_wear_mm: Decimal | None = None
    cached_d_geom_mm: Decimal | None = None
    cached_d_wear_mm: Decimal | None = None
    pending_review: bool
    pending_reason: str | None = None
    assigned_at: datetime
    last_confirmed_at: datetime | None = None
    deleted_at: datetime | None = None
