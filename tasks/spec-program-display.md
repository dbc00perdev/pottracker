# Spec — Running-Program Display (lathe v1)

**Status**: APPROVED (dbc00per 2026-08-06, "spec it and build it — READ ONLY").
**Goal**: the web UI shows *which program is running* on each lathe —
O-number + human part name — live at the poll cadence.

---

## 1. What we read (all documented FOCAS reads, header-verified)

Verified live on JAKE_2100LYS 2026-08-05 (`reports/lathe57-active-program-20260805.json`):

| Call | Gives | Use |
|---|---|---|
| `cnc_exeprgname` (hdr:11851, ODBEXEPRG hdr:836) | running program name (`"O9034"`) + `o_num` (9034) | **program_number** |
| `cnc_rdexecprog` (hdr:11878) | executing block text (512 B) | **program_name** — best-effort comment parse: when the text starts `O<num>(comment)` take the comment (`"3878OR Blank"`). None otherwise — never guessed. |

Two calls, milliseconds each, read-only. NOT in v1: `cnc_rdseqnum` (N churns
every block — display value low vs mirror churn), `cnc_rdprgnum` (redundant
with `o_num`), program-directory comment reads (unverified struct decode).

## 2. Data path (mirrors the active_wcs/0010 precedent exactly)

- **`shared/focas/client_reads.py`**: `ODBEXEPRG` struct (local, lathe idiom) +
  `read_program_info(client) -> tuple[int | None, str | None]` — each call
  resilient (None on rc != 0), comment regex `^O(\d+)\((.{1,64}?)\)`.
- **loader.py**: bind `cnc_exeprgname` / `cnc_rdexecprog` (c_void_p pattern
  like cnc_rdparam).
- **models.MachineStatus**: `program_number: int | None`, `program_name:
  str | None` (additive, default None — mills stay None by construction).
- **lathe.read_status_lathe**: populate both (fast tier L3 inherits it free).
- **Mills**: NOT in v1 — `client.py` sits at the 400-LOC cap; mill program
  display lands when that file is next split (follow-up noted in todo).
- **Migration 0013**: `shared.focas_machine_status` + `program_number` INT
  NULL, `program_name` TEXT NULL. `shared/db.py` table def updated.
- **snapshot_diff.diff_status / StatusState**: carry program_number through
  the change tuple (name is display data derived from the same program —
  number alone drives `changed`); param carries both. NOT audited (same R17
  rationale as HEAD/NEXT — program changes every job).
- **snapshot._load_status/_upsert_status**: select/set both columns;
  `program_number` joins the IS DISTINCT FROM change predicate.
- **API**: `SpindleOut` + `services.machines.spindle()` add both fields.
- **UI**: `types/api.ts` Spindle + program badge in the lathe view status
  strip: `O9034 · 3878OR Blank` (number-only when name is None).

## 3. Safety classification

Reads only: `cnc_exeprgname`, `cnc_rdexecprog` — both `cnc_rd*/exe*` query
functions, no register writes, no state change on the control. Same class as
every existing poll call. No write function exists in the codebase.

## 4. Verification

1. Unit: comment-parse cases (match, no-comment, garbage, oversized),
   diff_status change detection on program_number, MachineStatus defaults.
2. `alembic upgrade head` on dev; migration round-trips (downgrade drops).
3. ruff + mypy + pytest (full CI surface).
4. Live read-only check vs 10.1.10.57: read_status_lathe returns (9034,
   "3878OR Blank")-class data.
5. Restart the four lathe pollers (VT + 3 Panthers); confirm mirror rows
   carry program fields, `GET /machines/{id}/spindle` returns them, UI badge
   renders.

## 5. Follow-ups (explicitly out)

Mill program display (client.py split), sequence-N/progress display,
cycle-time analytics tie-in, program-text viewer.
