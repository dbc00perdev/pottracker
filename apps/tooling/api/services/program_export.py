"""Running-program export: one live READ against the machine per request.

The only export surface that touches a control, and it only reads —
`shared/focas/programs.py` uploads text FROM the control (no download/write
functions exist in this codebase). Connect → resolve O number → fetch text →
close happens inside one synchronous call, so FastAPI's threadpool runs the
whole FOCAS handle lifecycle on a single thread (the thread-affinity rule).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from apps.tooling.api.errors import ApiError, Unprocessable
from apps.tooling.api.services.machines import get_row
from apps.tooling.api.services.offset_export import file_stamp, safe_name
from shared.focas.client import FocasClient
from shared.focas.client_reads import read_program_info
from shared.focas.errors import FocasError
from shared.focas.programs import read_program_text

_CONNECT_TIMEOUT_SECONDS = 10


def fetch_program(session: Session, machine_id: UUID, o_number: int | None) -> tuple[str, bytes]:
    """(filename, program bytes). o_number None = whatever is executing now."""
    machine = get_row(session, machine_id)
    try:
        client = FocasClient.connect(
            ip=str(machine.ip_address), port=machine.focas_port,
            timeout_seconds=_CONNECT_TIMEOUT_SECONDS,
        )
    except FocasError as exc:
        # FocasConnectError (network) and FocasNoDllError (host config) both
        # land here — either way the live read can't start.
        raise ApiError(
            503, "Machine Unreachable",
            f"FOCAS connect to {machine.name} failed: {exc}",
        ) from exc

    try:
        resolved = o_number
        if resolved is None:
            resolved, _name = read_program_info(client)
            if resolved is None:
                raise Unprocessable(
                    f"{machine.name} reports no program under execution; "
                    "pass o_number to fetch a specific program"
                )
        try:
            text = read_program_text(client, resolved)
        except FocasError as exc:
            raise Unprocessable(
                f"{machine.name} rejected upload of O{resolved}: {exc} "
                "(busy/protected programs can be exported when the machine is idle)"
            ) from exc
        except TimeoutError as exc:
            raise Unprocessable(f"{machine.name}: {exc}") from exc
    finally:
        client.close()

    stamp = file_stamp(datetime.now(UTC))
    filename = f"{safe_name(machine.name)}-O{resolved:04d}-{stamp}.nc"
    return filename, text
