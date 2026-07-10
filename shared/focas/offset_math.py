"""Pure offset math for the FOCAS write path (PR-3). No I/O, no FOCAS, no DB.

Every constant here was verified on the Lance Viper LG-1000AP (FANUC 0i-MF,
Memory-B offset model) during Phase 1 — see `tasks/lessons.md` and
`tasks/spec-phase5-write-path.md` §4. They are **control-specific and
non-negotiable**: a second control MUST re-verify param 1013 and the type-code
map on hardware before reusing this module (R8 / R9 / R18).

This module only *computes and classifies*. It performs no write and binds no
FOCAS function — the real `cnc_wrtofs` binding lands in PR-4 behind the gate,
and will call `verify_increment()` with the live param-1013 value before it
trusts any conversion here.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from shared.focas.models import RegisterType

# --- increment (the 10x hazard) ---------------------------------------------

# 0.0001 mm/count — panel cross-checked on the Viper (panel H50 = 7.4050 mm read
# back as raw counts 74050). NOT 0.001: a 10x error would silently corrupt every
# written value. PR-4 reads param 1013 live via `cnc_rdparam` and refuses the
# write if the reported increment disagrees with this (see verify_increment).
OFFSET_INCREMENT_MM = Decimal("0.0001")

# --- type-code map (H/D swapped vs the FANUC docs on THIS control) -----------

# Empirically locked on register 396 with all four panel banks distinct
# (lessons.md). Standard docs say type=1->H_GEOM, type=3->D_GEOM; this 0i-MF has
# them swapped. Hardcoding "the FANUC standard" here would mislabel every length
# offset as a diameter offset — the same class of error as guessing function
# names against the wrong control series.
REGISTER_TYPE_TO_CODE: dict[RegisterType, int] = {
    RegisterType.D_GEOM: 1,
    RegisterType.H_WEAR: 2,
    RegisterType.H_GEOM: 3,
    RegisterType.D_WEAR: 4,
}
CODE_TO_REGISTER_TYPE: dict[int, RegisterType] = {v: k for k, v in REGISTER_TYPE_TO_CODE.items()}

# --- writability policy (D2) -------------------------------------------------

# v1 writable set = H_GEOM only (D2, recommended default). Widening to H_WEAR /
# D_GEOM is the D2 follow-on once the gate is proven live — change this set, not
# the call sites.
WRITABLE_TYPES_V1: frozenset[RegisterType] = frozenset({RegisterType.H_GEOM})

# D_WEAR is structurally unreadable AND unwritable via FOCAS on this control
# (`cnc_rdtofs(type=4)` returns EW_ATTRIB regardless of value — the option bit
# is not licensed). It stays panel-only; the write path must refuse it
# regardless of any future widening of WRITABLE_TYPES_V1.
NEVER_WRITABLE: frozenset[RegisterType] = frozenset({RegisterType.D_WEAR})

# --- plausibility ------------------------------------------------------------

# A change larger than this vs the prior value is flagged for explicit operator
# confirmation, never written silently (CLAUDE.md offset rules / R6).
LARGE_DIFF_THRESHOLD_MM = Decimal("0.5")

# Corrupt-value guard (mirrors shared.focas.models bounds). Narrow per-register
# physical ranges are a later refinement; this catches obviously bad values.
OFFSET_ABS_MAX_MM = Decimal("9999.9999")


class OffsetMathError(ValueError):
    """A write value or register type that offset math refuses outright."""


def counts_from_mm(value_mm: Decimal) -> int:
    """Convert mm -> integer FANUC counts at the write boundary.

    Rounds half-up to the nearest count. Conversion happens ONLY here (and its
    inverse) — never in business logic (CLAUDE.md offset math rule).
    """
    counts = (value_mm / OFFSET_INCREMENT_MM).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(counts)


def mm_from_counts(counts: int) -> Decimal:
    """Inverse of `counts_from_mm`, quantized to the 0.0001 mm grid."""
    return (Decimal(counts) * OFFSET_INCREMENT_MM).quantize(Decimal("0.0001"))


def register_type_code(register_type: RegisterType) -> int:
    """FANUC `cnc_wrtofs`/`cnc_rdtofs` type code for a register type."""
    return REGISTER_TYPE_TO_CODE[register_type]


def is_writable(register_type: RegisterType) -> bool:
    """True only for register types the v1 write path may target."""
    return register_type in WRITABLE_TYPES_V1 and register_type not in NEVER_WRITABLE


def assert_writable(register_type: RegisterType) -> None:
    """Raise OffsetMathError if this register type may not be written in v1.

    D_WEAR is refused unconditionally (panel-only); other non-v1 types are
    refused as "not enabled yet" (D2).
    """
    if register_type in NEVER_WRITABLE:
        raise OffsetMathError(
            f"{register_type.value} is panel-only and can never be written via FOCAS "
            "on this control (unlicensed option) — edit it at the panel"
        )
    if register_type not in WRITABLE_TYPES_V1:
        raise OffsetMathError(
            f"{register_type.value} is not writable in v1 (D2: H_GEOM only)"
        )


def within_bounds(value_mm: Decimal) -> bool:
    """Corrupt-value guard: value within the physical envelope of the table."""
    return -OFFSET_ABS_MAX_MM <= value_mm <= OFFSET_ABS_MAX_MM


def diff_mm(old_mm: Decimal, new_mm: Decimal) -> Decimal:
    """Absolute magnitude of the change, on the 0.0001 mm grid."""
    return abs(new_mm - old_mm).quantize(Decimal("0.0001"))


def is_large_diff(old_mm: Decimal, new_mm: Decimal) -> bool:
    """True when |new - old| exceeds the operator-confirmation threshold."""
    return diff_mm(old_mm, new_mm) > LARGE_DIFF_THRESHOLD_MM


def verify_increment(reported_increment_mm: Decimal) -> None:
    """PR-4 hook: refuse the whole write path if the control's live increment
    (from param 1013) disagrees with the assumed 0.0001 mm/count.

    Not wired to hardware here — offset math is pure. PR-4's `cnc_wrtofs`
    binding calls this with the `cnc_rdparam` value before converting anything,
    closing the 10x hazard for a second control.
    """
    if reported_increment_mm != OFFSET_INCREMENT_MM:
        raise OffsetMathError(
            f"control increment {reported_increment_mm} mm/count disagrees with the "
            f"assumed {OFFSET_INCREMENT_MM} — refusing all writes (10x scaling hazard)"
        )


__all__ = [
    "CODE_TO_REGISTER_TYPE",
    "LARGE_DIFF_THRESHOLD_MM",
    "NEVER_WRITABLE",
    "OFFSET_ABS_MAX_MM",
    "OFFSET_INCREMENT_MM",
    "OffsetMathError",
    "REGISTER_TYPE_TO_CODE",
    "WRITABLE_TYPES_V1",
    "assert_writable",
    "counts_from_mm",
    "diff_mm",
    "is_large_diff",
    "is_writable",
    "mm_from_counts",
    "register_type_code",
    "verify_increment",
    "within_bounds",
]
