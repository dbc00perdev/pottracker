"""Pure G10 offset-program formatting + parsing (spec-offset-export.md §1).

Formats verified verbatim against FANUC manuals 2026-08-06 (B-64604EN-2/01
§6.10 mill; B-64604EN-1/01 §5.1.8 + p.312 lathe — the lathe form is FANUC's
own OFFSET-screen punch format). Traps encoded here, from the spec:

- Mill: G90 forced (G91 would ADD instead of replace); every line carries an
  explicit L code (omitted L silently means L11/H-wear).
- Lathe: NO G90 (turning canned cycle in G-code system A); no T word in any
  block (PS1144); tip Q written once, on the geometry line (shared field).
- Both: every value carries an explicit decimal point (a bare number is read
  in least-increment COUNTS — a silent 10000x error); values are the
  control's NATIVE unit, never converted (spec-offset-units).

Sparse semantics: a register is emitted iff ANY bank is non-zero, and an
emitted register writes ALL its banks (zeros included) — sparseness is
register-granular, never address-granular, so a listed register can't keep
stale values in an unnamed bank. Unlisted registers are untouched by G10.

Pure: no I/O, no DB. The parser is strict (unknown blocks raise) and doubles
as the future G10-import front half — imports never auto-apply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from shared.focas.models import RegisterType

ZERO = Decimal("0")

# Decimal places per unit at IS-B resolution (0.0001 inch / 0.001 mm per
# count). Unit is always passed explicitly — no caller can do unit-blind math.
_UNIT_DECIMALS = {"inch": 4, "mm": 3}

# Mill memory-C banks, manual-verbatim L codes (B-64604EN-2/01 §6.10).
MILL_BANKS: tuple[tuple[RegisterType, str], ...] = (
    (RegisterType.H_GEOM, "L10"),
    (RegisterType.H_WEAR, "L11"),
    (RegisterType.D_GEOM, "L12"),
    (RegisterType.D_WEAR, "L13"),
)

# Lathe banks per G10 line (B-64604EN-1/01 §5.1.8): P<n> = wear,
# P<10000+n> = geometry; X/Z/R absolute addresses; Q = tip (geometry line
# only — one shared field).
LATHE_WEAR_ADDRESSES: tuple[tuple[str, RegisterType], ...] = (
    ("X", RegisterType.X_WEAR),
    ("Z", RegisterType.Z_WEAR),
    ("R", RegisterType.R_WEAR),
)
LATHE_GEOM_ADDRESSES: tuple[tuple[str, RegisterType], ...] = (
    ("X", RegisterType.X_GEOM),
    ("Z", RegisterType.Z_GEOM),
    ("R", RegisterType.R_GEOM),
)

_COMMENT_ALLOWED = re.compile(r"[^A-Z0-9 .+/#-]")

Banks = dict[str, Decimal]  # register_type value -> native value
Rows = dict[int, Banks]  # register_number -> banks


def comment_text(text: str) -> str:
    """FANUC-safe comment body: uppercase, punch-charset only."""
    return _COMMENT_ALLOWED.sub("-", text.upper())


def format_value(value: Decimal | None, unit: str) -> str:
    """Native-unit value with a guaranteed explicit decimal point."""
    decimals = _UNIT_DECIMALS.get(unit)
    if decimals is None:
        raise ValueError(f"unknown offset unit {unit!r}")
    return f"{(value if value is not None else ZERO):.{decimals}f}"


def register_is_empty(banks: Banks) -> bool:
    return all(v == ZERO for v in banks.values())


def select_registers(rows: Rows, *, sparse: bool, register_count: int) -> list[int]:
    """Sparse: registers with any non-zero bank. Full: 1..register_count,
    absent mirror rows exported as all-zero."""
    if sparse:
        return sorted(n for n, banks in rows.items() if not register_is_empty(banks))
    return list(range(1, register_count + 1))


@dataclass(frozen=True)
class G10Meta:
    machine_name: str
    machine_class: str  # "mill" | "lathe"
    unit: str
    register_count: int
    sparse: bool
    generated_at: str  # preformatted UTC stamp
    mirror_note: str  # freshness line, e.g. "MIRROR POLLED 42 SEC AGO"
    form_verified: bool = False
    program_number: int = 9999


def build_g10(rows: Rows, meta: G10Meta) -> str:
    selected = select_registers(rows, sparse=meta.sparse, register_count=meta.register_count)
    lines = ["%", f"O{meta.program_number:04d}({comment_text('POTTRACKER OFFSET EXPORT')})"]
    lines.append(f"({comment_text('MACHINE ' + meta.machine_name)})")
    lines.append(f"({comment_text('GENERATED ' + meta.generated_at)})")
    lines.append(f"({comment_text(meta.mirror_note)})")
    if meta.sparse:
        lines.append(f"({comment_text(f'SPARSE - {len(selected)} OF {meta.register_count} REGS - UNLISTED REGS UNTOUCHED')})")
    else:
        lines.append(f"({comment_text(f'FULL TABLE - WRITES ALL {meta.register_count} REGS INCL ZEROS')})")
    if not meta.form_verified:
        lines.append(f"({comment_text('FORM UNVERIFIED ON THIS MACHINE - DO NOT RUN')})")
    lines.append(f"({comment_text('UNIT ' + meta.unit)})")
    lines.append("G20" if meta.unit == "inch" else "G21")

    if meta.machine_class == "mill":
        lines.append("G90")
        for n in selected:
            banks = rows.get(n, {})
            for register_type, l_code in MILL_BANKS:
                lines.append(f"G10 {l_code} P{n} R{format_value(banks.get(register_type), meta.unit)}")
    elif meta.machine_class == "lathe":
        for n in selected:
            banks = rows.get(n, {})
            wear = " ".join(
                f"{addr}{format_value(banks.get(rt), meta.unit)}"
                for addr, rt in LATHE_WEAR_ADDRESSES
            )
            geom = " ".join(
                f"{addr}{format_value(banks.get(rt), meta.unit)}"
                for addr, rt in LATHE_GEOM_ADDRESSES
            )
            tip = int(banks.get(RegisterType.TIP) or 0)
            lines.append(f"G10 P{n} {wear}")
            lines.append(f"G10 P{10000 + n} {geom} Q{tip}")
    else:
        raise ValueError(f"unknown machine_class {meta.machine_class!r}")

    lines.append("M30")
    lines.append("%")
    return "\n".join(lines) + "\n"


# --- parser (round-trip + future import front half) ---------------------------

_MILL_L_TO_TYPE = {l_code: rt for rt, l_code in MILL_BANKS}
_MILL_RE = re.compile(r"^G10 (L1[0-3]) P(\d+) R(-?\d+\.\d+)$")
_LATHE_RE = re.compile(
    r"^G10 P(\d+) X(-?\d+\.\d+) Z(-?\d+\.\d+) R(-?\d+\.\d+)(?: Q(\d+))?$"
)
_PASSTHROUGH = re.compile(r"^(%|O\d+\(.*\)|\(.*\)|G20|G21|G90|M30)$")


@dataclass
class ParsedG10:
    rows: Rows = field(default_factory=dict)
    machine_class: str | None = None


def parse_g10(text: str) -> ParsedG10:
    """Strict parse of a file this module built. Unknown blocks raise — a
    round-trip that silently skips a line proves nothing."""
    out = ParsedG10()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _PASSTHROUGH.match(line):
            continue
        m = _MILL_RE.match(line)
        if m:
            _set_class(out, "mill", line)
            l_code, register, value = m.group(1), int(m.group(2)), Decimal(m.group(3))
            out.rows.setdefault(register, {})[_MILL_L_TO_TYPE[l_code].value] = value
            continue
        m = _LATHE_RE.match(line)
        if m:
            _set_class(out, "lathe", line)
            p_number = int(m.group(1))
            geometry = p_number > 10000
            register = p_number - 10000 if geometry else p_number
            addresses = LATHE_GEOM_ADDRESSES if geometry else LATHE_WEAR_ADDRESSES
            banks = out.rows.setdefault(register, {})
            for (_, rt), group in zip(addresses, m.group(2, 3, 4), strict=True):
                banks[rt.value] = Decimal(group)
            if geometry:
                if m.group(5) is None:
                    raise ValueError(f"lathe geometry line missing Q: {line!r}")
                banks[RegisterType.TIP.value] = Decimal(m.group(5))
            elif m.group(5) is not None:
                raise ValueError(f"lathe wear line must not carry Q: {line!r}")
            continue
        raise ValueError(f"unrecognized G10 block: {line!r}")
    return out


def _set_class(parsed: ParsedG10, machine_class: str, line: str) -> None:
    if parsed.machine_class is None:
        parsed.machine_class = machine_class
    elif parsed.machine_class != machine_class:
        raise ValueError(f"mixed mill/lathe forms in one file at: {line!r}")
