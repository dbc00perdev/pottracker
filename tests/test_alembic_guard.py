"""Tests for migrations/_guard.py — tracker-isolation logic (R1).

Uses real Alembic op objects (not text scraping) so the tests reflect what
the guard actually sees during real migrations. Every bypass that Bug 1
(FK schema lives in op.kw, not op.schema) and Bug 2 (schema=None falls
through to PostgreSQL search_path default) opened up is covered here with
a dedicated negative test.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.operations.ops import (
    AddColumnOp,
    AlterColumnOp,
    CreateForeignKeyOp,
    CreateIndexOp,
    CreatePrimaryKeyOp,
    CreateTableOp,
    DropConstraintOp,
    DropTableOp,
    ExecuteSQLOp,
    ModifyTableOps,
    RenameTableOp,
)

from migrations._guard import (
    ALLOWED_SCHEMAS,
    FORBIDDEN_SCHEMAS,
    SEARCH_PATH_SQL,
    check_op_schemas,
    include_object,
    process_revision_directives,
    runtime_ddl_check,
    walk_ops,
)

# --- helpers ----------------------------------------------------------------


def _table_op(schema: str | None) -> CreateTableOp:
    return CreateTableOp("foo", columns=[sa.Column("id", sa.Integer)], schema=schema)


def _fk_op(source_schema: str | None, referent_schema: str | None) -> CreateForeignKeyOp:
    return CreateForeignKeyOp(
        constraint_name="fk_x",
        source_table="t",
        referent_table="u",
        local_cols=["x"],
        remote_cols=["y"],
        source_schema=source_schema,
        referent_schema=referent_schema,
    )


# --- positive cases ---------------------------------------------------------


class TestAllowedSchemasPass:
    @pytest.mark.parametrize("schema", sorted(ALLOWED_SCHEMAS))
    def test_create_table(self, schema):
        check_op_schemas(_table_op(schema))

    def test_fk_within_allowed(self):
        check_op_schemas(_fk_op(source_schema="tooling", referent_schema="shared"))


# --- Bug 2: schema=None must be refused (search_path bypass) ---------------


class TestNoneSchemaRefused:
    def test_create_table_with_schema_none_refused(self):
        with pytest.raises(RuntimeError, match="None"):
            check_op_schemas(_table_op(None))

    def test_fk_with_none_source_refused(self):
        with pytest.raises(RuntimeError, match="None"):
            check_op_schemas(_fk_op(source_schema=None, referent_schema="tooling"))

    def test_fk_with_none_referent_refused(self):
        with pytest.raises(RuntimeError, match="None"):
            check_op_schemas(_fk_op(source_schema="tooling", referent_schema=None))


# --- Bug 1: FK schemas live in op.kw, not on the op itself -----------------


class TestForeignKeyKwIntrospection:
    def test_fk_referent_tracker_refused(self):
        with pytest.raises(RuntimeError, match="tracker"):
            check_op_schemas(_fk_op(source_schema="tooling", referent_schema="tracker"))

    def test_fk_source_tracker_refused(self):
        with pytest.raises(RuntimeError, match="tracker"):
            check_op_schemas(_fk_op(source_schema="tracker", referent_schema="tooling"))

    def test_fk_both_tracker_refused(self):
        with pytest.raises(RuntimeError, match="tracker"):
            check_op_schemas(_fk_op(source_schema="tracker", referent_schema="tracker"))

    def test_fk_unknown_schema_refused(self):
        with pytest.raises(RuntimeError, match="unknown schema"):
            check_op_schemas(_fk_op(source_schema="public", referent_schema="tooling"))


# --- Tracker / unknown schemas refused on every common op type ------------


class TestForbiddenSchemaAllOpTypes:
    """Every common alembic op with schema='tracker' must fail. Spot-check
    coverage so adding a new op type is a deliberate decision, not silent
    passage through the guard."""

    @pytest.mark.parametrize(
        "op_factory",
        [
            lambda: CreateTableOp("t", columns=[sa.Column("id", sa.Integer)], schema="tracker"),
            lambda: AddColumnOp("t", sa.Column("c", sa.Integer), schema="tracker"),
            lambda: AlterColumnOp("t", "c", schema="tracker"),
            lambda: CreateIndexOp("ix", "t", ["c"], schema="tracker"),
            lambda: DropTableOp("t", schema="tracker"),
            lambda: RenameTableOp("t", "new_t", schema="tracker"),
            lambda: DropConstraintOp("cn", "t", schema="tracker"),
            lambda: CreatePrimaryKeyOp("pk", "t", ["c"], schema="tracker"),
            lambda: ModifyTableOps("t", ops=[], schema="tracker"),
        ],
    )
    def test_op_with_tracker_schema_refused(self, op_factory):
        with pytest.raises(RuntimeError, match="tracker"):
            check_op_schemas(op_factory())


# --- ExecuteSQLOp refused outright -----------------------------------------


class TestExecuteSqlRefused:
    def test_execute_sql_refused(self):
        with pytest.raises(RuntimeError, match="ExecuteSQLOp"):
            check_op_schemas(ExecuteSQLOp("CREATE TABLE foo (id INT)"))

    def test_execute_sql_refused_even_with_innocuous_sql(self):
        with pytest.raises(RuntimeError, match="ExecuteSQLOp"):
            check_op_schemas(ExecuteSQLOp("SELECT 1"))


# --- Nested op containers must be walked -----------------------------------


class TestNestedOpsWalked:
    """ModifyTableOps wraps multiple ops on the same table; the walker
    must recurse so a bad nested op can't hide inside a clean wrapper."""

    def test_walk_ops_yields_nested(self):
        nested = AddColumnOp("t", sa.Column("x", sa.Integer), schema="tooling")
        wrapper = ModifyTableOps("t", ops=[nested], schema="tooling")
        container = SimpleNamespace(ops=[wrapper])
        yielded = list(walk_ops(container))
        assert wrapper in yielded
        assert nested in yielded

    def test_directives_walker_catches_bad_nested_fk(self):
        nested_bad = _fk_op(source_schema="tooling", referent_schema="tracker")
        wrapper = ModifyTableOps("t", ops=[nested_bad], schema="tooling")
        directive = SimpleNamespace(
            upgrade_ops=SimpleNamespace(ops=[wrapper]),
            downgrade_ops=None,
        )
        with pytest.raises(RuntimeError, match="tracker"):
            process_revision_directives(None, None, [directive])

    def test_directives_walker_catches_nested_none_schema(self):
        nested_bad = AddColumnOp("t", sa.Column("x", sa.Integer), schema=None)
        wrapper = ModifyTableOps("t", ops=[nested_bad], schema="tooling")
        directive = SimpleNamespace(
            upgrade_ops=SimpleNamespace(ops=[wrapper]),
            downgrade_ops=None,
        )
        with pytest.raises(RuntimeError, match="None"):
            process_revision_directives(None, None, [directive])

    def test_directives_walker_clean_pass(self):
        good = _fk_op(source_schema="tooling", referent_schema="shared")
        directive = SimpleNamespace(
            upgrade_ops=SimpleNamespace(ops=[good]),
            downgrade_ops=None,
        )
        process_revision_directives(None, None, [directive])  # no raise


