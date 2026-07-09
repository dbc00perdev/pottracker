"""Tool schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from apps.tooling.api.schemas.common import ORMModel
from apps.tooling.api.schemas.tool_type import ToolTypeRef


class ToolCreate(BaseModel):
    short_id: str = Field(min_length=1, max_length=128)
    tool_type_id: UUID
    diameter_mm: Decimal = Field(gt=0)
    diameter_inch: Decimal | None = None
    flute_count: int | None = Field(default=None, ge=0)
    corner_radius_mm: Decimal | None = None
    flute_length_mm: Decimal | None = None
    overall_length_mm: Decimal | None = None
    shank_diameter_mm: Decimal | None = None
    substrate: str | None = None
    coating: str | None = None
    vendor: str | None = None
    vendor_part_number: str | None = None
    vendor_url: str | None = None
    manufacturer: str | None = None
    edp_number: str | None = None
    max_doc_mm: Decimal | None = None
    max_woc_mm: Decimal | None = None
    requires_tsc: bool = False
    requires_climb: bool = False
    is_consumable_class: bool = False
    notes: str | None = None


class ToolUpdate(BaseModel):
    """PATCH — every field optional; only provided keys are written."""

    short_id: str | None = Field(default=None, min_length=1, max_length=128)
    tool_type_id: UUID | None = None
    diameter_mm: Decimal | None = Field(default=None, gt=0)
    diameter_inch: Decimal | None = None
    flute_count: int | None = Field(default=None, ge=0)
    corner_radius_mm: Decimal | None = None
    flute_length_mm: Decimal | None = None
    overall_length_mm: Decimal | None = None
    shank_diameter_mm: Decimal | None = None
    substrate: str | None = None
    coating: str | None = None
    vendor: str | None = None
    vendor_part_number: str | None = None
    vendor_url: str | None = None
    manufacturer: str | None = None
    edp_number: str | None = None
    max_doc_mm: Decimal | None = None
    max_woc_mm: Decimal | None = None
    requires_tsc: bool | None = None
    requires_climb: bool | None = None
    is_consumable_class: bool | None = None
    notes: str | None = None


class DuplicateRequest(BaseModel):
    short_id: str = Field(min_length=1, max_length=128)


class ToolAssignmentRef(BaseModel):
    """Active-assignment summary embedded in a tool response."""

    machine_id: UUID
    machine_name: str
    t_number: int
    h_register: int
    d_register: int | None = None


class ToolOut(ORMModel):
    id: UUID
    short_id: str
    tool_type: ToolTypeRef
    diameter_mm: Decimal
    diameter_inch: Decimal | None = None
    flute_count: int | None = None
    corner_radius_mm: Decimal | None = None
    flute_length_mm: Decimal | None = None
    overall_length_mm: Decimal | None = None
    shank_diameter_mm: Decimal | None = None
    substrate: str | None = None
    coating: str | None = None
    vendor: str | None = None
    vendor_part_number: str | None = None
    vendor_url: str | None = None
    manufacturer: str | None = None
    edp_number: str | None = None
    max_doc_mm: Decimal | None = None
    max_woc_mm: Decimal | None = None
    requires_tsc: bool
    requires_climb: bool
    is_consumable_class: bool
    regrind_count: int
    # Generated, standardized human description (type + Ø + flutes + material).
    # Derived from attributes, not stored — the associative label half; identity
    # stays the non-significant GTID (short_id). See tool_label.tool_description.
    description: str | None = None
    notes: str | None = None
    assignments: list[ToolAssignmentRef] = Field(default_factory=list)
    retired_at: datetime | None = None
