"""User lookup for authentication."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from shared.db import user as user_t


def get_by_username(session: Session, username: str):
    return session.execute(
        sa.select(user_t).where(user_t.c.username == username)
    ).one_or_none()


def get_by_id(session: Session, user_id: UUID):
    return session.execute(
        sa.select(user_t).where(user_t.c.id == user_id)
    ).one_or_none()


def touch_last_login(session: Session, user_id: UUID) -> None:
    session.execute(
        sa.update(user_t)
        .where(user_t.c.id == user_id)
        .values(last_login_at=datetime.now(UTC))
    )
