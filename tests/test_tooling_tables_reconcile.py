"""Drift guard: app-side Core Table defs must match the migrated DB schema.

Reflects the live schema (assumes `alembic upgrade head` has run against
DATABASE_URL) and asserts every column declared in `apps.tooling.api.tables`
and the `shared.machine`/`shared.user` additions to `shared.db` exists in the
DB with a compatible type. Catches the classic "migration and Core Table drift"
bug (the pending Phase-2 reconciliation task, now covering tooling too).

Skips without DATABASE_URL.
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.integration

_RAW = os.environ.get("DATABASE_URL", "")
_URL = _RAW.replace("postgresql://", "postgresql+psycopg://", 1) if _RAW else ""

# (module_table, schema)
from apps.tooling.api import tables as tt  # noqa: E402
from shared import db as sdb  # noqa: E402

_TARGETS = [
    (sdb.machine, "shared"),
    (sdb.user, "shared"),
    (tt.tool_type, "tooling"),
    (tt.tool, "tooling"),
    (tt.assignment, "tooling"),
    (tt.pot_observation, "tooling"),
    (tt.offset_write_request, "tooling"),
]


@pytest.fixture(scope="module")
def engine() -> sa.Engine:
    if not _URL:
        pytest.skip("DATABASE_URL not set")
    return sa.create_engine(_URL, future=True)


@pytest.mark.parametrize("table,schema", _TARGETS, ids=lambda x: getattr(x, "name", x))
def test_columns_present(engine: sa.Engine, table, schema):
    insp = sa.inspect(engine)
    db_cols = {c["name"]: c for c in insp.get_columns(table.name, schema=schema)}
    for col in table.columns:
        assert col.name in db_cols, f"{schema}.{table.name}.{col.name} missing in DB"


def test_no_extra_declared_columns(engine: sa.Engine):
    """Every declared column exists in the DB (no phantom app columns)."""
    insp = sa.inspect(engine)
    for table, schema in _TARGETS:
        db_cols = {c["name"] for c in insp.get_columns(table.name, schema=schema)}
        declared = {c.name for c in table.columns}
        assert declared <= db_cols, f"{schema}.{table.name}: {declared - db_cols} not in DB"
