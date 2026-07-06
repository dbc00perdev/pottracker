# tasks/spec-potmap.md — Live Pot Map Sourcing (random-access ATC, no magazine option)

> Design decision for how the pot↔tool map is sourced on the Lance Viper
> LG-1000AP, given the FANUC magazine option is NOT licensed. Captured from the
> 2026-07-06 design discussion. Read-path only — no FANUC writes. NOT a blocker
> for Phase 2/3; must be resolved before the Phase 4 pot-map UI tab.

---

## Problem

`05-ui-flows.md` assumes a live pot map sourced from FOCAS. Phase 1 found that
mechanism is dead on this control:

- `cnc_rdmagazine` → `EW_NOOPT` (magazine option not licensed).
- All 6 secondary magazine fns (`cnc_rdcurmgr`, `cnc_rdcurpot`, `cnc_rdpotinfo`,
  `cnc_rdmagsts`, `cnc_rdspmaint`, `cnc_rdmgrptool`) are not exported by
  `fwlib30i64.dll` for this control.
- `cnc_rdtdiseltool` (selected tool) → `EW_NOOPT`.

The pot↔tool mapping lives in the **PMC ladder**, not the NC layer — same place
HEAD/NEXT live. `pmc_rdpmcrng` works and is our access path.

## Confirmed facts (operator-verified, Phase 1 + 2026-07-06 discussion)

| Fact | Value | Confidence |
|---|---|---|
| ATC mode | **Random-access** (returned tool takes any open pot) | Operator-confirmed |
| Loaded tool (spindle / HEAD) | PMC **R327** | Confirmed vs panel (HEAD=85) |
| Pre-call tool (pre-selected / NEXT / waiting) | PMC **R325** | Confirmed vs panel (NEXT=31) |
| Pre-call is shown on the machine panel | yes, dedicated display field | Operator-confirmed |
| `Txx` pre-index behavior | **`Txx` alone pre-indexes the magazine; `M06` performs the swap** | Operator-confirmed |

Because the ATC is random-access, **Option B (static/manual pot map) is OUT** —
it would go stale the instant the machine reshuffles and manufacture the
app-vs-machine disagreement R11 says kills adoption.

## Why the pre-call is the lever

A `Txx` pre-call does physical work: the magazine **indexes** so the
pre-selected tool's pot reaches the change position, before `M06` swaps it.

1. **Proves a tool→pot lookup table exists in the PMC.** The ladder can't index
   to the correct pot without consulting one. The data is physically there to
   be found — not hypothetical.
2. **Pre-call + magazine position = one `(tool, pot)` fact per change.** At
   pre-selection the magazine is physically indexed to that tool's pot. Pairing
   the (panel-verified) R325 pre-call with a magazine-position read yields an
   auditable pair. Accumulate over a shift → full map by observation.
3. **Operator-verifiable** (R11): the pre-call shows on the panel, so our R325
   read — and any map built on it — can be cross-checked against the machine.

## Strategy — two routes, one probe

Both targets move when the magazine indexes, so a single snapshot/diff probe
surfaces both.

- **Route 1 (best): full pot array.** Find the pot→tool (or tool→pot) array in
  the PMC. Read all ~24 cells each poll → always-current map. One cell changes
  when a returned tool takes an open pot.
- **Route 2 (now the primary bootstrap): position + pre-call, driven by a bare-`Txx`
  calibration sweep.** Because `Txx` alone pre-indexes (confirmed), an operator can
  run `T1 … T24` as **bare pre-calls in single-block MDI — no `M06`, magazine-only
  motion, no tool exchange**. Each pre-call stages that tool's pot at the change
  position; we read `(tool = R325, magazine-position register)` and diff. Result: a
  **deterministic full-magazine map in ~24 clean steps**, each step cross-checkable
  against the panel pre-call field. Also refreshes live during production (every
  program `Txx` updates the pair).

**Recommended:** use the bare-`Txx` sweep (Route 2) to bootstrap + validate the map,
and read the full array (Route 1) each poll for always-current steady state if it
decodes. They're complementary: sweep = deterministic calibration, array = continuous
full read. Option E
(pot-number-free state UI: loaded / next / in-magazine / not-loaded) remains the
guaranteed-shippable floor using only R327/R325 we already have.

## Probe protocol (`probe_potmap.py`, to be written)

Same snapshot/diff play that isolated R327/R325; `probe_modal_v7` already dumps
full PMC across R/D/F/K/E areas.

1. Dump full PMC state (baseline).
2. **Bare-`Txx` sweep (primary):** operator runs `T1 … T24` as bare pre-calls in
   single-block MDI (magazine-only motion, no `M06`). Diff after each. The byte
   that tracks the pre-called tool's pot is the **magazine-position register**;
   R325 confirms the tool. Pair per step → tool→pot for all 24.
   - Safety: bare-`Txx` is pre-index (magazine rotation) only; operator confirms a
     safe machine state first (spindle empty, no program running).
3. **Optional `Txx M06` cycles (for Route 1):** a few real changes so a returned
   tool takes an open pot — isolates the pot-**array** cell that mutates, revealing
   the full array's location/orientation for always-current reads.
4. Changed bytes cluster into: HEAD (R327), NEXT (R325), the magazine-position
   register (step 2), the pot-array cell (step 3) + timer noise.
5. Cross-reference the changed pot cell against post-change HEAD to determine
   pot-indexed vs tool-indexed, and byte/word/BCD encoding.
6. Bind found addresses as per-machine constants (like `_PMC_R_HEAD_ADDR`);
   document here + in `spec-focas-calls.md`. Re-derive for AG100 in Phase 8.

## Integration — nothing built so far is wasted

The persistence layer is **source-agnostic**. `shared.db.focas_pot`,
`decode_pot`, and `snapshot.diff_pots`/`persist` all consume `PotEntry` tuples.
Whichever route wins, we only swap the *producer* inside
`FocasClient.read_pots()` (which today returns `()` on the `EW_NOOPT` it
detects) with a PMC decoder. Diff + persist + audit are unchanged.

## Open questions

- **PMC-O1**: address + encoding of the magazine-position register (unfound).
- **PMC-O2**: address + encoding + orientation (pot→tool vs tool→pot) of the
  pot array (unfound; existence proven by the pre-call mechanism).
- **PMC-O3**: RESOLVED (2026-07-06, operator-confirmed) — `Txx` alone pre-indexes;
  `M06` swaps. Enables the bare-`Txx` calibration sweep (Route 2 bootstrap).
- **PMC-O4**: per-machine — AG100 will have different addresses (OEM ladder).
  Re-run the probe in Phase 8; never assume cross-machine.

## Scope / safety

Reads only via `pmc_rdpmcrng` — outside the FOCAS-write confirmation zone. Needs
operator machine-time (a few tool changes), not a code-only task. Does not block
Phase 2 (persistence) or Phase 3 (API); resolve before wiring the Phase 4
pot-map tab.
