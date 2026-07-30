# Spec — VT_23 smarter active-offset display (L1+L2)

Approved by dbc00per 2026-07-29 (session prompt); go given 2026-07-30.
Branch `claude/vt23-offset-display` off `b3fc5e6`. Read-only against all
machines; dev DB localhost:5433 only; `cnc_wrtofs` unbound (HARD GATE).

## Why

The VT_23 hub shouted amber **NO OFFSET** whenever the commanded T word was a
cancel (`Tnn00` or bare station). But the shop cancels the offset with `Tnn00`
at the end of EVERY op (docs/14 convention) — so on an idle machine a canceled
offset is *normal*, not a warning. Amber is only honest when the machine is
actually running with no offset applied.

## Level 1 — context-aware NO OFFSET (frontend only)

`LatheTurretTable.tsx` hub, when the T word carries no offset digits:

- `spindle.running === true` → amber bold **NO OFFSET** (unchanged — cutting
  with no active offset is worth shouting about).
- otherwise (idle / unknown) → neutral gray **"offset canceled (idle)"**.

## Level 2 — last-real-offset memory

A cancel erases the live word's offset digits, so the hub can't say *which*
offset was last active. Persist a memory of the last real `Tnnww`:

- **Migration 0011** — nullable `last_tool_t_word` (int) + `last_tool_at`
  (tz timestamp) on `shared.focas_machine_status`. Round-tripped on dev.
- **Persist path** — `snapshot_diff.diff_status` sets the fields ONLY when the
  incoming word has real offset digits (`t >= 100 and t % 100 != 0`); on a
  cancel it emits None and `_upsert_status` preserves the stored value via
  `COALESCE(excluded, current)`. A cancel never erases the memory.
- **Mills excluded by construction** — mill HEAD ids are raw tool numbers
  (< 100), never `Tnnww`, so the fields stay NULL there (same per-profile
  precedent as `active_wcs`).
- **`StatusState` unchanged** — the memory only moves when the live word moves,
  which already flips `changed`; it is derived state, not observed state.
- **API** — `SpindleOut` + `GET /machines/{id}/spindle` gain both fields.
- **Hub** — live word is a cancel + memory exists →
  `S8 · canceled · last OFS 08 · Nm ago`, colored per the L1 running/idle rule.

## Safety

No FOCAS surface touched — the commanded-T read (`cnc_rdcommand`) already
exists; this is mirror/display only. Migration touches `shared` schema on the
dev DB only (Stop-Condition covered by dbc00per's go).

## Gates

Full suite + ruff + mypy; frontend typecheck/vitest/build; migration
up→down→up on dev; live verification on the VT_23 page after a stack bounce.
