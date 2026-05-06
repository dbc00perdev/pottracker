"""Alembic environment for lance-tooling.

Tracker-isolation guard (R1 mitigation): this env REFUSES to run a migration
that touches any schema other than `tooling` or `shared`. The Lance CNC
Tracker owns `tracker.*`; tooling never writes there.

The guard runs in two places:
  1. `include_object` — filters out anything outside the allowlist during
     autogenerate so migrations can't accidentally pick up tracker tables.
  2. `process_revision_directives` — refuses to write a revision file that
     references a forbidden schema, even if hand-edited.

Empty `metadata` is fine for v1: migrations are written by hand. When models
land in Phase 3, replace `target_metadata = None` with the model registry's
metadata and the autogenerate filter does the rest.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

_logger = logging.getLogger("alembic.env")

ALLOWED_SCHEMAS: frozenset[str] = frozenset({"tooling", "shared"})
FORBIDDEN_SCHEMAS: frozenset[str] = frozenset({"tracker"})

config = context.config

target_metadata = None


def _check_schema(schema: str | None, source: str) -> None:
    if schema is None:
        return
    if schema in FORBIDDEN_SCHEMAS:
        raise RuntimeError(
            f"Refusing migration: {source} targets forbidden schema '{schema}'. "
            "Tooling migrations may only touch 'tooling' or 'shared'. "
            "See docs/07-risks.md R1."
        )
    if schema not in ALLOWED_SCHEMAS:
        raise RuntimeError(
            f"Refusing migration: {source} targets unknown schema '{schema}'. "
            f"Allowed: {sorted(ALLOWED_SCHEMAS)}."
        )


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    schema = getattr(obj, "schema", None)
    if schema is None:
        return True
    if schema in FORBIDDEN_SCHEMAS:
        _logger.warning("excluding %s '%s' in forbidden schema '%s'", type_, name, schema)
        return False
    return schema in ALLOWED_SCHEMAS


_SCHEMA_REF_RE = re.compile(
    r"""schema\s*=\s*['"](?P<schema>[a-zA-Z_][a-zA-Z0-9_]*)['"]"""
)


def _scan_script_for_schemas(script_text: str) -> Iterable[str]:
    return {m.group("schema") for m in _SCHEMA_REF_RE.finditer(script_text)}


def process_revision_directives(context_, revision, directives) -> None:
    for directive in directives:
        upgrade_ops = getattr(directive, "upgrade_ops", None)
        downgrade_ops = getattr(directive, "downgrade_ops", None)
        for ops in (upgrade_ops, downgrade_ops):
            if ops is None:
                continue
            for op in getattr(ops, "ops", []):
                schema = getattr(op, "schema", None)
                _check_schema(schema, f"op {type(op).__name__}")


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        process_revision_directives=process_revision_directives,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            process_revision_directives=process_revision_directives,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    try:
        run_migrations_online()
    except Exception as exc:  # pragma: no cover
        print(f"alembic env failed: {exc}", file=sys.stderr)
        raise
