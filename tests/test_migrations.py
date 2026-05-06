"""Tests for the Phase 2 Alembic migrations.

Two layers of validation:

  1. Structural — every migration file imports cleanly, has the right
     revision metadata, and forms a single linear chain (`down_revision`
     graph).

  2. Schema-isolation — render the full migration plan to SQL via
     `alembic upgrade --sql head` (offline mode, no DB needed) and feed
     every emitted statement through `migrations._guard.runtime_ddl_check`.
     If a future migration accidentally targets a forbidden schema, this
     test catches it before the SQL is ever applied to a real DB.

The Alembic offline render uses the stub `sqlalchemy.url` in `alembic.ini`
(no real connection). The output is the exact SQL text the runtime guard
would see in production.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

from migrations._guard import (
    ALLOWED_SCHEMAS,
    FORBIDDEN_SCHEMAS,
    runtime_ddl_check,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"


# ============================================================================
# Discovery
# ============================================================================


def _migration_files() -> list[Path]:
    return sorted(p for p in VERSIONS_DIR.glob("*.py") if not p.name.startswith("_"))


def _load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def migrations() -> list:
    return [_load_migration(p) for p in _migration_files()]


# ============================================================================
# Structural
# ============================================================================


class TestStructure:
    def test_at_least_one_migration_present(self, migrations):
        assert len(migrations) >= 1

    def test_each_has_revision(self, migrations):
        for m in migrations:
            assert isinstance(m.revision, str) and m.revision
            assert callable(m.upgrade)
            assert callable(m.downgrade)

    def test_revisions_form_linear_chain(self, migrations):
        # Build the revision -> down_revision map and verify there is
        # exactly one root (down_revision is None) and a chain that
        # reaches every other revision.
        by_rev = {m.revision: m for m in migrations}
        roots = [m for m in migrations if m.down_revision is None]
        assert len(roots) == 1, f"expected exactly one root migration, got {len(roots)}"
        # walk forward from the root
        seen = {roots[0].revision}
        cur = roots[0].revision
        while True:
            nxt = next((m for m in migrations if m.down_revision == cur), None)
            if nxt is None:
                break
            assert nxt.revision not in seen, f"cycle at {nxt.revision}"
            seen.add(nxt.revision)
            cur = nxt.revision
        assert seen == set(by_rev.keys()), (
            f"orphaned migrations not reachable from root: " f"{set(by_rev.keys()) - seen}"
        )


# ============================================================================
# Schema-isolation — drives the real Alembic offline-SQL renderer
# ============================================================================


def _render_offline_sql() -> str:
    """Run `alembic upgrade --sql head` and return stdout. Offline mode
    requires no DB connection; the configured URL in alembic.ini is a
    placeholder."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "--sql", "head"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"alembic upgrade --sql head failed (rc={result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout


# `alembic` emits SQL as semicolon-separated statements separated by
# blank lines. Split on `;` followed by whitespace; drop empties and
# comments.
_STATEMENT_SPLIT_RE = re.compile(r";\s*\n", re.MULTILINE)


def _split_statements(sql: str) -> list[str]:
    out: list[str] = []
    for stmt in _STATEMENT_SPLIT_RE.split(sql):
        cleaned = "\n".join(
            line for line in stmt.splitlines() if line.strip() and not line.strip().startswith("--")
        ).strip()
        if cleaned:
            out.append(cleaned)
    return out


@pytest.fixture(scope="module")
def rendered_sql() -> str:
    return _render_offline_sql()


@pytest.fixture(scope="module")
def rendered_statements(rendered_sql: str) -> list[str]:
    return _split_statements(rendered_sql)


class TestSchemaIsolation:
    def test_render_succeeds(self, rendered_sql):
        # Smoke check: render produced something and includes our schemas
        # but no forbidden ones.
        assert "CREATE SCHEMA IF NOT EXISTS shared" in rendered_sql
        for forbidden in FORBIDDEN_SCHEMAS:
            assert (
                f"CREATE SCHEMA IF NOT EXISTS {forbidden}" not in rendered_sql
            ), f"migration creates forbidden schema {forbidden!r}"

    def test_every_statement_passes_runtime_ddl_check(self, rendered_statements):
        for stmt in rendered_statements:
            runtime_ddl_check(stmt)  # raises on forbidden-schema reference

    def test_qualified_table_refs_are_in_allowlist(self, rendered_statements):
        # Pick out every `<schema>.<identifier>` and verify every
        # schema named is in ALLOWED_SCHEMAS. Schemas referenced by
        # `WITH SCHEMA <name>` (CREATE EXTENSION) are intentionally not
        # caught by this regex; they're still validated by
        # runtime_ddl_check above.
        qualifier_re = re.compile(
            r"""(?:^|[\s\(,;=])"?([a-z_][a-z0-9_]*)"?\s*\.\s*"?[a-z_]""",
            re.IGNORECASE | re.VERBOSE,
        )
        seen_schemas: set[str] = set()
        for stmt in rendered_statements:
            for m in qualifier_re.finditer(stmt):
                schema = m.group(1).lower()
                # Skip fully-qualified function refs in CHECK constraints
                # that legitimately reference allowed schemas.
                seen_schemas.add(schema)
        unknown = seen_schemas - ALLOWED_SCHEMAS
        # Strip well-known false positives:
        #   - `pg_catalog`, `information_schema` — system catalogs
        #   - `alembic_version` — alembic's bookkeeping TABLE (the regex
        #     can't tell `<schema>.<table>` from `<table>.<column>`,
        #     and alembic emits `alembic_version.version_num` in UPDATE
        #     WHERE clauses)
        unknown = {
            s
            for s in unknown
            if not s.startswith("pg_") and s != "information_schema" and s != "alembic_version"
        }
        assert not unknown, f"migration references unknown schemas: {unknown}"


# ============================================================================
# Specific contract checks for the Phase 2 tables
# ============================================================================


class TestPhase2TablesPresent:
    @pytest.mark.parametrize(
        "table_name",
        [
            "machine",
            '"user"',
            "audit_log",
            "focas_offset_register",
            "focas_pot",
            "focas_tool_life",
        ],
    )
    def test_table_created_in_shared(self, rendered_sql, table_name):
        # `CREATE TABLE shared.<name>` appears somewhere in the offline SQL.
        # Trailing word-boundary doesn't work past a closing `"`, so match
        # via the next-char predicate (paren or whitespace).
        pattern = re.compile(
            rf"CREATE\s+TABLE\s+shared\.{re.escape(table_name)}[\s(]",
            re.IGNORECASE,
        )
        assert pattern.search(rendered_sql), f"shared.{table_name} not created by any migration"

    def test_pgcrypto_extension_in_shared_schema(self, rendered_sql):
        assert "CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA shared" in rendered_sql

    def test_audit_log_indexes(self, rendered_sql):
        for ix in (
            "ix_audit_log_occurred_at",
            "ix_audit_log_machine_occurred",
            "ix_audit_log_entity",
        ):
            assert ix in rendered_sql, f"missing audit_log index {ix}"

    def test_offset_register_check_constraint(self, rendered_sql):
        assert "ck_focas_offset_register_type" in rendered_sql

    def test_machine_atc_strategy_check_constraint(self, rendered_sql):
        assert "ck_machine_atc_strategy" in rendered_sql


# ============================================================================
# Downgrade rendering — at minimum, alembic must be able to produce it
# ============================================================================


class TestDowngrade:
    def test_downgrade_to_base_renders(self):
        # `alembic downgrade --sql head:base` renders the full reverse path.
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "downgrade",
                "--sql",
                "head:base",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            check=False,
        )
        assert result.returncode == 0, f"downgrade render failed: {result.stderr}"
        out = result.stdout
        assert "DROP TABLE shared.machine" in out
        assert "DROP TABLE shared.focas_offset_register" in out
