"""Tests for shared.focas.errors."""

from __future__ import annotations

import pytest

from shared.focas.errors import (
    FocasAlarmError,
    FocasError,
    FocasHandleError,
    FocasRejectedError,
    raise_for_code,
)


class TestRaiseForCode:
    def test_zero_is_noop(self):
        # No exception raised; explicit return None.
        assert raise_for_code(0) is None
        assert raise_for_code(0, context="cnc_rdtofs") is None

    def test_unmapped_nonzero_raises_generic(self):
        with pytest.raises(FocasError) as ei:
            raise_for_code(99, context="cnc_rdtofs")
        assert ei.value.code == 99
        assert ei.value.context == "cnc_rdtofs"
        assert "cnc_rdtofs" in str(ei.value)

    def test_message_propagated(self):
        with pytest.raises(FocasError) as ei:
            raise_for_code(99, context="cnc_x", message="weirdness")
        assert "weirdness" in str(ei.value)


class TestExceptionHierarchy:
    @pytest.mark.parametrize(
        "cls",
        [FocasHandleError, FocasAlarmError, FocasRejectedError],
    )
    def test_subclasses_inherit(self, cls):
        assert issubclass(cls, FocasError)

    def test_carries_code_and_context(self):
        e = FocasHandleError(code=-8, context="cnc_modal")
        assert e.code == -8
        assert e.context == "cnc_modal"
