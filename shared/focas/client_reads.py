"""FOCAS bulk-read implementations for `FocasClient`.

Split out of `shared/focas/client.py` (LOC cap): the domain reads that
dominate the cycle (offsets / pots / tool life / alarms) live here as
module-level functions taking the client — the same idiom as
`shared/focas/lathe.py`. `FocasClient` keeps thin delegating methods, so
the public API and every existing caller are unchanged.

Read-only, like everything in the client: no write function is bound
anywhere in this package (`cnc_wrtofs` lands in Phase 6 behind the HARD
GATE).
"""

from __future__ import annotations

import ctypes
import logging
import re
from decimal import Decimal
from typing import TYPE_CHECKING

from .ctypes_defs import (
    IODBTD,
    IODBTLMAG,
    ODBALMMSG2,
    ODBM,
    ODBTLIFE1,
    ODBTLIFE2,
    ODBTLINF,
    ODBTOFS,
    ODBUSEGR,
)
from .decoders import (
    _ALARM_TYPE_ALL,
    _MACRO_DATA_LEN,
    _NO_TOOL_LIFE,
    _OFS_TYPE_DISPATCH,
    _PMC_AREA_D,
    _PMC_D_POT_BASE,
    _SKIP_MACRO_VARS,
    decode_alarm,
    decode_macro,
    decode_offset,
    decode_offset_layout,
    decode_pot,
    decode_pot_bcd,
    decode_tool_life,
)
from .errors import FocasError, raise_for_code
from .models import AlarmEntry, MacroVariable, OffsetRegister, PotEntry, ToolLife

if TYPE_CHECKING:
    from .client import FocasClient

_logger = logging.getLogger("shared.focas.client_reads")


def read_offset_layout(client: FocasClient) -> tuple[int, int]:
    """Read offset table layout (`ofs_type`, `use_no`) and cache it on the
    client until `close()`. The cached `ofs_type` drives the type-code
    dispatch in `read_offsets`."""
    out = ODBTLINF()
    rc = client._lib.cnc_rdtofsinfo(client._handle, ctypes.byref(out))
    raise_for_code(rc, context="cnc_rdtofsinfo")
    ofs_type, use_no = decode_offset_layout(out)
    client._offset_use_no = use_no
    client._ofs_type = ofs_type
    return ofs_type, use_no


def read_offsets(client: FocasClient) -> tuple[OffsetRegister, ...]:
    """Read every offset register, dispatched by the control's `ofs_type`
    (Memory A / B / C).

    Memory A: 1 type per register, 1 call per register.
    Memory B: what the Lance Viper reports (`ofs_type=2`) — four banks
              via the non-standard type codes 0..3 (0=D_WEAR!);
              1600 calls per cycle.
    Memory C: 4 types per register (length geom/wear, dia geom/wear),
              1600 calls per cycle.

    Phase 2 poller may switch to `cnc_rdtofsr` (range read) for a ~10x
    speedup once the IODBTO union variant is verified per ofs_type — see
    Open question O3 in `tasks/spec-focas-calls.md`.
    """
    if client._offset_use_no is None or client._ofs_type is None:
        read_offset_layout(client)
    assert client._offset_use_no is not None
    assert client._ofs_type is not None

    type_map = _OFS_TYPE_DISPATCH.get(client._ofs_type)
    if type_map is None:
        _logger.warning(
            "unsupported ofs_type=%d; cannot decode offsets. Add a mapping "
            "to _OFS_TYPE_DISPATCH in shared/focas/decoders.py.",
            client._ofs_type,
        )
        return ()

    out: list[OffsetRegister] = []
    length = ctypes.sizeof(ODBTOFS)
    for num in range(1, client._offset_use_no + 1):
        for type_code, register_type in type_map.items():
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
                # rc==0 but the response carries no register number —
                # treat as an unconfigured / unused slot rather than
                # synthesizing a row with a bogus datano.
                continue
            out.append(decode_offset(buf, register_type, client._offset_increment))
    return tuple(out)


