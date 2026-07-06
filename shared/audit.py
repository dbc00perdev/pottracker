"""Audit log writer — `shared.audit_log`.

Phase 2 deliverable. Thin, single-purpose insert into the append-only ledger.
Poller-driven change events (Phase 2) pass `user_id=None` and `success=True`;
operator-driven offset writes (Phase 6) will pass a real `user_id` and may pass
`success=False` + `error` when a FANUC write fails.

Column names match `migrations/versions/0001_shared_core.py` exactly — NOT the
`kind`/`before`/`after` sketch in the older spec draft. Source of truth is the
migration.

`before_value` / `after_value` are JSONB; callers MUST pass JSON-serializable
dicts (no `Decimal`, no `datetime` — stringify at the call site). See
`shared.focas.snapshot` for how offset values are rendered.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from shared.db import audit_log


def record_audit(
    session: Session,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
    machine_id: UUID | None = None,
    user_id: UUID | None = None,
    before_value: dict[str, Any] | None = None,
    after_value: dict[str, Any] | None = None,
    reason: str | None = None,
    success: bool = True,
    error: str | None = None,
    occurred_at: datetime | None = None,
) -> None:
    """Insert one row into `shared.audit_log`.

    Does NOT commit — the caller owns the transaction boundary so a snapshot's
    mirror UPSERTs and its audit rows land atomically (one commit per poll).

    `occurred_at` defaults to the DB `now()` when omitted; pass the snapshot's
    `polled_at` to stamp every row in a cycle with the same instant.
    """
    values: dict[str, Any] = {
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "machine_id": machine_id,
        "user_id": user_id,
        "before_value": before_value,
        "after_value": after_value,
        "reason": reason,
        "success": success,
        "error": error,
    }
    if occurred_at is not None:
        values["occurred_at"] = occurred_at
    session.execute(sa.insert(audit_log).values(**values))


# Back-compat shim: the Phase 6 writer's import target from the original stub.
# Kept as a thin alias so `from shared.audit import write_audit_entry` still
# resolves; new code should call `record_audit`.
def write_audit_entry(session: Session, **kwargs: Any) -> None:
    record_audit(session, **kwargs)


__all__ = ["record_audit", "write_audit_entry"]
