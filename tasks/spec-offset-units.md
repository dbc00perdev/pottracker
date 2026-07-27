# spec-offset-units.md — native-inch offset storage

**Status**: LOCKED (dbc00per, 2026-07-15). Contains decided items only.
Amends the CLAUDE.md rule "lengths in metric (mm) internally".

---

## 1. The machine is inch

**CONFIRMED by dbc00per, 2026-07-15.** The LG-1000AP, its panel, the CAM post and the
shop are inch. FANUC IS-B is `0.001 mm` in metric but **`0.0001 inch` in inch mode`** —
the Phase-1 measurement of `0.0001` was the inch increment, recorded with the wrong unit.

Every offset value in the codebase is currently labelled `mm` and is actually inches — a
**25.4× error** through the mirror, the audit log, the API and the UI. Nothing is damaged:
no write path is bound (`cnc_wrtofs` unbound) and the mirror is dev-only.

Supporting observations (read-only, 2026-07-15): GEOM H range 3.37–7.40 = normal CAT40
gauge length in inches; probe GEOM D `0.2360` = a 6 mm stylus in inches; `G20` on every
posted program; `.set` stick-outs in `IN`.

## 2. Decision — store native inch + explicit unit

Stored values are the control's own numbers, so **what the app shows equals what the panel
shows**. The unit is a property of the machine, read from the control, never assumed.

```
shared.machine
  + offset_unit        TEXT NOT NULL  CHECK (offset_unit IN ('inch','metric'))
  + offset_increment   NUMERIC NOT NULL          -- 0.0001 for this control

shared.focas_offset_register
    value_mm -> value  NUMERIC                   -- native value, verbatim from the control
```

Unit lives on the machine row (all registers share it). `audit_log` **denormalizes**
`{"value": …, "unit": "inch"}` into before/after so immutable history stays self-describing.

`offset_math.py`:

```
OFFSET_INCREMENT_INCH = Decimal("0.0001")        # IS-B inch
counts_from_value(value, unit) / value_from_counts(counts, unit)
```

Conversion functions take `unit` explicitly — no caller can do unit-blind math. The naming
failure is what hid this bug, so the signature forces the question.

## 3. Blast radius

| Layer | Symbol | Fix |
|---|---|---|
| `shared/focas/offset_math.py` | `OFFSET_INCREMENT_MM` | → `OFFSET_INCREMENT_INCH` |
| | `LARGE_DIFF_THRESHOLD_MM = 0.5` | value is an open item — see question list |
| | `OFFSET_ABS_MAX_MM` | rebound in inches |
| | `counts_from_mm` / `mm_from_counts` | → unit-explicit |
| `shared/focas/client.py` | `DEFAULT_OFFSET_INCREMENT` | unit-aware; read from control |
| `shared/focas/models.py` | `OffsetValueMM`, `value_mm` | → `value` + unit |
| `shared/db.py`, migrations 0002/0003 | `focas_offset_register.value_mm` | → `value` |
| `snapshot.py` / `snapshot_diff.py` | audit `{"value_mm"}` | → `{"value","unit"}` |
| `apps/tooling/api/services/occupancy.py` | `offset_mm` | → `value` + unit |
| `apps/tooling/api/services/offset_write.py` | via offset_math | inherits |
| `shared/focas/mock.py` | mock writer units | inherits |
| frontend `format.ts`, `OffsetTable.tsx`, `types/api.ts` | displays "mm" | display `in` |

## 4. Phasing — each independently verifiable, safest first

| # | Slice | Touches | Risk |
|---|---|---|---|
| **1** | `offset_math.py` + tests: units, unit-explicit conversion | 1 pure module | none — no I/O |
| **2** | Bind `cnc_rdparam`; read increment + unit; fail-closed on mismatch | `client.py`, `models.py` | read-only FOCAS |
| **3** | Migration: `machine.offset_unit`/`offset_increment`, rename `value_mm`→`value`; persist + audit JSON | migration, `db.py`, `snapshot*.py` | dev DB only |
| **4** | API + UI: `occupancy`, schemas, `format.ts`, `OffsetTable.tsx` — display `in` | api + web | display only |
| **5** | Docs: `docs/02`, `docs/03`, `spec-focas-calls`, `spec-phase5-write-path` | docs | none |

## 5. Verification

- Phase 1: unit tests including a regression test pinning `0.0001 inch`.
- Phase 2: live read-only against the Viper; assert the reported unit is inch; prove the
  poller refuses on a forced mismatch.
- Phase 3: `alembic upgrade`/`downgrade` round-trip on dev; reconcile test. **No backfill
  conversion** — mirror rows re-derive on the next poll; the stored values were never right.
- Phase 4: frontend typecheck + vitest + one value cross-checked against the panel.
- Full suite (471) + ruff + mypy green at every phase.