def read_pots_pmc(client: FocasClient) -> tuple[PotEntry, ...]:
    """Read the pot->tool table from the PMC D-area (OEM Mighty Viper
    binding): pot N at D(104+N), each a packed-BCD byte (`decode_pot_bcd`).

    One `pmc_rdpmcrng` byte read per pot (`_pot_count` pots, 24 on the
    Viper) — negligible vs the offset reads. A pot whose PMC read *fails*
    is skipped (no data != empty), so the mirror keeps its prior value for
    that pot rather than being wrongly cleared.
    """
    out: list[PotEntry] = []
    for i in range(client._pot_count):
        pot_number = i + 1
        addr = _PMC_D_POT_BASE + i
        raw = client._read_pmc_byte(addr, area=_PMC_AREA_D)
        if raw is None:
            _logger.debug("pot %d: pmc_rdpmcrng D%d failed; skipping", pot_number, addr)
            continue
        t_number = decode_pot_bcd(raw)
        if t_number is None and raw != 0:
            _logger.warning(
                "pot %d: D%d byte 0x%02x is not valid packed BCD; treating as empty",
                pot_number,
                addr,
                raw,
            )
        out.append(PotEntry(pot_number=pot_number, t_number=t_number))
    return tuple(out)


def read_pots_magazine(client: FocasClient) -> tuple[PotEntry, ...]:
    """Generic FOCAS magazine read via `cnc_rdmagazine`.

    NOT used on the Lance Viper — `cnc_rdmagazine` is a FANUC OPTION and
    returns rc=6 (EW_NOOPT) on that control (option unlicensed). Retained
    for future magazine-licensed controls and Phase-8 per-machine
    pot-source dispatch. On EW_NOOPT we return an empty tuple and log
    rather than raising, so a caller that opts into this path still gets a
    clean snapshot; any other error still raises for the circuit breaker.
    """
    ArrayT = IODBTLMAG * client._max_pots  # noqa: N806
    arr = ArrayT()
    count = ctypes.c_short(client._max_pots)
    rc = client._lib.cnc_rdmagazine(
        client._handle, ctypes.byref(count), ctypes.cast(arr, ctypes.POINTER(IODBTLMAG))
    )
    if rc == 6:  # EW_NOOPT
        _logger.warning(
            "cnc_rdmagazine returned EW_NOOPT (option not licensed on "
            "this control); pot tracking via FOCAS unavailable."
        )
        return ()
    raise_for_code(rc, context="cnc_rdmagazine")
    n = int(count.value)
    return tuple(decode_pot(arr[i]) for i in range(n))


def read_tool_life(client: FocasClient) -> tuple[ToolLife, ...]:
    """Read tool life management data.

    Sequence per the spec doc:
      1. `cnc_rdngrp` — total group count
      2. For each group: `cnc_rdgrpid` -> group ID
      3. `cnc_rdusegrpid` -> currently-active groups (logged for visibility)
      4. For each group + each tool slot: `cnc_rd1tlifedata`

    Empty / disabled tool life management returns ().
    """
    ngrp = ODBTLIFE2()
    rc = client._lib.cnc_rdngrp(client._handle, ctypes.byref(ngrp))
    if rc != 0:
        _logger.debug("cnc_rdngrp returned %d; treating as no tool life", rc)
        return ()
    group_count = int(ngrp.data)
    if group_count <= _NO_TOOL_LIFE:
        return ()

    # Active group info — informational, not gated.
    usegrp = ODBUSEGR()
    rc = client._lib.cnc_rdusegrpid(client._handle, ctypes.byref(usegrp))
    if rc == 0:
        _logger.debug(
            "tool life groups: in_use=%d, next=%d, selecting=%d",
            usegrp.use,
            usegrp.next,
            usegrp.slct,
        )

    out: list[ToolLife] = []
    for group_idx in range(1, group_count + 1):
        group_id_buf = ODBTLIFE1()
        rc = client._lib.cnc_rdgrpid(
            client._handle, ctypes.c_short(group_idx), ctypes.byref(group_id_buf)
        )
        if rc != 0:
            _logger.debug("cnc_rdgrpid(%d) returned %d", group_idx, rc)
            continue
        group_id = int(group_id_buf.data)

        # Read each tool slot in the group. FANUC tool life management
        # supports configurable max tools per group; iterate up to a
        # bounded ceiling and stop on first error per slot.
        for slot in range(1, 64 + 1):
            td = IODBTD()
            rc = client._lib.cnc_rd1tlifedata(
                client._handle,
                ctypes.c_short(group_id),
                ctypes.c_short(slot),
                ctypes.byref(td),
            )
            if rc != 0:
                break
            if int(td.tool_num) <= 0:
                break
            out.append(decode_tool_life(td))
    return tuple(out)


def read_macro(client: FocasClient, number: int) -> Decimal | None:
    """Read one custom-macro variable via `cnc_rdmacro`. Returns the decoded
    value, or `None` if the variable is vacant (`dec_val < 0`).

    Raises `FocasError` on a FOCAS error code so the caller/circuit-breaker
    can react — a vacant variable (rc=0, dec_val<0) is NOT an error, it's a
    legitimately-unset variable and returns `None`."""
    out = ODBM()
    rc = client._lib.cnc_rdmacro(
        client._handle,
        ctypes.c_short(number),
        ctypes.c_short(_MACRO_DATA_LEN),
        ctypes.byref(out),
    )
    raise_for_code(rc, context=f"cnc_rdmacro({number})")
    return decode_macro(out)


