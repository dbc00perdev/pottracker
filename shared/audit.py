"""Audit log writer.

Phase 2 deliverable. Stub only — no implementation until Alembic migrations
for `shared.audit_log` land. Defined here so `shared.focas.writer` (Phase 6)
has a stable import target from day one.
"""

from __future__ import annotations

from typing import Any


def write_audit_entry(*args: Any, **kwargs: Any) -> None:
    raise NotImplementedError("shared.audit.write_audit_entry lands in Phase 2")
