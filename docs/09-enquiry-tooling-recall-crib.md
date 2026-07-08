# 09 — Enquiry: Proven Tooling Recall + Static Crib

> **Status: ENQUIRY — captured for later, NOT v1 scope.** Depends on the Phase 6
> FOCAS **write** path and its safety gates. Raised by dbc00per 2026-07-08 after
> the live presetter → offset verification was proven on the Viper. Refine before
> promoting to a phase spec.

---

## Problem

Repeat parts re-run months apart. Today each re-setup means **re-presetting every
tool from scratch** — slow and error-prone. And when tools are pulled after a job
and their machine offsets zeroed, the **measured offset data is lost.** We want to
persist proven tooling data *with the physical tools* and recall it on demand.

## Core idea

The app is the **digital twin of a static physical tool crib.** Every tool has a
**permanent, labeled crib location that never changes** (e.g. Tool #21 always lives
in the same slot; its physical label reads its offset, `5.6883`). The app stores
each tool's proven offset + provenance and can push it back to the machine when the
tool/part is needed again — behind the Phase-6 write gate.

## Workflows

### A — Capture at proof-out
Program runs good → operator marks it **proofed** → app snapshots the tools that ran
+ their offsets as a **proven tooling recipe** tied to the part/program, stamped with
**provenance** (presetter-verified via G31 skip; ran-good).

### B — Decommission (save-before-zero)
Finishing a job, operator pulls the tools → app **saves each tool's current offset**
(bound to tool identity + crib location + provenance) → *then* the machine offsets are
zeroed. Tool returns to its static crib slot.

### C — Recall / restore  (this is the FOCAS write)
Part returns or a tool is needed → app **pushes the stored offset** to the machine
(operator physically loads the tool; the pot is *observed*, R10). Gated by:
- **proven-file confirmation** ("this is the proven recipe for this part"), and
- the full **Phase-6 write safety**: two-stage confirm, pre-write re-read + drift
  abort, read-after-write verify, mode lockout, plausibility range.

## Physical crib model
- Static, **labeled locations that do not change**; `tool ↔ crib_location` is permanent.
- The physical label mirrors the app's stored offset (human-readable copy).
- App is authoritative for the digital record; the crib is the physical source of the tool.

## How it builds on what was proven (2026-07-08)
- **Provenance = the validated verification model:** an offset is "proven" only when it
  was **presetter-set** (G31 skip `#5061-63` attribution) **and** **ran good parts**.
  Only proven offsets are pushable. See `tasks/lessons.md` (presetter→offset chain).
- **Offset = truth** (non-zero = real measured tool) is already established.
- Recall is a **tool-identity-aware, provenance-gated variant of G10 import** (Phase 7/9)
  — a proven per-tool recipe instead of a raw file.

## Critical safety considerations (resolve before any build)
1. **Stale-offset hazard (R6 — scrap/crash).** A stored offset stays true only if the
   physical tool doesn't change. Works for **fixed-length preset assemblies** (tool +
   holder set to a gauge length, never touched). **Dangerous** for reground / rebuilt /
   consumable / bumped tools — pushing `5.6883` to a tool that's now `5.4` crashes on the
   first move. → **Push is NEVER blind.** Stored value is a *proposed* value requiring
   confirmation; `consumable_class` / reground tools **require re-verification (re-preset)**
   rather than trusting the number.
2. **Provenance gating.** Only push offsets tagged proven (presetter-verified + ran-good).
   Non-proven → warn/block.
3. **Identity integrity (R18-style).** The app **cannot detect a physical tool swap** — a
   wrong tool in slot 21 makes the label lie. Relies on crib-labeling discipline; default
   posture should be **re-verify-on-reinstall**.
4. **Phase-6 dependency.** This is a write feature; it cannot ship before the write path
   and its gates exist. v2 scope.

## Data model additions (sketch — not final)
- `tool.crib_location` — static labeled location (permanent).
- `offset_snapshot` — `(tool_id, register_type, value, provenance, proven_program_id,
  captured_at, verified_by)`.
- `tooling_recipe` — `(part_id / program_id → [ {tool, expected_offset, provenance} ])`.

## Open questions (for later)
- How is **"proofed"** signaled? Operator marks it, vs FOCAS program-end + sign-off.
- How to know which tools **"ran during"** a program? Active assignments + observed tool
  changes during the run (head/next from PMC `R327/R325`).
- **Consumable / reground** tools: exact re-verify policy.
- **Crib location** schema + labeling workflow.
- **Push granularity:** per-tool vs whole-recipe.
- **Wear vs geometry:** `d_wear` is panel-only on the Viper (FOCAS-unreadable) — recall
  covers geometry; wear stays operator-managed.
- **T ≠ H:** recall must carry the tool's actual H (and D) register, not assume H = T.
