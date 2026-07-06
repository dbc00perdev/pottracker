"""Tool-type endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.tooling.api.db import get_session
from apps.tooling.api.deps import CurrentUser, get_current_user, require_role
from apps.tooling.api.schemas.tool_type import ToolTypeCreate, ToolTypeOut
from apps.tooling.api.services import tool_types

router = APIRouter(prefix="/tool-types", tags=["tool-types"])


@router.get("", response_model=list[ToolTypeOut])
def list_types(session: Session = Depends(get_session),
               _: CurrentUser = Depends(get_current_user)) -> list[ToolTypeOut]:
    return [ToolTypeOut.model_validate(r) for r in tool_types.list_all(session)]


@router.post("", response_model=ToolTypeOut, status_code=201)
def create_type(body: ToolTypeCreate, session: Session = Depends(get_session),
                _: CurrentUser = Depends(require_role("admin"))) -> ToolTypeOut:
    return ToolTypeOut.model_validate(tool_types.create(session, body))
