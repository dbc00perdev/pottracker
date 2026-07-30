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
    WorkOffsetEntry,
    WorkOffsetSlot,
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


# Work coordinate structures (verbatim shapes from Fwlib64.h; both calls need
# the FULL 4 + 4*MAX_AXIS(32) = 132-byte block — rc=2 EW_LENGTH on anything
# smaller. Inverse of the ODBM 10-not-sizeof trap. Verified live on the VT_23:
# WORK SHIFT Z=19.5044 / X=15.8365, G55 Z=6.2660 — exact panel matches
# (reports/vt23-workshift-verified-20260729.json).)
_MAX_AXIS = 32


class _IODBZOFS(ctypes.Structure):
    _fields_ = [
        ("datano", ctypes.c_short),
        ("type", ctypes.c_short),
        ("data", ctypes.c_int32 * _MAX_AXIS),
    ]


_ZOFS_SLOTS: dict[int, WorkOffsetSlot] = {
    0: WorkOffsetSlot.EXT,
    1: WorkOffsetSlot.G54,
    2: WorkOffsetSlot.G55,
    3: WorkOffsetSlot.G56,
    4: WorkOffsetSlot.G57,
    5: WorkOffsetSlot.G58,
    6: WorkOffsetSlot.G59,
}

_AXES = ("x", "z")  # 2-axis lathe; data[] beyond the configured axes is garbage


def read_work_offsets_lathe(client: FocasClient) -> tuple[WorkOffsetEntry, ...]:
    """EXT + G54..G59 (`cnc_rdzofs`) + the WORK SHIFT screen
    (`cnc_rdwkcdshft` — the value T1 sets on the VT). Resilient per-slot."""
    out: list[WorkOffsetEntry] = []
    length = ctypes.sizeof(_IODBZOFS)  # the full-block length trap
    increment = client._offset_increment

    for datano, slot in _ZOFS_SLOTS.items():
        buf = _IODBZOFS()
        rc = client._lib.cnc_rdzofs(
            client._handle,
            ctypes.c_short(datano),
            ctypes.c_short(-1),
            ctypes.c_short(length),
            ctypes.byref(buf),
        )
        if rc != 0:
            _logger.debug("cnc_rdzofs(datano=%d) returned %d", datano, rc)
            continue
        for i, axis in enumerate(_AXES):
            out.append(
                WorkOffsetEntry(slot=slot, axis=axis, value=Decimal(int(buf.data[i])) * increment)
            )

    buf = _IODBZOFS()  # IODBWCSF shares the shape
    rc = client._lib.cnc_rdwkcdshft(
        client._handle, ctypes.c_short(-1), ctypes.c_short(length), ctypes.byref(buf)
    )
    if rc != 0:
        _logger.debug("cnc_rdwkcdshft returned %d", rc)
    else:
        for i, axis in enumerate(_AXES):
            out.append(
                WorkOffsetEntry(
                    slot=WorkOffsetSlot.WORK_SHIFT,
                    axis=axis,
                    value=Decimal(int(buf.data[i])) * increment,
                )
            )
    return tuple(out)


class _ODBGCD(ctypes.Structure):
    _fields_ = [
        ("group", ctypes.c_short),
        ("flag", ctypes.c_short),
        ("code", ctypes.c_char * 8),
    ]


# Modal G-group carrying the active work offset (G54..G59) on the VT_23 —
# verified live 2026-07-29 (group 13 read "G56" with G56 active at the panel).
_WCS_MODAL_GROUP = 13


def read_active_wcs(client: FocasClient) -> str | None:
    """The work-offset G code currently ACTIVE (modal state, `cnc_rdgcode`).
    Selecting an offset changes no stored value — only this modal answers
    "which one is the program using right now". None on any error."""
    num = ctypes.c_short(1)
    buf = (_ODBGCD * 1)()
    rc = client._lib.cnc_rdgcode(
        client._handle,
        ctypes.c_short(_WCS_MODAL_GROUP),
        ctypes.c_short(0),
        ctypes.byref(num),
        buf,
    )
    if rc != 0 or num.value < 1:
        _logger.debug("cnc_rdgcode(group=%d) returned %d", _WCS_MODAL_GROUP, rc)
        return None
    code = buf[0].code.decode("ascii", "replace").strip(" ").strip()
    return code or None


class _ODBCMD(ctypes.Structure):
    _fields_ = [
        ("adrs", ctypes.c_char),
        ("num", ctypes.c_char),
        ("flag", ctypes.c_short),
        ("cmd_val", ctypes.c_int32),
        ("dec_val", ctypes.c_int32),
    ]


def read_commanded_t(client: FocasClient) -> int | None:
    """The FULL commanded T word via `cnc_rdcommand` (documented NC read) —
    carries BOTH halves of the lathe Tnnww call: station nn and active offset
    ww. Panel-verified on the VT_23 2026-07-29: panel T1224 -> T=1224 exact
    (S=1300, M=30, O=21 in the same response). Preferred over the F26 T-code
    interface signal, which this ladder truncates to the station (T0808 -> 8).
    None on error or when no T has been commanded."""
    num = ctypes.c_short(30)
    buf = (_ODBCMD * 30)()
    rc = client._lib.cnc_rdcommand(
        client._handle, ctypes.c_short(-1), ctypes.c_short(0),
        ctypes.byref(num), buf,
    )
    if rc != 0:
        _logger.debug("cnc_rdcommand returned %d", rc)
        return None
    for i in range(num.value):
        if buf[i].adrs == b"T":
            return int(buf[i].cmd_val) or None
    return None


def read_status_lathe(client: FocasClient) -> MachineStatus:
    """`cnc_statinfo` + active work-offset modal + the commanded T word
    (station + active offset). All documented NC reads — ZERO PMC on the
    lathe profile (the mills' OEM R/D addresses are foreign bytes on this
    builder's ladder, R22). `current_t_number` carries the FULL Tnnww word;
    the lathe UI splits it into station (nn) and active offset (ww)."""
    out = ODBST()
    rc = client._lib.cnc_statinfo(client._handle, ctypes.byref(out))
    raise_for_code(rc, context="cnc_statinfo")
    status = decode_status(out)
    return status.model_copy(
        update={
            "active_wcs": read_active_wcs(client),
            "current_t_number": read_commanded_t(client),
        }
    )


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
        work_offsets = read_work_offsets_lathe(client)
        return MachineSnapshot(
            machine_id=client._machine_id,
            polled_at=datetime.now(UTC),
            status=status,
            offsets=offsets,
            work_offsets=work_offsets,
        )

    def read_status_snapshot(self) -> MachineSnapshot:
        """Light status-only read for the fast tier (L3): mode/running/e-stop +
        active WCS + the commanded T word — 3 NC calls, milliseconds, vs the
        ~12s full sweep. Absent domains (offsets/work offsets) are simply not
        observed; the persist layer's additive upserts never zero them."""
        client = self._client
        if client._machine_id is None:
            raise ValueError("machine_id not set on the wrapped FocasClient")
        return MachineSnapshot(
            machine_id=client._machine_id,
            polled_at=datetime.now(UTC),
            status=read_status_lathe(client),
        )

    def close(self) -> None:
        self._client.close()
