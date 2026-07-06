"""Audit-log queries. Admins see everything; other roles are scoped to their
own actions (`user_id == caller`)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from shared.db import audit_log


def query(session: Session, *, caller_id: UUID, caller_is_admin: bool,
          filters: dict[str, Any], limit: int, offset: int) -> Sequence[Any]:
    conds: list[Any] = []
    if not caller_is_admin:
        conds.append(audit_log.c.user_id == caller_id)
    elif (uid := filters.get("user_id")) is not None:
        conds.append(audit_log.c.user_id == uid)
    if (mid := filters.get("machine_id")) is not None:
        conds.append(audit_log.c.machine_id == mid)
    if (et := filters.get("event_type")):
        conds.append(audit_log.c.event_type == et)
    if (ent := filters.get("entity_type")):
        conds.append(audit_log.c.entity_type == ent)
    if (eid := filters.get("entity_id")):
        conds.append(audit_log.c.entity_id == eid)
    if (since := filters.get("since")) is not None:
        conds.append(audit_log.c.occurred_at >= since)
    if (until := filters.get("until")) is not None:
        conds.append(audit_log.c.occurred_at <= until)
    where = sa.and_(*conds) if conds else sa.true()
    return session.execute(
        sa.select(audit_log).where(where)
        .order_by(audit_log.c.occurred_at.desc()).limit(limit).offset(offset)
    ).all()
