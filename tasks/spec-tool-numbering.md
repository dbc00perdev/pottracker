# spec-tool-numbering.md — tool identity, numbering, and CSV intake

> Status: approved 2026-07-09; **materially revised 2026-07-12** (dbc00per floor
> ground truth). Implements the locked tool-numbering strategy for the ~100+
> physical library, tied into the app and (downstream) the CAMWorks Technology
> Database.
>
> **2026-07-12 revision — read this first.** The original §6 assumed a *permanent
> T1–T20 core band* with `H = D = T`. That is **retired**: nothing lives in the
> machine (24 pots ≪ 100+ library), so **every T rotates in/out per job**.
> Permanence moves from the *station* (T) to the *offset number* **N** (H/D
> register), which is **static per tool and shared across the mill class**. The
> app's current `assignment.h_register`/importer `H=D=T` default still encode the
> old model — realigning them (N at tool level + `mpn` field) is a flagged
> follow-on (§11), not built in this revision.

## 1. Purpose

Define one durable tool identity that flows CAM → shop floor → machine, and the
intake pipeline that gets the physical crib into the database. The library is not
digitized yet; this spec + the importer + the intake template (`docs/templates/
tool-intake.csv`) let documenting it be pure data entry that imports in one
command.

## 2. Four number-spaces (never conflated)

| Space | Meaning | Home | Static? | Scope | Reused? |
|---|---|---|---|---|---|
| **GTID** | permanent shop-wide tool identity; CAM tech-DB key | `tooling.tool.short_id` | permanent | shop-wide | never (retire = soft-delete) |
| **N** = offset # (H/D row) | machine "tool number" — `G43 H(N)` / `G41 D(N)` | tool-level *(target; today `assignment.h_register`)* | **static per tool** | **mill-class, fleet-wide** | permanent: reuse-in-place on rebuild; burner band (top 10): recycled |
| **T** = tool-change call | program-facing station the NC calls to load it; posted per job by CAM | `tooling.assignment.t_number` | **dynamic per job** | per-machine | yes — frees on removal |
| **Pot** | observed magazine location (random ATC, drifts) | `shared.focas_pot` | observed | per-machine | poller-read, never commanded |

The prior revision folded the offset register into T (`H = D = T`). Floor reality
splits them: **T rotates every job** (which pot the ATC loads), while **N (the H/D
offset) is static per tool** and — because there are ~400 registers vs 24 pots —
is where permanence lives. GTID and N are **linked but distinct** (GTID unlimited;
N bounded ~400). Pot is observed state (R10), correlated to identity only via the
assignment (occupancy model, `services/occupancy.py`).

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
`edp_number` = the maker's EDP catalog / reorder number. Together they're a valuable
secondary cross-reference key (pin a tool to its published geometry; reorder;
cross-ref to CAMWorks / tool DBs). They are **distinct** from `vendor` /
`vendor_part_number`, which describe the *distributor* you buy from (who makes it
≠ who you buy it from). All four are optional attributes; identity stays the GTID.

**Bin-label key = `manufacturer` + `edp_number` (existing fields — no new column).**
The Lance Tracker Parts Bin lookup / reorder is keyed by manufacturer + EDP number.
**Decided: the Code 128 encodes the `edp_number` only; `manufacturer` prints as
human-readable text** on the label — the scanner wedges the EDP reorder key, the eye
reads the maker. **No dedicated `mpn` field is needed** — both columns already exist.

## 6. T is fully dynamic; N (offset #) carries the permanence

**No tool lives in the machine.** 24 pots ≪ a 100+ (growing) library, so **every T
rotates in and out with the job** — CAM posts the `T` (tool-change) and `H` (offset)
calls; the operator loads whatever pot the job assigns; the poller reads the pot.
There is **no permanent core band**. T is per-machine, per-job, freely reused.

