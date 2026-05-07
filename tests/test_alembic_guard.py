"""Tests for the Alembic schema-isolation guard.

R1 mitigation: tooling migrations must never touch tracker tables. The guard
in migrations/env.py is verified here by importing the helper functions in
isolation, since the env.py module body runs Alembic at import time.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_guard():
    """Load just the helper functions from migrations/env.py without executing
    the Alembic context startup at the bottom of the file."""
    src = Path(__file__).resolve().parents[1] / "migrations" / "env.py"
    text = src.read_text()
    head, _, _ = text.partition("if context.is_offline_mode():")
    head = head.replace("from alembic import context", "context = None  # test stub")
    head = head.replace(
        "from sqlalchemy import engine_from_config, pool",
        "engine_from_config = None  # test stub\npool = None  # test stub",
    )
    head = head.replace("config = context.config", "config = None  # test stub")
    spec = importlib.util.spec_from_loader("alembic_env_under_test", loader=None)
    mod = importlib.util.module_from_spec(spec)
    exec(compile(head, str(src), "exec"), mod.__dict__)
    sys.modules["alembic_env_under_test"] = mod
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load_guard()


class TestCheckSchema:
    def test_allows_tooling(self, guard):
        guard._check_schema("tooling", "test")

    def test_allows_shared(self, guard):
        guard._check_schema("shared", "test")

    def test_allows_none(self, guard):
        guard._check_schema(None, "test")

    def test_blocks_tracker(self, guard):
        with pytest.raises(RuntimeError, match="forbidden schema 'tracker'"):
            guard._check_schema("tracker", "test op")

    def test_blocks_unknown(self, guard):
        with pytest.raises(RuntimeError, match="unknown schema 'public'"):
            guard._check_schema("public", "test op")


class TestIncludeObject:
    class _Obj:
        def __init__(self, schema):
            self.schema = schema

    def test_includes_tooling(self, guard):
        assert guard.include_object(self._Obj("tooling"), "t", "table", False, None) is True

    def test_excludes_tracker(self, guard):
        assert guard.include_object(self._Obj("tracker"), "t", "table", False, None) is False

    def test_excludes_unknown(self, guard):
        assert guard.include_object(self._Obj("public"), "t", "table", False, None) is False

    def test_includes_no_schema_obj(self, guard):
        class NoSchema:
            pass

        assert guard.include_object(NoSchema(), "t", "table", False, None) is True
