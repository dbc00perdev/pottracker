"""Generated tool description (tool_label.tool_description) — pure, no DB."""

from __future__ import annotations

from decimal import Decimal

from apps.tooling.api.services.tool_label import tool_description


def test_square_endmill_imperial_full():
    d = tool_description(
        type_code="em_square", type_display="Square Endmill",
        diameter_mm=Decimal("12.7000"), diameter_inch=Decimal("0.50000"),
        flute_count=4, substrate="carbide", coating="tialn",
    )
    assert d == "0.5in 4FL SQ EM CARBIDE TIALN"


def test_metric_fallback_when_no_inch():
    d = tool_description(
        type_code="drill", type_display="Drill",
        diameter_mm=Decimal("6.3500"), diameter_inch=None,
    )
    assert d == "6.35mm DRILL"


def test_trailing_zero_integer_trimmed_not_scientific():
    d = tool_description(
        type_code="face_mill", type_display="Face Mill",
        diameter_mm=Decimal("10.0000"), diameter_inch=None, flute_count=5,
    )
    assert d == "10mm 5FL FACE MILL"


def test_corner_radius_included():
    d = tool_description(
        type_code="em_corner_radius", type_display="Corner-Radius Endmill",
        diameter_mm=Decimal("6.0000"), flute_count=4,
        corner_radius_mm=Decimal("0.5000"), substrate="carbide",
    )
    assert d == "6mm 4FL CR EM R0.5 CARBIDE"


def test_missing_coating_and_flutes_omitted():
    d = tool_description(
        type_code="reamer", type_display="Reamer",
        diameter_mm=Decimal("8.0000"), substrate="hss",
    )
    assert d == "8mm REAMER HSS"


def test_unknown_type_code_falls_back_to_display_upper():
    d = tool_description(
        type_code="weird_new_type", type_display="Weird New Type",
        diameter_mm=Decimal("5.0000"), flute_count=2,
    )
    assert d == "5mm 2FL WEIRD NEW TYPE"


def test_corner_radius_zero_is_omitted():
    # A falsy corner radius (0) is not a real CR endmill feature -> omit.
    d = tool_description(
        type_code="em_square", type_display="Square Endmill",
        diameter_mm=Decimal("6.0000"), flute_count=3, corner_radius_mm=Decimal("0"),
    )
    assert d == "6mm 3FL SQ EM"
