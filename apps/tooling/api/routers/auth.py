"""Auth endpoints: login, refresh, me."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from jose import JWTError
from sqlalchemy.orm import Session

from apps.tooling.api.config import Settings, get_settings
from apps.tooling.api.db import get_session
from apps.tooling.api.deps import CurrentUser, get_current_user
from apps.tooling.api.errors import Unauthorized
from apps.tooling.api.schemas.auth import LoginRequest, MeResponse, RefreshRequest, TokenPair
from apps.tooling.api.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from apps.tooling.api.services import users

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, settings: Settings = Depends(get_settings),
          session: Session = Depends(get_session)) -> TokenPair:
    row = users.get_by_username(session, body.username)
    # Verify even when the user is missing to avoid a username-timing oracle.
    stored_hash = row.password_hash if row is not None else "$2b$12$" + "x" * 53
    if row is None or row.disabled_at is not None or not verify_password(body.password, stored_hash):
        raise Unauthorized("invalid username or password")
    users.touch_last_login(session, row.id)
    return TokenPair(
        access_token=create_access_token(
            settings, user_id=str(row.id), username=row.username, role=row.role),
        refresh_token=create_refresh_token(settings, user_id=str(row.id)),
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, settings: Settings = Depends(get_settings),
            session: Session = Depends(get_session)) -> TokenPair:
    try:
        payload = decode_token(settings, body.refresh_token)
    except JWTError as exc:
        raise Unauthorized(f"invalid refresh token: {exc}") from exc
    if payload.get("typ") != "refresh":
        raise Unauthorized("not a refresh token")
    row = users.get_by_id(session, UUID(str(payload["sub"])))
    if row is None or row.disabled_at is not None:
        raise Unauthorized("user not found or disabled")
    return TokenPair(
        access_token=create_access_token(
            settings, user_id=str(row.id), username=row.username, role=row.role),
        refresh_token=create_refresh_token(settings, user_id=str(row.id)),
    )


@router.get("/me", response_model=MeResponse)
def me(current: CurrentUser = Depends(get_current_user),
       session: Session = Depends(get_session)) -> MeResponse:
    row = users.get_by_id(session, current.id)
    if row is None:
        raise Unauthorized("user not found")
    return MeResponse(id=row.id, username=row.username,
                      display_name=row.display_name, role=row.role)
