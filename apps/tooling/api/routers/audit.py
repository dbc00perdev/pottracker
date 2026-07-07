"""Audit-log query endpoint. Admins see all; others see own actions only."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.tooling.api.db import get_session
from apps.tooling.api.deps import CurrentUser, get_current_user
from apps.tooling.api.schemas.audit import AuditOut
from apps.tooling.api.schemas.common import Page
from apps.tooling.api.services import audit

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditOut])
def query_audit(
    session: Session = Depends(get_session),
    current: CurrentUser = Depends(get_current_user),
    machine_id: UUID | None = None,
    user_id: UUID | None = None,
    event_type: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> Page[AuditOut]:
    filters: dict[str, Any] = {
        "machine_id": machine_id, "user_id": user_id, "event_type": event_type,
        "entity_type": entity_type, "entity_id": entity_id, "since": since, "until": until,
    }
    rows, total = audit.query(
        session, caller_id=current.id, caller_is_admin=current.role == "admin",
        filters=filters, limit=limit, offset=offset,
    )
    return Page(items=[AuditOut.model_validate(r) for r in rows],
                total=total, limit=limit, offset=offset)
