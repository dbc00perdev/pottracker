# 14 — GCG ↔ Pot Tracker Integration (Parametric Standards → Verified Mill Setups)

**Status: PROPOSAL** (dbc00per + Claude, 2026-07-29). Nothing in this document is
built. It exists so the design survives between sessions and so the concept can
be presented to the machinists in plain terms before any build starts.

Related: `docs/09-enquiry-tooling-recall-crib.md` (recall/proven recipes),
`docs/11-machine-classes.md` (lathe class), `tasks/spec-setup-verification.md`
(job setup + toolsetter verification), `tasks/spec-tool-numbering.md` (N-model).

---

## 1. The idea in shop terms (read this part aloud to the crew)

Most of our parts are **standards**: the same part in different sizes. A 3/8"
version and a 1/2" version are the same program with different numbers — and
different tools.

Today, making one means: pick the right program revision, remember which tools
it needs, check they're in the machine, check they're measured, and trust that
nothing changed since last time. Every one of those steps is a human memory
step, and every one of them has bitten a shop somewhere.

The plan is to connect two things we already have:

1. **The generator** (dbc00per's program generator — the same tool that already
   makes our sleeve programs). It gets a new module: enter the size and options
   for a standard, and it produces the complete mill program. No CAM session,
   no editing an old program, no wrong-revision risk — the program is *made
   fresh from the numbers you typed*.

2. **The pot tracker** (the app that watches the Viper). It already knows, live
   from the machine, every tool in the crib, every tool in the carousel, and
   whether each one has a real toolsetter-verified length.

Connected, they close the loop:

> **Generate the program → the app checks the machine → you get a green light
> or an exact pull list.**

Concretely, when a program is generated it carries a list of the tools it needs
(by their **N numbers** — the permanent offset numbers on every tool tag). The
app compares that list against the machine *right now* and answers, in one
screen:

- ✅ these tools are loaded, measured, and verified — nothing to do
- 🟡 these tools are in the crib but not in the machine — **pull list**: "pull
  N51, N24, N5; pots 16, 20, 22 are free"
- 🔴 this tool doesn't exist in-house at all — stop before you start

**What this kills:** wrong program revision, missing tool discovered mid-setup,
running against an unmeasured offset, typo'd offset numbers, and "I thought
that tool was still in the machine." The machine is read the same way the
operator would check it — the app just never forgets and never skims.

**What this does NOT do:** it does not write anything to the machine. Checking
is read-only. (A gated offset-write step exists in the roadmap as its own
heavily-guarded feature — approval + password, machine idle — and is separate
from this.)

---

## 2. Why this works now (and didn't before)

Three things landed in July 2026 that make this integration cheap instead of
speculative:

1. **The crib is digitized and machine-readable.** All 58 (and growing)
   N-labeled stations live in `tooling.tool` with geometry, manufacturer, EDP,
   and assignments (`docs/data/tool-library.csv` → dev DB, 2026-07-28).
2. **N is permanent.** The N-model (`spec-tool-numbering.md`) made offset
   numbers static and fleet-wide for the life of a tool. A generated program
   that says `T37 M06 / G43 H37` does not rot — that stability is the entire
   reason permanence was moved from T to N.
3. **The machine is mirrored live.** Pots (identity), offsets all four banks
   (presence + wear), HEAD/NEXT (location), and presetter-vs-manual attribution
   are polled every 60s and audited. "Is the machine actually ready?" is now a
   database query, not a walk to the panel.

---

## 3. The loop, end to end

```
 dbc00per enters size/options            (GCG standards module — to be built)
        │
        ▼
 GCG resolves tools FROM CRIB TRUTH      (crib.json export from pot tracker)
        │        "need SQ EM ≥ Ø.500 4FL" → N51
        │        no match → REFUSE at the desk, name what's missing
        ▼
 GCG emits: program (.nc) + MANIFEST     (extends the existing setup-record JSON)
        │        manifest = N numbers called, geometry assumed, material row,
        │        units, standard + size + parameter set (the program's identity)
        ▼
 Pot tracker PRE-FLIGHT (read-only)      (new screen — to be built)
        │        every N: in crib? loaded? offset ≠ 0? presetter-verified?
        │        G20 vs control unit; no T50/H50 calls; pots free ≥ tools needed
        ▼
 GREEN LIGHT  or  PULL LIST              (operator loads; toolsetter verifies;
        │                                 app watches it happen via G31/attribution)
        ▼
 RUN — and the pairing (manifest + as-loaded machine baseline) is archived
                                          → the proven-recipe library (docs/09)
                                            for the next time this standard runs
```

