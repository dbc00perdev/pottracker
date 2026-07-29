"""Generated, standardized tool description — the human-readable / associative
half of the tool label, DERIVED from attributes (never stored as identity).

Per the tool-numbering spec (`tasks/spec-tool-numbering.md`): the permanent
identity is the non-significant GTID (`tool.short_id`); this module produces the
descriptive string shown next to it (e.g. `100042 · 1/2in 4FL SQ CARBIDE TiAlN`).
Because it is computed, it can never go stale relative to the tool's attributes —
if a spec changes, the description regenerates; identity never moves. This is the
ISO-13399-style "attributes carry the meaning" approach.

Pure (no I/O). One canonical source of truth for the label used by the API
(`ToolOut.description`), the intake importer's dry-run preview, and any future
CAMWorks-TechDB sync.
"""

from __future__ import annotations

from decimal import Decimal

# Short type codes keyed on the seeded tool_type.code (scripts/seed_tool_types).
# Falls back to the type's display_name uppercased for unknown codes.
_TYPE_SHORT: dict[str, str] = {
    "em_square": "SQ EM",
    "em_ball": "BALL EM",
    "em_corner_radius": "CR EM",
    "face_mill": "FACE MILL",
    "chamfer": "CHAMFER",
    "spot_drill": "SPOT DRILL",
    "drill": "DRILL",
    "reamer": "REAMER",
    "tap": "TAP",
    "probe": "PROBE",
    "turn": "TURN",
    "cutoff": "CUTOFF",
    "bar_puller": "BAR PULLER",
}


def _trim(value: Decimal | float | int | str | None) -> str | None:
    """Fixed-point string with trailing zeros trimmed ('12.7000' -> '12.7',
    '10.00' -> '10'). None-safe. Avoids Decimal.normalize()'s scientific
    notation on trailing-zero integers."""
    if value is None:
        return None
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    s = f"{d:f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def tool_description(
    *,
    type_code: str,
    type_display: str,
    diameter_mm: Decimal | float | int | None,
    diameter_inch: Decimal | float | int | None = None,
    flute_count: int | None = None,
    substrate: str | None = None,
    coating: str | None = None,
    corner_radius_mm: Decimal | float | int | None = None,
) -> str:
    """Build the standardized description. Imperial diameter is preferred when
    present (the shop specs tools in inches); otherwise metric mm. Null parts are
    omitted, so a bare drill yields just '6mm DRILL'."""
    parts: list[str] = []

    if diameter_inch is not None:
        parts.append(f"{_trim(diameter_inch)}in")
    elif diameter_mm is not None:
        parts.append(f"{_trim(diameter_mm)}mm")

    if flute_count:
        parts.append(f"{flute_count}FL")

    parts.append(_TYPE_SHORT.get(type_code, type_display.upper()))

    if corner_radius_mm:
        parts.append(f"R{_trim(corner_radius_mm)}")

    if substrate:
        parts.append(substrate.upper())
    if coating:
        parts.append(coating.upper())

    return " ".join(p for p in parts if p)


__all__ = ["tool_description"]
