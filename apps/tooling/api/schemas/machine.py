"""Machine schemas + FOCAS mirror read models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from apps.tooling.api.schemas.common import ORMModel


class MachineCreate(BaseModel):
    name: str = Field(min_length=1)
    control_model: str = Field(min_length=1)
    ip_address: str
    focas_port: int = 8193
    pot_count: int = Field(ge=1)
    probe_pot: int | None = None
    probe_t_number: int | None = None
    probe_h_register: int | None = None
    offset_register_count: int = 400
    atc_strategy: str = Field(pattern="^(random_access|sequential)$")
    has_tsc: bool = False
    has_toolsetter: bool = False
    poll_interval_seconds: int = Field(default=60, ge=10)


class MachineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    control_model: str | None = None
    ip_address: str | None = None
    focas_port: int | None = None
    pot_count: int | None = Field(default=None, ge=1)
    probe_pot: int | None = None
    probe_t_number: int | None = None
    probe_h_register: int | None = None
    offset_register_count: int | None = None
    has_tsc: bool | None = None
    has_toolsetter: bool | None = None
    poll_interval_seconds: int | None = Field(default=None, ge=10)
    enabled: bool | None = None


class FocasState(BaseModel):
    connected: bool
    last_polled_at: datetime | None = None
    lag_seconds: float | None = None


class MachineOut(ORMModel):
    id: UUID
    name: str
    serial_number: str | None = None
    control_model: str
    ip_address: str
    focas_port: int
    pot_count: int
    probe_pot: int | None = None
    probe_t_number: int | None = None
    probe_h_register: int | None = None
    offset_register_count: int
    atc_strategy: str
    has_tsc: bool
    has_toolsetter: bool
    poll_interval_seconds: int
    enabled: bool
    retired_at: datetime | None = None
    focas_state: FocasState


class OffsetRegisterOut(ORMModel):
    register_number: int
    register_type: str
    value_mm: Decimal
    last_polled_at: datetime
    last_changed_at: datetime


class PotOut(ORMModel):
    pot_number: int
    t_number: int | None = None
    last_polled_at: datetime
    last_changed_at: datetime


class ToolLifeOut(ORMModel):
    t_number: int
    life_count: int | None = None
    life_max: int | None = None
    status: str | None = None
    last_polled_at: datetime