Permanence lives on **N — the offset register number** (`G43 H(N)` length /
`G41 D(N)` diameter). One 0i-MF offset row carries both H-geom and D-geom, so a
single **N gives H and D** (`H = D = N`), now **decoupled from T**. Properties:

- **Static per tool** — a tool keeps its N for life; CAM's tech DB carries one
  fixed `H(N)` per tool and auto-pulls the assembly when programming.
- **Shared across the mill class (fleet-wide)** — the *same* tool gets the *same* N
  on every mill, so one printed N and one CAM H work fleet-wide. The **H_GEOM value
  at N is the shared preset length**; small machine-to-machine differences live in
  **H_WEAR at the same N** (the existing presetter GEOM/WEAR split, `snapshot`
  attribution, already supports this). **Lathes are excluded** — different offset
  model (docs/11), their own scheme later.
- **Bounded ~400 registers** (minus the reserved probe **H50**, Decision-4/R12).
- **Pot tracker owns the N pool** — the authority that assigns and reclaims N.

### N lifecycle + pool allocation

- **Recommission (the majority case)** — same cutter back in, re-measured: **same
  GTID, same N**, log the new length (`regrind_count++` / recommission event).
  Length is a **versioned attribute of the GTID**, never a new identity or a new N.
- **Rebuild into a genuinely different tool** (different cutter/geometry) — old GTID
  retires (**soft-delete; history/audit always preserved**), a new GTID is minted, and
  the **new keeper reuses the vacated N in place** — the slot's number is stable, the
  occupant changes. A brand-new keeper that replaces nothing **appends** the next
  permanent N.
- **One-off** — flagged at intake (an explicit **one-off checkbox**, distinct from
  `is_consumable_class`); draws an N from the **burner band** (below). When the job is
  done the GTID is soft-deleted and its burner N returns to the band.

**Two-band N pool** (decided 2026-07-13, dbc00per floor ground truth):

| Band | Range | For | Reuse |
|---|---|---|---|
| **Permanent** | bulk of the range | recurring tools ("used over and over") | reuse-in-place on rebuild; append only for a brand-new keeper |
| **Burner** | **top 10** of the usable range | one-offs / transient / any "need a new N but it won't stay static" | freely recycled — drawn and returned |

The permanent band carries essentially all N's; the 10-slot burner band is the escape
hatch so an edge-case allocation never pollutes the static pool. It sits at the **top of
the range, clear of the reserved probe H50** (Decision-4/R12); the exact ceiling = the
control's offset-table size minus the probe reservation, pinned at build time. Because
active tools (~100–250) sit far under the pool size, **every permanent tool holds a
static N with no mid-life churn** — a printed N stays valid for the tool's whole life.

**Reuse-in-place safety net.** A reused permanent N changes occupant, so every
reassignment logs an **N-reassignment audit event** (old GTID → new GTID at N, when, who)
and the new tool's assembly tag always prints the current GTID + N — the physical label is
never stale and a wrong-offset surprise is always traceable. (dbc00per retires the matching
CAM program operationally; a proactive "N reassigned — check callers" warning is a cheap
later add.)

### Teardown / re-entry entry point

The operator needs a defined place in the app — reached by **scanning the assembly-tag
GTID** — to handle a physical teardown, with two operator-chosen outcomes:

1. **Reset / recommission** — same cutter: keep GTID + N, log the new length.
2. **Retire + create new** — rebuilt into a different tool: old GTID soft-deleted (its
   history stays in the DB), a **blank entry form** appears, the operator keys the new
   tool's attributes "as they see fit", and it takes the **reused permanent N** (default,
   keeper-in-slot) or a **burner N** (if flagged one-off). The screen clears; the audit
   trail behind it does not (never a hard delete).

