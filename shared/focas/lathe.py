"""Lathe (0i-TF) read profile — offsets-only v1 for the VIPER VT_23.

Why a separate profile instead of the mill snapshot (`FocasClient.read_snapshot`):
the mill path reads OEM Mighty Viper PMC addresses (pot table D105-128, HEAD/NEXT
R327/R325) that are meaningless on the VT's different ladder, and labels offset
banks H/D. Running it against a lathe would mirror plausible-looking false data
(R20/R22). This profile reads ONLY:

  * `cnc_statinfo`  — mode / running / e-stop (control-generic; NO PMC reads,
    so current/next tool stay None until the VT turret-position source is
    verified — its own discovery task).
  * `cnc_rdtofs`    — the seven lathe banks, PANEL-LOCKED on the VT_23
    2026-07-29 (`reports/vt23-bank-mapping-verified-20260729.json`):
    type 0=X wear, 1=X geom, 2=Z wear, 3=Z geom, 4=R wear, 5=R geom, 6=tip.
    Type 7 duplicates the tip view and is deliberately NOT read (the mirror
    keys on (register_number, register_type); reading both 6 and 7 would
    collide on 'tip').

Read-only throughout. No pots, no macros, no tool-life in v1 — the persist
layer's additive upserts make a partial snapshot safe (absent domains are
simply not observed, never zeroed).

`LatheSnapshotSource` satisfies the `SnapshotSource` protocol so the standard
`FocasService` supervisor runs it unchanged (`scripts/focas_service.py
--profile lathe`).
"""

from __future__ import annotations

import ctypes
import logging
from datetime import UTC, datetime
from decimal import Decimal

from shared.focas.client import FocasClient, decode_offset, decode_status
from shared.focas.ctypes_defs import ODBST, ODBTOFS
from shared.focas.errors import raise_for_code
from shared.focas.models import (
    MachineSnapshot,
    MachineStatus,
    OffsetRegister,
    RegisterType,
)

_logger = logging.getLogger("shared.focas.lathe")

# Panel-locked VT_23 bank map (FANUC T-series textbook interleave — unlike the
# mills' non-standard permutation). Code 7 (duplicate tip view) intentionally
# absent; see module docstring.
_LATHE_TYPE_MAP: dict[int, RegisterType] = {
    0: RegisterType.X_WEAR,
    1: RegisterType.X_GEOM,
    2: RegisterType.Z_WEAR,
    3: RegisterType.Z_GEOM,
    4: RegisterType.R_WEAR,
    5: RegisterType.R_GEOM,
    6: RegisterType.TIP,
}


def read_offsets_lathe(client: FocasClient) -> tuple[OffsetRegister, ...]:
    """Read every register x the seven verified lathe banks (~700 calls on the
    VT's 99 registers). Same resilient per-call shape as the mill read: a
    rejected call or empty datano skips that cell, never aborts the sweep."""
    _ofs_type, use_no = client.read_offset_layout()
    out: list[OffsetRegister] = []
    length = ctypes.sizeof(ODBTOFS)
    for num in range(1, use_no + 1):
        for type_code, register_type in _LATHE_TYPE_MAP.items():
            buf = ODBTOFS()
            rc = client._lib.cnc_rdtofs(
                client._handle,
                ctypes.c_short(num),
                ctypes.c_short(type_code),
                ctypes.c_short(length),
                ctypes.byref(buf),
            )
            if rc != 0:
                _logger.debug("cnc_rdtofs(num=%d, type=%d) returned %d", num, type_code, rc)
                continue
            if int(buf.datano) <= 0:
                continue
            if register_type is RegisterType.TIP:
                # Tip/orientation is an integer CODE (0-9), not a distance —
                # never scale it by the offset increment.
                out.append(
                    OffsetRegister(
                        register_number=int(buf.datano),
                        register_type=register_type,
                        value_mm=Decimal(int(buf.data)),
                    )
                )
            else:
                out.append(decode_offset(buf, register_type, client._offset_increment))
    return tuple(out)


def read_status_lathe(client: FocasClient) -> MachineStatus:
    """`cnc_statinfo` only — mode/running/e-stop. Deliberately NO PMC reads:
    the mill HEAD/NEXT addresses are foreign bytes on the VT ladder and would
    decode to phantom tool numbers. current/next stay None until the turret
    position source is verified per-machine."""
    out = ODBST()
    rc = client._lib.cnc_statinfo(client._handle, ctypes.byref(out))
    raise_for_code(rc, context="cnc_statinfo")
    return decode_status(out)


class LatheSnapshotSource:
    """`SnapshotSource` for a lathe: wraps a connected `FocasClient` and
    assembles the offsets-only snapshot. Drop-in for `FocasService`."""

    def __init__(self, client: FocasClient) -> None:
        self._client = client

    def read_snapshot(self) -> MachineSnapshot:
        client = self._client
        if client._machine_id is None:
            raise ValueError("machine_id not set on the wrapped FocasClient")
        status = read_status_lathe(client)
        offsets = read_offsets_lathe(client)
        return MachineSnapshot(
            machine_id=client._machine_id,
            polled_at=datetime.now(UTC),
            status=status,
            offsets=offsets,
        )

    def close(self) -> None:
        self._client.close()
