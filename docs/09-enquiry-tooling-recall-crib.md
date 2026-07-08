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
Part returns or a tool is needed. **Preferred: re-measure, don't push** — see
"Preferred recall mechanism" below (app writes the `#190+` measure recipe → operator runs
the machine's batch measure cycle → app verifies + flags drift). A **direct offset push**
is the fallback only for genuinely stable fixed-length assemblies, and even then is gated by:
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

## Preferred recall mechanism: macro-table-driven re-measure (NOT offset push)

Machines with a **multi-tool measure cycle** give a far safer recall path than the app
writing offsets directly. The two lathes run **program `O8207`** — a batch tool-measure
cycle driven by macro variables **`#190` and up** (operator sets the `#190` table to
designate the tools; the machine measures them all). **Two variants: one sequential, one
random**, both using the `#190`'s for the set functions.

Recall then works as "app proposes the recipe, the machine measures fresh":

1. **App writes the measure *recipe*** (which tools + mode) into the `#190+` macro table —
   a `cnc_wrmacro` write to **common variables only** (nothing moves, no offset touched).
2. **Operator loads the tools from the static crib and calls `O8207`** (sequential/random)
   — human gate, on a program the shop already trusts.
3. **The machine measures every designated tool fresh** with its own proven cycle and sets
   the offsets. **The app never pushes an offset value.**
4. **App reads the resulting offsets back and compares to the proven/labeled crib values**
   → flags **drift** beyond a threshold.

**Why this is the safest version (combines with the `cnc_wrmacro` note below):**
- App writes only `#190+` common vars — **never the offset register directly.**
- Operator invokes the cycle (human gate); it's a trusted existing program.
- **Fresh measurement eliminates the stale-offset hazard entirely** — offsets are re-measured,
  never recalled-and-pushed. (This designs out the single most dangerous part of the concept.)
- The stored/proven offset becomes a **drift-detection cross-check** (R6/R11), not a command:
  *"labeled 5.6883, measured 5.40 → check tool 21"* catches wear / regrind / wrong tool / damage.
- Workflow A's "proven recipe" therefore stores the **`#190` measure table**; recall = reload
  the recipe → operator runs `O8207` → app verifies + flags drift.

**Note on `cnc_wrmacro`:** FOCAS can write custom-macro **common** variables (`#100–199`,
`#500–999`) via `cnc_wrmacro` / `cnc_wrmacror`; **system** vars (`#5000`-series skip/position)
are read-only. Writing a common var is inherently lower-risk than a direct offset write — the
value is inert until a machine-side macro/operator acts on it. Still a FOCAS write (Phase 6
regime); untested on these controls — confirm `cnc_wrmacro` is exposed + macro-protection
allows `#190+` writes before relying on it (R9 discipline).

**To verify / map (read-only + operator input, per machine):**
- The **`#190+` table layout** for `O8207` (which var = tool #, which = mode/sequence) — probe +
  operator/macro docs, same approach as the pot-table mapping.
- Whether the **Viper (mill)** has an equivalent batch cycle, or only the single-tool presetter
  (`#100+` macro we mapped this session). O8207 is on the **lathes**; each machine's measure macro
  is its own integration point (per-machine, like the PMC bindings).
- Drift threshold + on-drift behavior (flag / require operator ack / block).

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