def read_macros(
    client: FocasClient, numbers: tuple[int, ...] = _SKIP_MACRO_VARS
) -> tuple[MacroVariable, ...]:
    """Read a set of custom-macro variables (default: the G31 skip vars
    #5061-#5063 for presetter attribution).

    A per-variable FOCAS error is logged and that variable is skipped (no
    data != vacant), so one bad read never loses the rest — same resilience
    as the pot read. Vacant variables ARE included with `value=None`."""
    out: list[MacroVariable] = []
    for number in numbers:
        try:
            value = read_macro(client, number)
        except FocasError as exc:
            _logger.debug("cnc_rdmacro(#%d) failed: %s; skipping", number, exc)
            continue
        out.append(MacroVariable(number=number, value=value))
    return tuple(out)


class ODBEXEPRG(ctypes.Structure):
    """`cnc_exeprgname` response (Fwlib64.h:836) — running program name + O
    number. Declared module-local (lathe.py idiom); loader binds the call
    through c_void_p."""

    _fields_ = [("name", ctypes.c_char * 36), ("o_num", ctypes.c_int32)]


# Comment line of the running program as the execution text returns it:
# "O9034(3878OR Blank)". Group 2 is the human part name shown on the panel
# header. Bounded at 64 chars — a FANUC program comment line, not free text.
_PROGRAM_COMMENT_RE = re.compile(r"^O(\d+)\((.{1,64}?)\)")


def parse_program_comment(text: str, o_num: int) -> str | None:
    """Best-effort part name from executing-program text. Only trusted when
    the text's own O number matches the running program — anything else
    returns None (never guessed, R11)."""
    m = _PROGRAM_COMMENT_RE.match(text.lstrip())
    if m and int(m.group(1)) == o_num:
        comment = m.group(2).strip()
        return comment or None
    return None


def read_program_info(client: FocasClient) -> tuple[int | None, str | None]:
    """(program_number, program_name) of the program under execution.

    `cnc_exeprgname` gives the O number; the name is a best-effort comment
    parse from `cnc_rdexecprog`'s block text (verified live on the 2100LYS:
    O9034 -> "3878OR Blank"). Resilient: each call failing independently
    degrades to None for its field — a status read never breaks on these."""
    prg = ODBEXEPRG()
    rc = client._lib.cnc_exeprgname(client._handle, ctypes.byref(prg))
    if rc != 0:
        _logger.debug("cnc_exeprgname returned %d", rc)
        return None, None
    o_num = int(prg.o_num)
    if o_num <= 0:
        return None, None

    name: str | None = None
    length = ctypes.c_ushort(512)
    blknum = ctypes.c_short(0)
    text = ctypes.create_string_buffer(512)
    rc = client._lib.cnc_rdexecprog(
        client._handle, ctypes.byref(length), ctypes.byref(blknum), text
    )
    if rc == 0:
        decoded = text.raw[: int(length.value)].decode("ascii", "replace")
        name = parse_program_comment(decoded, o_num)
    else:
        _logger.debug("cnc_rdexecprog returned %d", rc)
    return o_num, name


def read_alarms(client: FocasClient) -> tuple[AlarmEntry, ...]:
    """Read active alarms. Prefers `cnc_rdalmmsg2` (64-char message)."""
    # Allocate an array of 32 alarm records. Most controls report < 10
    # active at any time; 32 is a generous bound.
    capacity = 32
    ArrayT = ODBALMMSG2 * capacity  # noqa: N806
    arr = ArrayT()
    count = ctypes.c_short(capacity)
    rc = client._lib.cnc_rdalmmsg2(
        client._handle,
        ctypes.c_short(_ALARM_TYPE_ALL),
        ctypes.byref(count),
        ctypes.cast(arr, ctypes.POINTER(ODBALMMSG2)),
    )
    raise_for_code(rc, context="cnc_rdalmmsg2")
    n = int(count.value)
    return tuple(decode_alarm(arr[i]) for i in range(n))


__all__ = [
    "parse_program_comment",
    "read_alarms",
    "read_macro",
    "read_macros",
    "read_offset_layout",
    "read_offsets",
    "read_pots_magazine",
    "read_pots_pmc",
    "read_program_info",
    "read_tool_life",
]
