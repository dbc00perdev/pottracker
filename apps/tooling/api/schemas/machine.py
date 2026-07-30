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
    # Fast status-only tier (L3); None = no fast tier. Same 10s floor.
    status_poll_interval_seconds: int | None = Field(default=None, ge=10)


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
    status_poll_interval_seconds: int | None = Field(default=None, ge=10)
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
    status_poll_interval_seconds: int | None = None
    enabled: bool
    machine_class: str = "mill"
    retired_at: datetime | None = None
    focas_state: FocasState


class WorkOffsetOut(ORMModel):
    slot: str
    axis: str
    value: Decimal
    last_polled_at: datetime
    last_changed_at: datetime


class OffsetRegisterOut(ORMModel):
    register_number: int
    register_type: str
    value_mm: Decimal
    last_polled_at: datetime
    last_changed_at: datetime


class PotOut(ORMModel):
    pot_number: int
    t_number: int | None = None
    # Occupancy model (#3): identity (t_number) correlated with presence.
    # state ∈ {probe, loaded, empty, unverified}. `verified` = the mapped
    # h_geom offset's latest change was presetter-attributed (#2).
    state: str = "unverified"
    verified: bool = False
    assigned_h_register: int | None = None
    offset_mm: Decimal | None = None
    # Spindle/NEXT overlay: "spindle" if this pot's tool is currently in the
    # spindle (HEAD), "next" if on deck (NEXT), else null (really in the pot).
    # The UI draws spindle/next pots vacated rather than loaded (no ghosts).
    location: str | None = None
    last_polled_at: datetime
    last_changed_at: datetime


class SpindleOut(ORMModel):
    """Live spindle/load state (shared.focas_machine_status). All-None when the
    poller hasn't persisted a status row for the machine yet."""

    head_t_number: int | None = None
    next_t_number: int | None = None
    mode: str | None = None
    running: bool | None = None
    emergency_stop: bool | None = None
    active_wcs: str | None = None
    # Last commanded T word with real offset digits (Tnnww, ww != 00) + when
    # observed — survives the shop's Tnn00 end-of-op cancels. NULL on mills.
    last_tool_t_word: int | None = None
    last_tool_at: datetime | None = None
    last_polled_at: datetime | None = None
    last_changed_at: datetime | None = None


class ToolLifeOut(ORMModel):
    t_number: int
    life_count: int | None = None
    life_max: int | None = None
    status: str | None = None
    last_polled_at: datetime
