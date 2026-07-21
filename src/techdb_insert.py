"""Clone-row INSERT of registry tools into a CAMWorks TechDB copy.

Takes rows from the local tool registry (``registry.db``) that have no TechDB
identity yet (``techdb_id IS NULL``), clones a known-good template row per tool
class inside a TechDB *copy* (plain-SQLite ``.cwdb`` passed via ``--db``),
overrides the identifying fields, and writes the new TechDB identity back into
the registry.

Safety model (see tasks/spec-techdb-insert.md):
- DEFAULT IS DRY-RUN. Without ``--apply`` nothing is written anywhere: both
  databases are opened read-only (SQLite URI ``mode=ro``) and the generated
  INSERTs are printed for review.
- Never touches ``*Desc`` tables, ``TechDBVerInfoTable``, or schema (no DDL).
- Column lists come from ``PRAGMA table_info`` at runtime — never positional —
  so a TechDB schema variation fails closed instead of misaligning values.
- ``ID = MAX(ID)+1`` allocated inside the write transaction; read-after-write
  verification before commit; registry write-back only after the TechDB commit.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass
from typing import cast

# Template row per tool class: class -> (table, template row ID).
# A None template ID is a deliberate fail-closed placeholder: the class is
# known but its template row has not been confirmed by dbc00per yet.
TEMPLATES: dict[str, tuple[str, int | None]] = {
    "EM/ball": ("in_MILLC", 11),  # N62 ball mill — complete feeds/speeds/holder data
    "EM/hog": ("in_MILLC", 131),  # N46
    "DRILL": ("in_DRILLS", None),  # ID pending confirmation (row with ON=1 + Vendor set)
    # TAP: nTaps table not yet mapped — resolve_template() raises NotImplementedError.
}

_PROTECTED_EXACT = frozenset({"techdbverinfotable"})
_PROTECTED_SUFFIX = "desc"

_REQUIRED_REGISTRY_COLS = frozenset(
    {"shop_label", "class", "vendor", "part_no", "techdb_id", "techdb_table"}
)


class TechDbInsertError(Exception):
    """Base for all deliberate failures in this tool."""


class ConfigError(TechDbInsertError):
    """Missing/unconfirmed configuration (template IDs, registry shape)."""


class SchemaError(TechDbInsertError):
    """Target database does not match the documented expectation."""


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def assert_writable_table(table: str) -> None:
    """Refuse protected TechDB tables. Applies to every table this tool touches."""
    lowered = table.lower()
    if lowered in _PROTECTED_EXACT or lowered.endswith(_PROTECTED_SUFFIX):
        raise SchemaError(f"table {table!r} is protected (never written by this tool)")


def resolve_template(
    tool_class: str, templates: dict[str, tuple[str, int | None]]
) -> tuple[str, int]:
    """Map a registry class to its (table, template row ID); fail closed on gaps."""
    entry = templates.get(tool_class)
    if entry is None:
        if tool_class == "TAP":
            raise NotImplementedError("TAP: nTaps table not yet mapped (spec D2)")
        raise ConfigError(f"no template configured for class {tool_class!r}")
    table, template_id = entry
    assert_writable_table(table)
    if template_id is None:
        raise ConfigError(
            f"template ID for class {tool_class!r} ({table}) not confirmed — "
            "set it in TEMPLATES after dbc00per confirms (spec D1)"
        )
    return table, template_id


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({quote_ident(table)})")]


def fetch_template_row(
    conn: sqlite3.Connection, table: str, template_id: int, columns: list[str]
) -> dict[str, object]:
    if "ID" not in columns:
        raise SchemaError(f"table {table!r} has no ID column")
    col_sql = ", ".join(quote_ident(c) for c in columns)
    cur = conn.execute(
        f"SELECT {col_sql} FROM {quote_ident(table)} WHERE {quote_ident('ID')} = ?",
        (template_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ConfigError(f"template row ID={template_id} not found in {table!r}")
    return dict(zip(columns, row, strict=True))


def next_free_id(conn: sqlite3.Connection, table: str) -> int:
    cur = conn.execute(
        f"SELECT COALESCE(MAX({quote_ident('ID')}), 0) + 1 FROM {quote_ident(table)}"
    )
    return int(cur.fetchone()[0])


def build_overrides(reg_row: dict[str, object]) -> dict[str, object]:
    """The parsed fields written over the cloned template (spec A3/A5)."""
    shop_label = str(reg_row.get("shop_label") or "").strip()
    if not shop_label:
        raise ConfigError("registry row has an empty shop_label")
    vendor = str(reg_row.get("vendor") or "").strip()
    part_no = str(reg_row.get("part_no") or "").strip()
    # Written even when blank: a new tool must not inherit the template's vendor.
    vendor_value = " ".join(p for p in (vendor, part_no) if p)
    return {"Comment": shop_label, "Description": shop_label, "Vendor": vendor_value}


def build_insert(
    table: str,
    columns: list[str],
    template_row: dict[str, object],
    overrides: dict[str, object],
    new_id: int,
) -> tuple[str, list[object]]:
    """Named-column INSERT cloning the template with overrides applied."""
    missing = [c for c in overrides if c not in columns]
    if missing:
        raise SchemaError(f"table {table!r} lacks override column(s): {', '.join(missing)}")
    values = dict(template_row)
    values["ID"] = new_id
    values.update(overrides)
    col_sql = ", ".join(quote_ident(c) for c in columns)
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT INTO {quote_ident(table)} ({col_sql}) VALUES ({placeholders})"
    return sql, [values[c] for c in columns]


def _literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, bytes | bytearray):
        return "X'" + bytes(value).hex() + "'"
    return "'" + str(value).replace("'", "''") + "'"


def render_sql(sql: str, params: list[object]) -> str:
    """Inline literals for dry-run display. Execution always stays parameterized."""
    parts = sql.split("?")
    if len(parts) - 1 != len(params):
        raise ValueError("placeholder/parameter count mismatch")
    out = [parts[0]]
    for part, value in zip(parts[1:], params, strict=True):
        out.append(_literal(value))
        out.append(part)
    return "".join(out)


def find_registry_table(conn: sqlite3.Connection) -> str:
    """The single user table carrying techdb_id + techdb_table (spec A1)."""
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    candidates = [
        t for t in tables if {"techdb_id", "techdb_table"} <= set(table_columns(conn, t))
    ]
    if len(candidates) != 1:
        raise ConfigError(
            "expected exactly one registry table with techdb_id + techdb_table columns, "
            f"found: {candidates or 'none'}"
        )
    table = candidates[0]
    missing = _REQUIRED_REGISTRY_COLS - set(table_columns(conn, table))
    if missing:
        raise ConfigError(f"registry table {table!r} missing column(s): {sorted(missing)}")
    return table


def pending_rows(
    conn: sqlite3.Connection, table: str, label: str | None = None
) -> list[dict[str, object]]:
    columns = table_columns(conn, table)
    col_sql = ", ".join(quote_ident(c) for c in columns)
    sql = (
        f"SELECT rowid AS _rowid, {col_sql} FROM {quote_ident(table)} "
        f"WHERE {quote_ident('techdb_id')} IS NULL"
    )
    params: list[object] = []
    if label is not None:
        sql += f" AND {quote_ident('shop_label')} = ?"
        params.append(label)
    return [dict(zip(["_rowid", *columns], row, strict=True)) for row in conn.execute(sql, params)]


@dataclass
class Planned:
    rowid: int
    shop_label: str
    table: str
    new_id: int
    sql: str
    params: list[object]


def _open(path: str, writable: bool) -> sqlite3.Connection:
    if not os.path.isfile(path):
        raise ConfigError(f"database file not found: {path}")
    mode = "rw" if writable else "ro"
    # URI mode never creates a missing file; ro physically blocks every write.
    return sqlite3.connect(f"file:{path}?mode={mode}", uri=True)


def _verify_inserted(
    conn: sqlite3.Connection, table: str, new_id: int, overrides: dict[str, object]
) -> None:
    col_sql = ", ".join(quote_ident(c) for c in overrides)
    row = conn.execute(
        f"SELECT {col_sql} FROM {quote_ident(table)} WHERE {quote_ident('ID')} = ?",
        (new_id,),
    ).fetchone()
    if row is None or list(row) != list(overrides.values()):
        raise TechDbInsertError(
            f"read-after-write mismatch for {table} ID={new_id}: got {row!r}"
        )


def run(
    db_path: str,
    registry_path: str,
    apply: bool,
    label: str | None = None,
    templates: dict[str, tuple[str, int | None]] | None = None,
) -> int:
    templates = TEMPLATES if templates is None else templates
    techdb = _open(db_path, writable=apply)
    registry = _open(registry_path, writable=apply)
    try:
        reg_table = find_registry_table(registry)
        rows = pending_rows(registry, reg_table, label)
        if not rows:
            print(f"nothing to do: no rows with techdb_id IS NULL in {reg_table!r}")
            return 0
        print(f"mode: {'APPLY' if apply else 'DRY-RUN (default — nothing will be written)'}")
        print(f"registry: {registry_path} table {reg_table!r} — {len(rows)} pending row(s)\n")

        planned: list[Planned] = []
        skipped: list[tuple[str, str]] = []
        allocated: dict[str, int] = {}  # per-table high-water mark for sequential IDs
        if apply:
            techdb.execute("BEGIN IMMEDIATE")
        for reg_row in rows:
            shop_label = str(reg_row.get("shop_label") or f"rowid {reg_row['_rowid']}")
            try:
                table, template_id = resolve_template(str(reg_row["class"]), templates)
                columns = table_columns(techdb, table)
                if not columns:
                    raise SchemaError(f"table {table!r} not found in TechDB copy")
                template_row = fetch_template_row(techdb, table, template_id, columns)
                new_id = max(next_free_id(techdb, table), allocated.get(table, 0) + 1)
                overrides = build_overrides(reg_row)
                sql, params = build_insert(table, columns, template_row, overrides, new_id)
            except (TechDbInsertError, NotImplementedError) as exc:
                skipped.append((shop_label, f"{type(exc).__name__}: {exc}"))
                continue
            allocated[table] = new_id
            print(f"-- {shop_label} (class {reg_row['class']}, template {table} ID {template_id})")
            print(render_sql(sql, params) + ";")
            print(
                f"-- then registry rowid {reg_row['_rowid']}: "
                f"techdb_id={new_id}, techdb_table='{table}'\n"
            )
            if apply:
                techdb.execute(sql, params)
                _verify_inserted(techdb, table, new_id, overrides)
            rowid = cast(int, reg_row["_rowid"])
            planned.append(Planned(rowid, shop_label, table, new_id, sql, params))

        if apply and planned:
            techdb.commit()
            for p in planned:
                cur = registry.execute(
                    f"UPDATE {quote_ident(reg_table)} "
                    f"SET {quote_ident('techdb_id')} = ?, {quote_ident('techdb_table')} = ? "
                    "WHERE rowid = ?",
                    (p.new_id, p.table, p.rowid),
                )
                if cur.rowcount != 1:
                    registry.rollback()
                    raise TechDbInsertError(
                        f"registry write-back matched {cur.rowcount} rows for rowid {p.rowid}"
                    )
            registry.commit()
        elif apply:
            techdb.rollback()

        verb = "inserted + written back" if apply else "planned (not executed)"
        print(f"{len(planned)} row(s) {verb}; {len(skipped)} skipped")
        for shop_label, reason in skipped:
            print(f"  SKIPPED {shop_label}: {reason}")
        return 1 if skipped else 0
    finally:
        techdb.close()
        registry.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Clone-row INSERT of pending registry tools into a TechDB COPY. "
        "Dry-run by default; --apply required to write anything."
    )
    parser.add_argument("--db", required=True, help="path to the TechDB copy (.cwdb, plain SQLite)")
    parser.add_argument("--registry", default="registry.db", help="path to registry.db")
    parser.add_argument("--label", default=None, help="only process rows with this shop_label")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry", action="store_true", help="print INSERTs, execute nothing (default)")
    mode.add_argument("--apply", action="store_true", help="actually execute against the copy")
    args = parser.parse_args(argv)
    try:
        return run(args.db, args.registry, apply=args.apply, label=args.label)
    except TechDbInsertError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
