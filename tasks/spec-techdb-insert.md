# spec-techdb-insert — Phase-3 TechDB clone-row inserter

Status: **built, dry-run verified vs a synthetic TechDB copy. NOT run against a real
TechDB — no real write performed anywhere.**

## Purpose

`src/techdb_insert.py` — take rows from the local tool registry (`registry.db`)
that have no TechDB identity yet (`techdb_id IS NULL`), clone a known-good
template row per tool class inside a **TechDB copy** (plain-SQLite `.cwdb`
passed via `--db`), override the identifying fields, and write the new TechDB
identity back into the registry.

## Contract (from dbc00per's task, 2026-07-21)

- Input: registry rows `WHERE techdb_id IS NULL`.
- Target: TechDB **copy** at `--db` (never the live TechDB).
- Clone-row INSERT: template row per class (configurable dict), override parsed
  fields, `ID = MAX(ID)+1`, columns enumerated via `PRAGMA table_info` at
  runtime — **never positional**.
- `shop_label` → `Comment` AND `Description`; `vendor` + `part_no` → `Vendor`.
- After commit: write `techdb_id` + `techdb_table` back into the registry row.
- `--dry` prints INSERTs without executing; **dry-run is the default** (writes
  need explicit `--apply`; in dry mode both DBs are opened read-only).
- Never touch `*Desc` tables, `TechDBVerInfoTable`, or schema (no DDL, ever).

## Template rows (known-good rows in dbc00per's TechDB)

| class     | table       | template ID | note                                          |
|-----------|-------------|-------------|-----------------------------------------------|
| `EM/ball` | `in_MILLC`  | 11          | N62 ball mill, complete feeds/speeds/holder   |
| `EM/hog`  | `in_MILLC`  | 131         | N46                                           |
| `DRILL`   | `in_DRILLS` | **UNSET**   | fails closed until dbc00per confirms an ID (row with `ON=1` + Vendor set) |
| `TAP`     | `nTaps`     | —           | table not yet mapped → `NotImplementedError`  |

## Assumptions (forced — the referenced `docs/ARCHITECTURE.md` does not exist in this repo)

The task cites "ARCHITECTURE.md phase 3", but this repo contains no
`ARCHITECTURE.md`, no `src/`, no `registry.db`, no TechDB copy, and no prior
mention of any of them. Built from the task text alone; every gap below is an
assumption to confirm:

- **A1 — registry schema**: registry table is auto-detected (the single user
  table containing both `techdb_id` and `techdb_table` columns) and must also
  carry `shop_label`, `class`, `vendor`, `part_no`. `class` values are the
  literal strings above (`EM/ball`, `EM/hog`, `DRILL`, `TAP`). Rows are
  addressed by SQLite `rowid` for write-back.
- **A2 — TechDB ID column** is literally named `ID` (verified present via
  PRAGMA; fails closed if absent).
- **A3 — Vendor format**: `"{vendor} {part_no}"`, single-space joined, empty
  parts dropped. Written even when blank (a new tool must not inherit the
  template's vendor).
- **A4 — location**: `src/techdb_insert.py` per the task (this repo otherwise
  uses `scripts/`); stdlib-only, standalone.
- **A5 — parsed-field overrides** are exactly the three named in the task
  (Comment, Description, Vendor). Geometry/feeds stay cloned from the template
  until the field map is specified.

## Open decisions for dbc00per

- **D1** — DRILL template ID in `in_DRILLS` (`ON=1`, Vendor set). Tool fails
  closed until it's set in `TEMPLATES`.
- **D2** — `nTaps` mapping for TAP (stubbed `NotImplementedError`).
- **D3** — where is the real `ARCHITECTURE.md` / `registry.db`? Neither is in
  this repo; the acceptance dry-run for N300 ran against a **synthetic**
  TechDB copy + registry built to this spec's assumptions.
- **D4** — confirm A1–A5.

## Safety model

- Default dry-run; `--apply` required for any write; `--dry`/`--apply`
  mutually exclusive.
- Dry mode opens **both** DBs `mode=ro` (SQLite URI) — cannot write, cannot
  create files.
- Protected-name guard on every table access: `*Desc` (case-insensitive
  suffix) and `TechDBVerInfoTable` are refused.
- All identifiers quoted; all values bound by name-ordered parameters; column
  order comes from `PRAGMA table_info` at execution time.
- Apply mode: single `BEGIN IMMEDIATE` transaction on the TechDB,
  read-after-write verification of every inserted row (Comment / Description /
  Vendor read back and compared) before commit; registry write-back happens
  only after the TechDB commit, in its own transaction, `rowcount`-checked.
- Per-row failures (unknown class, unconfirmed DRILL, TAP, schema mismatch)
  skip that row with a reason and force a non-zero exit; they never abort
  other rows and never partially write.

## Verification

- `tests/test_techdb_insert.py` — unit suite over synthetic SQLite fixtures
  (dry-run default, read-only enforcement, MAX(ID)+1 with gaps, PRAGMA-driven
  cloning, override targeting, protected-table refusal, TAP/DRILL fail-closed,
  write-back, sequential multi-row IDs).
- Dry-run demo vs a synthetic TechDB copy + registry containing N300 — output
  in the session log. **Stopped before any real write, per the task.**
