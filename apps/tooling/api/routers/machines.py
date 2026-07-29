"""Machine endpoints + FOCAS mirror reads."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.tooling.api.db import get_session
from apps.tooling.api.deps import CurrentUser, get_current_user, require_role
from apps.tooling.api.schemas.machine import (
    MachineCreate,
    MachineOut,
    MachineUpdate,
    OffsetRegisterOut,
    PotOut,
    SpindleOut,
    ToolLifeOut,
    WorkOffsetOut,
)
from apps.tooling.api.services import machines, occupancy
from shared.audit import record_audit

router = APIRouter(prefix="/machines", tags=["machines"])


@router.get("", response_model=list[MachineOut])
def list_machines(session: Session = Depends(get_session),
                  _: CurrentUser = Depends(get_current_user)) -> list[MachineOut]:
    return [MachineOut.model_validate(m) for m in machines.list_machines(session)]


@router.post("", response_model=MachineOut, status_code=201)
def create_machine(body: MachineCreate, skip_probe: bool = False,
                   session: Session = Depends(get_session),
                   current: CurrentUser = Depends(require_role("admin"))) -> MachineOut:
    result = machines.create(session, body, skip_probe=skip_probe)
    record_audit(session, event_type="machine_create", entity_type="machine",
                 entity_id=str(result["id"]), machine_id=result["id"], user_id=current.id,
                 after_value={"name": result["name"]})
    return MachineOut.model_validate(result)


@router.get("/{machine_id}", response_model=MachineOut)
def get_machine(machine_id: UUID, session: Session = Depends(get_session),
                _: CurrentUser = Depends(get_current_user)) -> MachineOut:
    return MachineOut.model_validate(machines.get(session, machine_id))


@router.patch("/{machine_id}", response_model=MachineOut)
def update_machine(machine_id: UUID, body: MachineUpdate,
                   session: Session = Depends(get_session),
                   current: CurrentUser = Depends(require_role("admin"))) -> MachineOut:
    result = machines.update(session, machine_id, body)
    record_audit(session, event_type="machine_update", entity_type="machine",
                 entity_id=str(machine_id), machine_id=machine_id, user_id=current.id,
                 after_value=body.model_dump(exclude_unset=True))
    return MachineOut.model_validate(result)


@router.get("/{machine_id}/offsets", response_model=list[OffsetRegisterOut])
def get_offsets(machine_id: UUID, register_type: str | None = None,
                session: Session = Depends(get_session),
                _: CurrentUser = Depends(get_current_user)) -> list[OffsetRegisterOut]:
    return [OffsetRegisterOut.model_validate(r)
            for r in machines.offsets(session, machine_id, register_type)]


@router.get("/{machine_id}/work-offsets", response_model=list[WorkOffsetOut])
def get_work_offsets(machine_id: UUID, session: Session = Depends(get_session),
                     _: CurrentUser = Depends(get_current_user)) -> list[WorkOffsetOut]:
    # Lathe v1.1: EXT/G54-G59 + the WORK SHIFT screen (the value T1 sets on the VT).
    return [WorkOffsetOut.model_validate(r)
            for r in machines.work_offsets(session, machine_id)]


@router.get("/{machine_id}/pots", response_model=list[PotOut])
def get_pots(machine_id: UUID, session: Session = Depends(get_session),
             _: CurrentUser = Depends(get_current_user)) -> list[PotOut]:
    # Occupancy-enriched: correlates pot identity with offset-based presence (#3).
    return [PotOut.model_validate(r) for r in occupancy.occupancy(session, machine_id)]


@router.get("/{machine_id}/tool-life", response_model=list[ToolLifeOut])
def get_tool_life(machine_id: UUID, session: Session = Depends(get_session),
                  _: CurrentUser = Depends(get_current_user)) -> list[ToolLifeOut]:
    return [ToolLifeOut.model_validate(r) for r in machines.tool_life(session, machine_id)]


@router.get("/{machine_id}/spindle", response_model=SpindleOut)
def get_spindle(machine_id: UUID, session: Session = Depends(get_session),
                _: CurrentUser = Depends(get_current_user)) -> SpindleOut:
    # Live HEAD/NEXT for the pot-map spindle overlay (Spindle/NEXT slots).
    return SpindleOut.model_validate(machines.spindle(session, machine_id))
