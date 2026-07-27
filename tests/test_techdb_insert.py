"""Unit tests for src/techdb_insert.py (synthetic SQLite fixtures, no real TechDB).

The synthetic TechDB mimics the documented shape (in_MILLC with template rows
ID 11 / 131, an in_MILLCDesc sibling, TechDBVerInfoTable) without claiming to
reproduce the real CAMWorks schema — the tool reads columns via PRAGMA at
runtime, so these tests exercise the mechanism, not a hardcoded column list.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import techdb_insert as ti

BALL_TEMPLATE = {
    "ID": 11,
    "ON": 1,
    "Comment": "N62",
    "Description": "N62 1/2 BALL EM",
    "Vendor": "Harvey 12345",
    "ToolDia": 0.5,
    "NoFlutes": 4,
    "HolderName": "CAT40-ER32",
}
HOG_TEMPLATE = {
    "ID": 131,
    "ON": 1,
    "Comment": "N46",
    "Description": "N46 HOG EM",
    "Vendor": "Kennametal 998",
    "ToolDia": 0.75,
    "NoFlutes": 5,
    "HolderName": "CAT40-SF",
}


def make_techdb(path: Path) -> None:
    conn = sqlite3.connect(path)
    cols = ", ".join(
        f'{ti.quote_ident(c)} {"REAL" if isinstance(v, float) else "INTEGER" if isinstance(v, int) else "TEXT"}'
        for c, v in BALL_TEMPLATE.items()
    )
    conn.execute(f"CREATE TABLE in_MILLC ({cols})")
    for row in (BALL_TEMPLATE, HOG_TEMPLATE):
        names = ", ".join(ti.quote_ident(c) for c in row)
        conn.execute(
            f"INSERT INTO in_MILLC ({names}) VALUES ({', '.join('?' * len(row))})",
            list(row.values()),
        )
    conn.execute('CREATE TABLE in_DRILLS ("ID" INTEGER, "ON" INTEGER, "Comment" TEXT, '
                 '"Description" TEXT, "Vendor" TEXT)')
    conn.execute('CREATE TABLE in_MILLCDesc ("ID" INTEGER, "Text" TEXT)')
    conn.execute('CREATE TABLE TechDBVerInfoTable ("Ver" TEXT)')
    conn.commit()
    conn.close()


def make_registry(path: Path, rows: list[tuple[str, str, str | None, str | None]]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE tools ("shop_label" TEXT, "class" TEXT, "vendor" TEXT, '
        '"part_no" TEXT, "techdb_id" INTEGER, "techdb_table" TEXT)'
    )
    conn.executemany(
        "INSERT INTO tools (shop_label, class, vendor, part_no) VALUES (?, ?, ?, ?)", rows
    )
    conn.commit()
    conn.close()


@pytest.fixture
def dbs(tmp_path: Path) -> tuple[Path, Path]:
    techdb = tmp_path / "copy.cwdb"
    registry = tmp_path / "registry.db"
    make_techdb(techdb)
    make_registry(registry, [("N300", "EM/ball", "Helical", "H45AL-C-3")])
    return techdb, registry


def techdb_rows(path: Path) -> list[dict[str, object]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute('SELECT * FROM in_MILLC ORDER BY "ID"')]
    conn.close()
    return rows


def registry_rows(path: Path) -> list[dict[str, object]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM tools")]
    conn.close()
    return rows


def test_default_is_dry_run(dbs, capsys):
    techdb, registry = dbs
    rc = ti.main(["--db", str(techdb), "--registry", str(registry)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert 'INSERT INTO "in_MILLC"' in out
    assert "'N300'" in out
    assert len(techdb_rows(techdb)) == 2  # nothing written
    assert registry_rows(registry)[0]["techdb_id"] is None  # no write-back


def test_dry_and_apply_mutually_exclusive(dbs):
    techdb, registry = dbs
    with pytest.raises(SystemExit):
        ti.main(["--db", str(techdb), "--registry", str(registry), "--dry", "--apply"])


def test_apply_clones_template_with_overrides(dbs):
    techdb, registry = dbs
    rc = ti.main(["--db", str(techdb), "--registry", str(registry), "--apply"])
    assert rc == 0
    rows = techdb_rows(techdb)
    assert len(rows) == 3
    new = rows[-1]
    assert new["ID"] == 132  # MAX(11, 131) + 1
    assert new["Comment"] == "N300"
    assert new["Description"] == "N300"
    assert new["Vendor"] == "Helical H45AL-C-3"
    # everything else cloned from the ball template (ID 11)
    for col in ("ON", "ToolDia", "NoFlutes", "HolderName"):
        assert new[col] == BALL_TEMPLATE[col]
    reg = registry_rows(registry)[0]
    assert reg["techdb_id"] == 132
    assert reg["techdb_table"] == "in_MILLC"


def test_new_id_is_max_plus_one_with_gaps(dbs):
    techdb, registry = dbs
    conn = sqlite3.connect(techdb)
    conn.execute('INSERT INTO in_MILLC ("ID", "ON", "Comment") VALUES (500, 0, "gap")')
    conn.commit()
    conn.close()
    ti.main(["--db", str(techdb), "--registry", str(registry), "--apply"])
    assert techdb_rows(techdb)[-1]["ID"] == 501


def test_multiple_rows_get_sequential_ids(tmp_path):
    techdb = tmp_path / "copy.cwdb"
    registry = tmp_path / "registry.db"
    make_techdb(techdb)
    make_registry(
        registry,
        [("N300", "EM/ball", "Helical", "H1"), ("N301", "EM/hog", "Kenna", "K2")],
    )
    rc = ti.main(["--db", str(techdb), "--registry", str(registry), "--apply"])
    assert rc == 0
    ids = {r["shop_label"]: r["techdb_id"] for r in registry_rows(registry)}
    assert ids == {"N300": 132, "N301": 133}
    comments = {r["Comment"]: r for r in techdb_rows(techdb)}
    assert comments["N301"]["ToolDia"] == HOG_TEMPLATE["ToolDia"]  # hog template cloned


def test_label_filter(tmp_path, capsys):
    techdb = tmp_path / "copy.cwdb"
    registry = tmp_path / "registry.db"
    make_techdb(techdb)
    make_registry(
        registry,
        [("N300", "EM/ball", "Helical", "H1"), ("N301", "EM/hog", "Kenna", "K2")],
    )
    rc = ti.main(["--db", str(techdb), "--registry", str(registry), "--label", "N300"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "N300" in out and "N301" not in out


def test_protected_tables_refused():
    for table in ("in_MILLCDesc", "nTapsDesc", "TechDBVerInfoTable", "techdbverinfotable"):
        with pytest.raises(ti.SchemaError):
            ti.assert_writable_table(table)
    ti.assert_writable_table("in_MILLC")  # sanity: real target passes


def test_template_pointing_at_protected_table_is_skipped(dbs, capsys):
    techdb, registry = dbs
    rc = ti.run(
        str(techdb), str(registry), apply=True,
        templates={"EM/ball": ("in_MILLCDesc", 1)},
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "SKIPPED N300" in out
    assert len(techdb_rows(techdb)) == 2  # nothing written


def test_tap_raises_not_implemented(dbs, capsys):
    techdb, registry = dbs
    make_registry_conn = sqlite3.connect(registry)
    make_registry_conn.execute("UPDATE tools SET class = 'TAP'")
    make_registry_conn.commit()
    make_registry_conn.close()
    with pytest.raises(NotImplementedError):
        ti.resolve_template("TAP", ti.TEMPLATES)
    rc = ti.main(["--db", str(techdb), "--registry", str(registry), "--apply"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "NotImplementedError" in out
    assert registry_rows(registry)[0]["techdb_id"] is None


def test_unconfirmed_template_fails_closed(dbs, capsys):
    techdb, registry = dbs
    rc = ti.run(
        str(techdb), str(registry), apply=True,
        templates={"EM/ball": ("in_MILLC", None)},  # deliberately unconfirmed
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "not confirmed" in out
    assert registry_rows(registry)[0]["techdb_id"] is None


def test_unknown_class_skipped_without_write(dbs, capsys):
    techdb, registry = dbs
    conn = sqlite3.connect(registry)
    conn.execute("UPDATE tools SET class = 'LOLLIPOP'")
    conn.commit()
    conn.close()
    rc = ti.main(["--db", str(techdb), "--registry", str(registry), "--apply"])
    assert rc == 1
    assert "no template configured" in capsys.readouterr().out
    assert len(techdb_rows(techdb)) == 2


def test_missing_override_column_fails_closed(tmp_path, capsys):
    techdb = tmp_path / "copy.cwdb"
    registry = tmp_path / "registry.db"
    conn = sqlite3.connect(techdb)
    conn.execute('CREATE TABLE in_MILLC ("ID" INTEGER, "Vendor" TEXT)')  # no Comment/Description
    conn.execute("INSERT INTO in_MILLC VALUES (11, 'x')")
    conn.commit()
    conn.close()
    make_registry(registry, [("N300", "EM/ball", "V", "P")])
    rc = ti.main(["--db", str(techdb), "--registry", str(registry), "--apply"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "lacks override column" in out
    conn = sqlite3.connect(techdb)
    assert conn.execute("SELECT COUNT(*) FROM in_MILLC").fetchone()[0] == 1
    conn.close()


def test_columns_come_from_pragma_not_hardcoded(dbs):
    techdb, registry = dbs
    conn = sqlite3.connect(techdb)
    conn.execute('ALTER TABLE in_MILLC ADD COLUMN "WeirdNewCol" TEXT')
    conn.execute('UPDATE in_MILLC SET "WeirdNewCol" = \'carried\' WHERE "ID" = 11')
    conn.commit()
    conn.close()
    ti.main(["--db", str(techdb), "--registry", str(registry), "--apply"])
    assert techdb_rows(techdb)[-1]["WeirdNewCol"] == "carried"


def test_registry_autodetect_rejects_ambiguity(tmp_path):
    registry = tmp_path / "registry.db"
    conn = sqlite3.connect(registry)
    conn.execute("CREATE TABLE a (techdb_id INTEGER, techdb_table TEXT)")
    conn.execute("CREATE TABLE b (techdb_id INTEGER, techdb_table TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(ti.ConfigError, match="exactly one registry table"):
        ti.find_registry_table(sqlite3.connect(registry))


def test_missing_db_file_is_clear_error(dbs, capsys):
    _, registry = dbs
    rc = ti.main(["--db", "/nonexistent/nope.cwdb", "--registry", str(registry)])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_set_overrides_win_and_are_verified(dbs):
    techdb, registry = dbs
    rc = ti.main(
        ["--db", str(techdb), "--registry", str(registry), "--apply", "--label", "N300",
         "--set", "ToolDia=1.0", "--set", "NoFlutes=2", "--set", "HolderName=CAT40-EM100"]
    )
    assert rc == 0
    new = techdb_rows(techdb)[-1]
    assert new["ToolDia"] == 1.0
    assert new["NoFlutes"] == 2
    assert new["HolderName"] == "CAT40-EM100"
    assert new["Comment"] == "N300"  # computed defaults still applied


def test_set_requires_label(dbs, capsys):
    techdb, registry = dbs
    rc = ti.main(["--db", str(techdb), "--registry", str(registry), "--set", "ToolDia=1.0"])
    assert rc == 2
    assert "requires --label" in capsys.readouterr().err
    assert len(techdb_rows(techdb)) == 2


def test_set_rejects_id_and_bad_syntax():
    with pytest.raises(ti.ConfigError, match="may not target ID"):
        ti.parse_set_args(["ID=999"])
    with pytest.raises(ti.ConfigError, match="COL=VALUE"):
        ti.parse_set_args(["ToolDia"])
    assert ti.parse_set_args(["A=2", "B=0.5", "C=x=y"]) == {"A": 2, "B": 0.5, "C": "x=y"}


def test_set_unknown_column_fails_closed(dbs, capsys):
    techdb, registry = dbs
    rc = ti.main(
        ["--db", str(techdb), "--registry", str(registry), "--apply", "--label", "N300",
         "--set", "NoSuchCol=1"]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "lacks override column" in out
    assert len(techdb_rows(techdb)) == 2


def test_render_sql_literals():
    sql = "INSERT INTO t (a, b, c, d) VALUES (?, ?, ?, ?)"
    rendered = ti.render_sql(sql, [1, "O'Ring", None, 0.5])
    assert rendered == "INSERT INTO t (a, b, c, d) VALUES (1, 'O''Ring', NULL, 0.5)"
