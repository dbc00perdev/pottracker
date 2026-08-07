"""Export endpoints (spec-offset-export.md) — browser downloads.

Offsets (G10/CSV) read the DB mirror only. The program endpoint performs one
live FOCAS READ (program upload FROM the control); no write surface exists.
All endpoints require auth; the frontend downloads via fetch-with-bearer and
a blob URL (a bare <a href> can't carry the Authorization header).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from apps.tooling.api.db import get_session
from apps.tooling.api.deps import CurrentUser, get_current_user
from apps.tooling.api.services import offset_export, program_export

router = APIRouter(prefix="/machines/{machine_id}/exports", tags=["exports"])


def _attachment(filename: str, content: str | bytes, media_type: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/offsets.g10")
def offsets_g10(machine_id: UUID, mode: str = Query("sparse", pattern="^(sparse|full)$"),
                session: Session = Depends(get_session),
                _: CurrentUser = Depends(get_current_user)) -> Response:
    filename, text = offset_export.export_g10(session, machine_id, sparse=mode == "sparse")
    return _attachment(filename, text, "text/plain")


@router.get("/offsets.csv")
def offsets_csv(machine_id: UUID, mode: str = Query("sparse", pattern="^(sparse|full)$"),
                session: Session = Depends(get_session),
                _: CurrentUser = Depends(get_current_user)) -> Response:
    filename, text = offset_export.export_csv(session, machine_id, sparse=mode == "sparse")
    return _attachment(filename, text, "text/csv")


@router.get("/program")
def running_program(machine_id: UUID, o_number: int | None = Query(None, ge=1),
                    session: Session = Depends(get_session),
                    _: CurrentUser = Depends(get_current_user)) -> Response:
    # Sync endpoint: FastAPI's threadpool keeps the whole FOCAS handle
    # lifecycle on one thread (thread-affinity rule).
    filename, text = program_export.fetch_program(session, machine_id, o_number)
    return _attachment(filename, text, "text/plain")
