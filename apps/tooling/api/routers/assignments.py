"""Assignment endpoints: list/create/get/update/confirm/delete."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.tooling.api.db import get_session
from apps.tooling.api.deps import CurrentUser, get_current_user, require_role
from apps.tooling.api.schemas.assignment import (
    AssignmentCreate,
    AssignmentOut,
    AssignmentUpdate,
    ConfirmRequest,
)
from apps.tooling.api.schemas.common import Page, ReasonBody
from apps.tooling.api.services import assignments
from shared.audit import record_audit

router = APIRouter(prefix="/assignments", tags=["assignments"])


@router.get("", response_model=Page[AssignmentOut])
def list_assignments(
    session: Session = Depends(get_session),
    _: CurrentUser = Depends(get_current_user),
    machine_id: UUID | None = None,
    tool_id: UUID | None = None,
    pending_review: bool | None = None,
    include_deleted: bool = False,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[AssignmentOut]:
    filters: dict[str, Any] = {
        "machine_id": machine_id, "tool_id": tool_id,
        "pending_review": pending_review, "include_deleted": include_deleted,
    }
    rows, total = assignments.list_assignments(session, filters, limit, offset)
    return Page(items=[AssignmentOut.model_validate(r) for r in rows],
                total=total, limit=limit, offset=offset)


@router.post("", response_model=AssignmentOut, status_code=201)
def create_assignment(body: AssignmentCreate, session: Session = Depends(get_session),
                      current: CurrentUser = Depends(require_role("setter"))) -> AssignmentOut:
    row = assignments.create(session, body, current.id)
    record_audit(session, event_type="assignment_create", entity_type="assignment",
                 entity_id=str(row.id), machine_id=body.machine_id, user_id=current.id,
                 after_value={"tool_id": str(body.tool_id), "t_number": body.t_number,
                              "h_register": body.h_register, "d_register": body.d_register})
    return AssignmentOut.model_validate(row)


@router.get("/{assignment_id}", response_model=AssignmentOut)
def get_assignment(assignment_id: UUID, session: Session = Depends(get_session),
                   _: CurrentUser = Depends(get_current_user)) -> AssignmentOut:
    return AssignmentOut.model_validate(assignments.get(session, assignment_id))


@router.patch("/{assignment_id}", response_model=AssignmentOut)
def update_assignment(assignment_id: UUID, body: AssignmentUpdate,
                      session: Session = Depends(get_session),
                      current: CurrentUser = Depends(require_role("setter"))) -> AssignmentOut:
    row = assignments.update(session, assignment_id, body)
    record_audit(session, event_type="assignment_update", entity_type="assignment",
                 entity_id=str(assignment_id), machine_id=row.machine_id, user_id=current.id,
                 after_value=body.model_dump(exclude_unset=True))
    return AssignmentOut.model_validate(row)


@router.post("/{assignment_id}/confirm", response_model=AssignmentOut)
def confirm_assignment(assignment_id: UUID, body: ConfirmRequest | None = None,
                       session: Session = Depends(get_session),
                       current: CurrentUser = Depends(require_role("operator"))) -> AssignmentOut:
    row = assignments.confirm(session, assignment_id, current.id)
    record_audit(session, event_type="assignment_confirm", entity_type="assignment",
                 entity_id=str(assignment_id), machine_id=row.machine_id, user_id=current.id,
                 reason=body.reason if body else None)
    return AssignmentOut.model_validate(row)


@router.delete("/{assignment_id}", status_code=204)
def delete_assignment(assignment_id: UUID, body: ReasonBody | None = None,
                      session: Session = Depends(get_session),
                      current: CurrentUser = Depends(require_role("setter"))) -> None:
    row = assignments.get(session, assignment_id)
    assignments.soft_delete(session, assignment_id)
    record_audit(session, event_type="assignment_delete", entity_type="assignment",
                 entity_id=str(assignment_id), machine_id=row.machine_id, user_id=current.id,
                 reason=body.reason if body else None)