## 4. Integration points, in build order

| # | Piece | Side | Effort | Notes |
|---|-------|------|--------|-------|
| 1 | **Crib export** — read-only `crib.json` (N, geometry, type, flags, description) | pot tracker | trivial | Button/endpoint. Same "label emitter" pattern as the Parts Bin tie-in: the GCG stays standalone and reads a file; **no DB coupling** (Decision-10 discipline). |
| 2 | **Mill standards module** | GCG | dbc00per | The parametric core: variables in → program out. Consumes crib.json for tool resolution (requirement → N), refuses on no-match. |
| 3 | **Manifest** | GCG | small | Extend the existing canonical setup-record JSON with the tool/N list + assumptions. This is the contract between the two apps — define it together first. |
| 4 | **Pre-flight screen** | pot tracker | moderate | Ingest manifest → verdict vs live mirror → pull list. Pure read. This is `spec-setup-verification.md` with the program as the input. |
| 5 | **Run archive** | pot tracker | small | Store manifest + as-loaded baseline at "setup complete." Recall/diff on re-run (docs/09). |
| 6 | *(later, gated)* **Offset push** | pot tracker | Phase 5/6 | The write half of setup: app writes confirmed crib lengths, toolsetter independently re-verifies. Lives entirely behind the HARD GATE; not part of this integration's v1. |

## 5. Rules the generator inherits from the machine registry

Because the crib export can carry machine facts, the GCG can enforce at the
desk what the app currently only enforces at the API:

- **Never emit T50/H50** (Viper probe identity lock, R12).
- **Stamp `G20`**; pre-flight cross-checks program units against
  `shared.machine.offset_unit` (the 25.4× error class, `spec-offset-units.md`).
- **Warn when a program calls more distinct tools than the machine has free
  pots** (24-pot carousel reality).
- Feeds/speeds computed from **actual crib geometry** (diameter/flutes as they
  are *after* the last rebuild), not nominal catalog values.

## 6. Boundaries (unchanged from everything else in this project)

- GCG remains standalone; integration is via **exported read-only data + a
  manifest file**, never a shared database.
- Program generation is **never a write path to the machine**. Pre-flight is
  read-only. Offset writes remain a separate, later, HARD-GATE feature.
- CAMWorks TechDB keeps the complex parts; the GCG standards module is
  complementary (family-of-parts generation for parametric standards), and
  both consume the same crib truth.

## 7. ADDENDUM 2026-07-29 — the live target arrived: VT_23 is v1, mill module is v2

Same-day development: first contact with **VIPER VT_23 (10.1.10.53, FANUC
0i-TF lathe)** — and dbc00per confirms it is **the only machine GCG currently
runs on**. That inverts the build order: the integration no longer waits on the
mill standards module. The existing sleeve/extension/bit-holder modules + the
now-readable VT_23 are the v1 pairing:

- **Pre-flight for today's programs**: parse the generated `Txxyy` calls →
  verify each called offset has geometry set on the control (99 regs read
  live); compare stored **nose radius (bank t5)** and **tip orientation
  (t6/t7)** against the program's cutter-comp assumptions — the silent
  scrap-makers a human never re-checks.
- **Wear-bank mirroring (t0/t2)** = sizing-drift trends + unattributed-edit
  review on the main products.
- **Run provenance now**: GCG's canonical setup-record JSON + a VT_23 offset
  snapshot at cycle start.

Gates before v1 (small): panel cross-check to NAME the eight banks (which of
t1/t3 is X vs Z; artifacts `reports/vt23-*-20260729.json`); lathe T-call parse
in the manifest/pre-flight; delivery shape decision (standalone read-only
pre-flight script may precede full app onboarding — docs/11 lathe-class UI
gates the screens, not the check). R20 stands: when the VT_23 enters the app
it gets a **turret view**, never a mill pot map.

The mill standards module (§1–6) remains the plan — as **v2**, on an
integration already proven on the lathe.

## 8. Open items before v1 (original mill-module list)

- [ ] dbc00per: enumerate the first standards family to parameterize (which
      part, which size range, which tool requirements).
- [ ] Define the manifest schema together (one working session).
- [ ] Decide crib.json delivery: manual export button (simplest) vs the GCG
      fetching the read API directly (needs the API running + CORS).
- [ ] Machinist walkthrough of §1 — collect objections early; the pull-list
      screen is for them, so its shape should come from them.