**NB — current code still encodes the old model.** `tooling.assignment` holds
`h_register`/`d_register` per machine and the importer defaults `H = D = T`. Moving N to
tool-level (fleet-wide) with the **two-band allocator + one-off flag + teardown/re-entry
UI + N-reassignment audit** is the flagged follow-on (§11); this section is the target
model, not yet the schema.

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
*from* it (same GTID + generated description). The link that makes CAM auto-pull
work is the **fixed `H(N)` per tool**: each assembly in the tech DB carries its
static, fleet-wide **N** as its offset (`G43 H(N)` / `G41 D(N)`), so any program
using that tool posts the same H on any mill. **T is *not* fixed** — it is assigned
per job/program (which pot to load); loading records the assignment and the poller
lights the pot. So the sync is **GTID + N + description** (static), while T flows
the other way (per-job, machine-side). (Sync *implementation* is future work.)

## 10. Labeling — two-label taxonomy (Code 128 house standard)

Two label classes serve two workflows / two lifecycle stages. **Code 128 is the
house standard on both** (one gun-scanner fleet, one keyboard-wedge behavior).

| Label | Lives on | Keyed by | Symbology | Feeds |
|---|---|---|---|---|
| **Bin label** | storage bin / raw cutter + insert stock | **manufacturer + EDP #** | **Code 128 of EDP # + mfr text** | gun scanner → **Tracker Parts Bin** lookup / reorder sheet (clean wedged text) |
| **Assembly tag** | the CAT40 holder (built tool) | **GTID** (+ N, description) | **Code 128 of GTID** + optional QR-URL | pot tracker scan-to-load / recommission; QR = phone lookup |

Proposed assembly-tag layout — every field is already on the tool record
(`short_id`, generated `description` via `tool_label.py`, plus N):

```
┌────────────────────────────┐
│  100042       [Code 128]   │   GTID (big) — identity / setup-sheet match
│  H/D 205                   │   N — static offset call, fleet-wide
│  1/2" 4FL SQ CARBIDE       │   generated description
│  TiAlN         [ QR-URL ]  │   optional QR → pot-tracker tool page (phone)
└────────────────────────────┘
```

Design rules:
- **Bin label — Code 128 of `edp_number` only; `manufacturer` as human-readable text**
  (the scanner wedges the EDP reorder key; §5). QR-URL is a phone-lookup *extra* on the
  assembly tag, never the bin key.
- **No DB coupling** (Decision-10 two-DB wall): a barcode is printed text of a value
  we already store; the operator scans it into whatever system has focus. The
  **Tracker Parts Bin stays the authoritative inventory/reorder system** — the pot
  tracker is only a *label emitter*, never a second bin-inventory DB.
- The QR (when present) carries **GTID** (stable identity), not N (poolable).

## 11. Out of scope / follow-on build (each its own plan-noded PR)

- **Schema realignment** — move N from per-machine `assignment.h_register` to a
  **tool-level, mill-class, fleet-wide** field + a **two-band N-pool allocator**
  (permanent band, reuse-in-place on rebuild; a **top-10 burner band**, recyclable, clear
  of probe H50) + a **one-off flag** (distinct from `is_consumable_class`) + an
  **N-reassignment audit event**. Migration + reconcile test + importer update (`H=D=T`
  default → the N model). Touches tool identity/offset model → confirm-gated. *(No `mpn`
  column — bin labels use existing `manufacturer` + `edp_number`.)*
- **Teardown / re-entry entry point (UI)** — operator screen (scan GTID → reset-same-GTID,
  or retire+create-new with a reused permanent N or a burner N), soft-delete preserving
  history, blank re-entry form (§6).
- **Label generators** — emit printable **assembly tags** (Code 128 GTID · N ·
  description · optional QR-URL) and **bin labels** (Code 128 of manufacturer + EDP #)
  from the tool table. Both fields already exist; assembly tags gate on N. (Borrow the
  tracker's QuickScan scan pattern.)
- **Assignment seed-run with real tools** — needs the digitized library + a
  committed machine row.
- **CAMWorks TechDB sync implementation** (GTID + N + description, §9).
