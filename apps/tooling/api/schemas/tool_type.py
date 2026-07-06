"""Tool-type schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from apps.tooling.api.schemas.common import ORMModel


class ToolTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1)
    has_corner_radius: bool = False
    has_thread_pitch: bool = False
    has_taper_angle: bool = False
    is_drilling: bool = False
    notes: str | None = None


class ToolTypeOut(ORMModel):
    id: UUID
    code: str
    display_name: str
    has_corner_radius: bool
    has_thread_pitch: bool
    has_taper_angle: bool
    is_drilling: bool
    notes: str | None = None


class ToolTypeRef(ORMModel):
    """Compact tool-type reference embedded in tool responses."""

    code: str
    display_name: str
