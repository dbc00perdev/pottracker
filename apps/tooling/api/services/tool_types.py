"""Tool-type queries."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.tooling.api.errors import Conflict
from apps.tooling.api.schemas.tool_type import ToolTypeCreate
from apps.tooling.api.tables import tool_type as tt


def list_all(session: Session) -> Sequence[Any]:
    return session.execute(sa.select(tt).order_by(tt.c.code)).all()


def create(session: Session, body: ToolTypeCreate):
    try:
        row = session.execute(
            sa.insert(tt).values(**body.model_dump()).returning(tt)
        ).one()
    except IntegrityError as exc:
        raise Conflict(f"tool_type code '{body.code}' already exists") from exc
    return row
