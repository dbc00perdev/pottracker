"""Tool endpoints: list/create/get/update/retire/duplicate."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.tooling.api.db import get_session
from apps.tooling.api.deps import CurrentUser, get_current_user, require_role
from apps.tooling.api.schemas.common import Page, ReasonBody
from apps.tooling.api.schemas.tool import DuplicateRequest, ToolCreate, ToolOut, ToolUpdate
from apps.tooling.api.services import tools
from shared.audit import record_audit

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=Page[ToolOut])
def list_tools(
    session: Session = Depends(get_session),
    _: CurrentUser = Depends(get_current_user),
    q: str | None = None,
    tool_type: str | None = None,
    diameter_mm_min: float | None = None,
    diameter_mm_max: float | None = None,
    flute_count: int | None = None,
    substrate: str | None = None,
    coating: str | None = None,
    requires_tsc: bool | None = None,
    assigned: bool | None = None,
    assigned_machine_id: UUID | None = None,
    include_retired: bool = False,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[ToolOut]:
    filters: dict[str, Any] = {
        "q": q, "tool_type": tool_type, "diameter_mm_min": diameter_mm_min,
        "diameter_mm_max": diameter_mm_max, "flute_count": flute_count,
        "substrate": substrate, "coating": coating, "requires_tsc": requires_tsc,
        "assigned": assigned, "assigned_machine_id": assigned_machine_id,
        "include_retired": include_retired,
    }
    items, total = tools.list_tools(session, filters, limit, offset)
    return Page(items=[ToolOut.model_validate(i) for i in items],
                total=total, limit=limit, offset=offset)


@router.post("", response_model=ToolOut, status_code=201)
def create_tool(body: ToolCreate, session: Session = Depends(get_session),
                current: CurrentUser = Depends(require_role("setter"))) -> ToolOut:
    result = tools.create(session, body, current.id)
    record_audit(session, event_type="tool_create", entity_type="tool",
                 entity_id=str(result["id"]), user_id=current.id,
                 after_value={"short_id": result["short_id"]})
    return ToolOut.model_validate(result)


@router.get("/{tool_id}", response_model=ToolOut)
def get_tool(tool_id: UUID, session: Session = Depends(get_session),
             _: CurrentUser = Depends(get_current_user)) -> ToolOut:
    return ToolOut.model_validate(tools.get(session, tool_id))


@router.patch("/{tool_id}", response_model=ToolOut)
def update_tool(tool_id: UUID, body: ToolUpdate, session: Session = Depends(get_session),
                current: CurrentUser = Depends(require_role("setter"))) -> ToolOut:
    result, diff = tools.update(session, tool_id, body)
    if diff:
        record_audit(session, event_type="tool_update", entity_type="tool",
                     entity_id=str(tool_id), user_id=current.id, after_value=diff)
    return ToolOut.model_validate(result)


@router.post("/{tool_id}/retire", response_model=ToolOut)
def retire_tool(tool_id: UUID, body: ReasonBody | None = None,
                force: bool = False, session: Session = Depends(get_session),
                current: CurrentUser = Depends(require_role("setter"))) -> ToolOut:
    result = tools.retire(session, tool_id, force=force, is_admin=current.role == "admin")
    record_audit(session, event_type="tool_retire", entity_type="tool",
                 entity_id=str(tool_id), user_id=current.id,
                 reason=body.reason if body else None)
    return ToolOut.model_validate(result)


@router.post("/{tool_id}/duplicate", response_model=ToolOut, status_code=201)
def duplicate_tool(tool_id: UUID, body: DuplicateRequest, session: Session = Depends(get_session),
                   current: CurrentUser = Depends(require_role("setter"))) -> ToolOut:
    result = tools.duplicate(session, tool_id, body.short_id, current.id)
    record_audit(session, event_type="tool_duplicate", entity_type="tool",
                 entity_id=str(result["id"]), user_id=current.id,
                 after_value={"short_id": result["short_id"], "source_tool_id": str(tool_id)})
    return ToolOut.model_validate(result)
