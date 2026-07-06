"""Auth dependencies: current-user resolution + role gating.

Role hierarchy (Decision-7 roles): viewer < operator < setter < admin.
`require_role(min_role)` returns a dependency that 403s when the caller's role
ranks below the minimum.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from fastapi import Depends, Request
from jose import JWTError
from sqlalchemy.orm import Session

from apps.tooling.api.config import Settings, get_settings
from apps.tooling.api.db import get_session
from apps.tooling.api.errors import Forbidden, Unauthorized
from apps.tooling.api.security import decode_token
from shared.db import user as user_t

ROLE_ORDER: dict[str, int] = {"viewer": 0, "operator": 1, "setter": 2, "admin": 3}


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    username: str
    role: str

    def rank(self) -> int:
        return ROLE_ORDER.get(self.role, -1)


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("missing or malformed Authorization header")
    return token


def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> CurrentUser:
    token = _bearer_token(request)
    try:
        payload = decode_token(settings, token)
    except JWTError as exc:
        raise Unauthorized(f"invalid token: {exc}") from exc
    if payload.get("typ") != "access":
        raise Unauthorized("not an access token")
    sub = payload.get("sub")
    if not sub:
        raise Unauthorized("token missing subject")
    row = session.execute(
        sa.select(user_t.c.id, user_t.c.username, user_t.c.role, user_t.c.disabled_at)
        .where(user_t.c.id == UUID(str(sub)))
    ).one_or_none()
    if row is None or row.disabled_at is not None:
        raise Unauthorized("user not found or disabled")
    return CurrentUser(id=row.id, username=row.username, role=row.role)


def require_role(min_role: str) -> Callable[..., CurrentUser]:
    minimum = ROLE_ORDER[min_role]

    def _dep(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current.rank() < minimum:
            raise Forbidden(f"requires role >= {min_role}, have {current.role}")
        return current

    return _dep
