# Spec — N schema realignment: fleet-wide N as a tool-level field (DRAFT for review)

Status: **DRAFT — needs dbc00per sign-off before any code** (touches tool
identity/offset model; spec-tool-numbering §11 names this confirm-gated).
Drafted 2026-07-30. Priority raised 2026-07-29 by the LG "no crib record"
incident.

## 1. Problem

The N model (spec-tool-numbering §6) says N is **static per tool and
fleet-wide across the mill class** — but the schema stores it only inside
per-machine `tooling.assignment.h_register` rows. Consequences, all observed
live 2026-07-29:

- The LG resolved **nothing** ("no crib record" on every pot) because every
  crib assignment pointed at the AG. Fleet-wide N existed only on paper.
- Interim fix was **SQL-mirroring all 57 AG assignments onto the LG** — it
  works (125 active assignments), but every future crib add needs the same
  manual mirroring, and a third mill triples it.
- The importer's `machine_name` column forces a single machine per CSV row,
  which is the wrong shape for a fleet-wide identity.

## 2. Target schema (migration 0012)

- **`tooling.tool.n_number`** — `Integer, nullable`. The tool's fleet-wide
  mill-class offset number (`G43 H(N)` / `G41 D(N)`, H=D=N). NULL = not in
  the mill N-pool (lathe tools, catalog-only, retired-and-freed).
- **Partial unique index**: `UNIQUE (n_number) WHERE retired_at IS NULL AND
  n_number IS NOT NULL` — one live owner per N; retirement frees the N for
  reuse-in-place without losing history (soft-delete keeps the old row).
- **`tooling.tool.is_one_off`** — `Boolean, NOT NULL DEFAULT false`. The
  burner-band designation from §6 (dbc00per's explicit checkbox; distinct
  from `is_consumable_class`).
- **Probe guard**: CHECK `n_number IS NULL OR n_number <> 50` — the probe's
  H50 is reserved fleet-wide (R12); no tool may ever hold N50.
- **Backfill** (in-migration, dev DB): `tool.n_number := h_register` from the
  tool's **active mill assignments**, but ONLY where every active assignment
  for that tool agrees on one h_register (today they all do — T=N=H by
  construction, AG+LG mirrored). Any disagreement aborts the migration with
  the conflicting GTIDs listed — flag, don't guess.

## 3. Allocator (pure service, no FOCAS)

`apps/tooling/api/services/n_pool.py`:

- **Permanent band** — append-allocate: `max(n_number in permanent band) + 1`.
  Reuse-in-place is a deliberate admin action (assign a freed N to a new
  keeper), never automatic.
- **Burner band** — the **top 10 of the usable register range** (D1 below),
  freely recycled: allocate the lowest free burner N; freed on retirement.
- **Every N assignment/reassignment/free writes an `n_reassignment` audit
  event** (old owner GTID, new owner GTID, N, reason) — §6's safety net.

## 4. Resolution changes (occupancy + API)

- `occupancy.py`: pot identity T resolves **per-machine assignment first**
  (unchanged — it carries pending_review/confirm and per-machine cached
  values), then **falls back to the fleet N**: a mill pot showing T with no
  assignment but a live tool with `n_number == T` resolves that tool, with
  presence still read from the machine's own offset register N. The LG would
  have worked on day one under this rule with zero mirrored rows.
- `ToolOut`/`Tool` gain `n_number` + `is_one_off`; tools list/search filters
  by N. `assignments` API unchanged (T stays per-machine and dynamic).

## 5. Importer (`scripts/import_tools.py`)

- New column `n_number` (replaces the implicit "t_number = N" convention);
  `machine_name` becomes optional.
- A row with an `n_number` **registers the tool once** and creates
  assignments (`t_number = h_register = d_register = N`) on **every enabled
  mill-class machine** — future crib adds land fleet-wide with no SQL.
  Probe N50 rejected (R12); lathe machines never receive mill-N assignments
  (R20 class wall).
- Idempotent re-import unchanged (upsert on GTID, never touches
  `regrind_count`/`created_at`).

## 6. Not in this slice

Teardown/re-entry UI, label generators, CAMWorks sync (spec-tool-numbering
§11 — each its own plan-noded PR). No FOCAS surface touched anywhere in this
build; dev DB only.

## 7. Open decisions (dbc00per)

- **D1 — burner band range.** "Top 10 of the usable range": the mills have
  400 registers, so proposal = **N391–N400**. Confirm, or name a different
  band (it only needs to be clear of the permanent pool's growth and H50).
- **D2 — backfill conflict rule.** Proposal: abort-and-list (no guessing).
  Confirm, or pick highest/lowest/manual-per-tool.
- **D3 — resolution precedence.** Proposal: per-machine assignment wins over
  fleet-N fallback when both exist (assignment is the confirmable record).
- **D4 — do mirrored LG rows stay?** Proposal: keep them (harmless, already
  correct); the fallback makes future mirroring unnecessary rather than
  requiring cleanup of the past.

## 8. Gates

Migration 0012 up→down→up on dev; reconcile drift test extended; unit tests
for the allocator (append, burner recycle, N50 refusal, audit event) +
occupancy fallback (assignment-wins, fleet-N resolves, lathe excluded);
importer dry-run + apply against dev; full suite + ruff + mypy; frontend
typecheck/vitest/build. Read-only against all machines throughout.
