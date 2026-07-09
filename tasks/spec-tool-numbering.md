# spec-tool-numbering.md — tool identity, numbering, and CSV intake

> Status: approved 2026-07-09. Implements the locked tool-numbering strategy for
> the ~100+ physical library + resident tools, tied into the app and (downstream)
> the CAMWorks Technology Database.

## 1. Purpose

Define one durable tool identity that flows CAM → shop floor → machine, and the
intake pipeline that gets the physical crib into the database. The library is not
digitized yet; this spec + the importer + the intake template (`docs/templates/
tool-intake.csv`) let documenting it be pure data entry that imports in one
command.

## 2. Three number-spaces (never conflated)

The app already models these as `tool` ↔ `assignment` ↔ `focas_pot`:

| Space | Meaning | Home | Reused? |
|---|---|---|---|
| **GTID** | permanent shop-wide tool identity | `tooling.tool.short_id` | never (retire = soft-delete) |
| **T-number** | per-machine, program-facing station the NC calls | `tooling.assignment.t_number` | yes — frees on removal |
| **Pot** | observed magazine location (random ATC, drifts) | `shared.focas_pot` | poller-read, never commanded |

GTID (100s–1000s) and T-number (fits a ~24-pot table) are **linked but distinct**
numbers; they cannot collapse into one. Pot is observed state (R10), correlated
to identity only via the assignment (occupancy model, `services/occupancy.py`).

## 3. GTID = a non-significant running serial (`short_id`)

GTID is stored in the existing unique `tooling.tool.short_id` column as a plain
**non-significant serial** (e.g. `100042`). It carries **no** encoded meaning.

**Why non-significant** (settled PLM/ERP/MDM best practice):
- Identity must **never become wrong**. A significant ("smart") number that
  encodes specs starts to *lie* the moment a tool is reground, re-coated,
  re-vendored, or when a spec dimension the scheme never anticipated appears —
  but identity must be immutable for traceability.
- Significant schemes are always *temporary* (fields exhaust, categories drift)
  and hand-keying long codes is error-prone.
- The database attributes + a generated description carry the human meaning far
  better than a code ever can. This mirrors **ISO 13399** (cutting-tool data
  representation): an opaque ID + a rich structured attribute dictionary.

Unit of identity = the **preset assembly** (cutter + holder + stickout + measured
length). Regrind / re-touchoff → **same GTID**, re-preset, `regrind_count++`.
Rebuild (new cutter/stickout) → **retire** old GTID, mint a **new** one. Holder is
an attribute, not a separately-tracked asset. Tracking granularity: **individual**
for preset/unique tools, **class** for cheap consumables (`is_consumable_class`).

## 4. Generated description (the associative half, derived)

The human-readable / associative nomenclature lives in a **computed** description,
not in the identity — so it can never go stale. Built by
`apps/tooling/api/services/tool_label.py:tool_description` from attributes and
exposed as `ToolOut.description`; the label reads `GTID · description`:

```
100042 · 1/2in 4FL SQ CARBIDE TiAlN
^GTID     ^generated from type + Ø + flutes + (corner R) + substrate + coating
```

Format: `<Ø> <flutes>FL <TYPE> [R<corner>] <SUBSTRATE> <COATING>`, null parts
omitted; imperial Ø preferred when `diameter_inch` is present, else metric mm;
type uses a short code per `tool_type.code` (SQ EM / BALL EM / CR EM / DRILL / …),
falling back to the type display name. One canonical string for the UI label, the
importer preview, and any future CAMWorks sync.

## 5. Manufacturer + EDP (attributes, not identity)

`tooling.tool.manufacturer` = the maker (Helical, Harvey, Kennametal…);
`edp_number` = the maker's EDP catalog/reorder number. Together they're a valuable
secondary cross-reference key (pin a tool to its published geometry; reorder;
cross-ref to CAMWorks / tool DBs). They are **distinct** from `vendor` /
`vendor_part_number`, which describe the *distributor* you buy from (who makes it
≠ who you buy it from). All four are optional attributes; identity stays the GTID.

## 6. T-numbering = hybrid (core + job band)

Per-machine, in `tooling.assignment`. Forced hybrid by physics (24 pots ≪ 100+
library → some T's must be reusable) and by CAMWorks cribs being resident-core +
per-job-adds. Viper starting split:

- **T1–T20 core** — permanent, fixed-role resident tools.
- **T21–T24 job band** — reused per job.
- **T50 / H50 = probe, reserved** (Decision-4). API + importer reject any
  assignment to the probe T or probe H (R12).

Convention **H = D = T** (stored per assignment, never hardcoded — a tool's H/D is
whatever it was assigned). The importer defaults H and D to the T-number when
blank. Tune the core/job split as we learn how many tools truly live resident.

## 7. CSV intake contract (`docs/templates/tool-intake.csv`)

One header row; one tool per data row. Columns:

**Required:** `gtid` (→ short_id), `tool_type` (a seeded `tool_type.code`),
`diameter_mm` (> 0).

**Catalog (optional):** `diameter_inch`, `flute_count`, `corner_radius_mm`,
`flute_length_mm`, `overall_length_mm`, `shank_diameter_mm`, `substrate`,
`coating`, `manufacturer`, `edp_number`, `vendor`, `vendor_part_number`,
`vendor_url`, `max_doc_mm`, `max_woc_mm`, `requires_tsc`, `requires_climb`,
`is_consumable_class`, `notes`.

**Resident assignment (optional):** `machine_name`, `t_number`, `h_register`,
`d_register`. Present ⇒ seed `tooling.assignment` (H/D default to T; probe T/H
rejected; machine resolved by name — a row whose machine doesn't exist yet is
**skipped with a note**, not an error). Blank ⇒ catalog-only.

Booleans accept `true/false/1/0/yes/no` (blank = false). Unknown columns are
ignored with a warning.

## 8. Importer behavior (`scripts/import_tools.py`)

- **Upsert on `short_id` (GTID)** — insert new, update catalog fields on conflict;
  **never overwrite `regrind_count` or `created_at`** (runtime-owned). Re-running
  is idempotent.
- `tool_type` resolved **by code** (run `scripts.seed_tool_types` first; unknown
  code lists the valid set).
- **Fails closed**: any per-row validation error aborts the whole import (nothing
  written) — a bad CSV can't half-load. All errors are reported at once.
- **Dry-run by default** (per-row action + generated-description preview);
  `--apply` writes in one transaction. DSN-guarded (dev only unless
  `LANCE_ALLOW_PROD`), `search_path = tooling, shared`.

## 9. CAMWorks TechDB sync boundary

Pot tracker is the **master tool DB**. The CAMWorks TechDB tool library is synced
*from* it (same GTID + generated description). Per-machine CAMWorks **tool cribs**
mirror the pot tracker's **permanent** (core-band) assignments — identical
T/station numbers — so program `T7` == app `T7` == the labeled tool. Job tools go
in the job band; the post outputs those T's; loading records the assignment and
the poller lights the pot. (Sync *implementation* is future work.)

## 10. Out of scope (future)

- Assignment **seed-run with real tools** — needs the digitized library + a
  committed machine row.
- Barcode / QR label + scan tie-in (borrow the tracker's QuickScan pattern).
- CAMWorks TechDB sync implementation.