# --- Runtime DDL guard -----------------------------------------------------


class TestRuntimeDdlCheck:
    @pytest.mark.parametrize(
        "stmt",
        [
            "CREATE TABLE tooling.foo (id INT)",
            "ALTER TABLE shared.user ADD COLUMN x INT",
            "DROP INDEX tooling.ix_foo",
            'CREATE TABLE "tooling"."foo" (id INT)',
            "SELECT * FROM tracker.users",  # not DDL — passes
            "SELECT 1",  # not DDL
            "",  # empty — passes
        ],
    )
    def test_passes(self, stmt):
        runtime_ddl_check(stmt)

    @pytest.mark.parametrize(
        "stmt",
        [
            "CREATE TABLE tracker.foo (id INT)",
            "ALTER TABLE tracker.users ADD COLUMN x INT",
            "DROP TABLE tracker.users",
            "CREATE INDEX ix ON tracker.users (id)",
            'CREATE TABLE "tracker"."foo" (id INT)',
            "ALTER TABLE tooling.foo ADD CONSTRAINT fk FOREIGN KEY (uid) "
            "REFERENCES tracker.users(id)",
            "GRANT SELECT ON tracker.users TO lance_tooling",
            "TRUNCATE TABLE tracker.audit_log",
        ],
    )
    def test_refuses(self, stmt):
        with pytest.raises(RuntimeError, match="tracker"):
            runtime_ddl_check(stmt)


# --- include_object --------------------------------------------------------


class TestIncludeObject:
    class _FakeObj:
        def __init__(self, schema: str | None):
            self.schema = schema

    def test_includes_tooling_table(self):
        assert include_object(self._FakeObj("tooling"), "t", "table", False, None) is True

    def test_includes_shared_table(self):
        assert include_object(self._FakeObj("shared"), "t", "table", False, None) is True

    def test_excludes_tracker_table(self):
        assert include_object(self._FakeObj("tracker"), "t", "table", False, None) is False

    def test_excludes_unknown_schema_table(self):
        assert include_object(self._FakeObj("public"), "t", "table", False, None) is False

    def test_includes_obj_without_schema_attribute(self):
        class NoSchema:
            pass

        assert include_object(NoSchema(), "t", "table", False, None) is True

    def _make_fake_fk(self, src_schema: str | None, ref_schema: str | None):
        class FakeTable:
            def __init__(self, s):
                self.schema = s

        class FakeFK:
            pass

        fk = FakeFK()
        fk.table = FakeTable(src_schema)
        fk.referred_table = FakeTable(ref_schema)
        return fk

    def test_fk_to_forbidden_referent_excluded(self):
        fk = self._make_fake_fk("tooling", "tracker")
        assert include_object(fk, "fk", "foreign_key_constraint", False, None) is False

    def test_fk_from_forbidden_source_excluded(self):
        fk = self._make_fake_fk("tracker", "tooling")
        assert include_object(fk, "fk", "foreign_key_constraint", False, None) is False

    def test_fk_within_allowed_included(self):
        fk = self._make_fake_fk("tooling", "shared")
        assert include_object(fk, "fk", "foreign_key_constraint", False, None) is True


# --- Search-path lockdown SQL ---------------------------------------------


class TestSearchPathSql:
    def test_search_path_only_includes_allowed_schemas(self):
        assert SEARCH_PATH_SQL.startswith("SET search_path TO ")
        for schema in ALLOWED_SCHEMAS:
            assert schema in SEARCH_PATH_SQL
        for forbidden in FORBIDDEN_SCHEMAS:
            assert forbidden not in SEARCH_PATH_SQL
        assert "public" not in SEARCH_PATH_SQL


# --- Schemaless-op default-deny --------------------------------------------


class TestSchemaFreeOpDefaultDeny:
    """Op types without any schema-bearing field must be in an explicit
    allowlist or the guard refuses them. This prevents a future Alembic
    op type from silently passing through."""

    def test_unknown_schemaless_op_refused(self):
        class FakeBareOp:
            pass

        with pytest.raises(RuntimeError, match="no schema-bearing"):
            check_op_schemas(FakeBareOp())
