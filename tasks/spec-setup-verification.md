# spec-setup-verification.md — job setup + toolsetter verification

**Status**: LOCKED items only (dbc00per, 2026-07-15). Open items are tracked separately
and deliberately not restated here.

The workflow dbc00per intends: machine broken down, empty carousel, a job needs N tools.
The app resolves the job's tools from the crib, writes their confirmed offsets, the
operator loads the carousel, and the machine's toolsetter independently confirms each tool
before the job runs.

---

## 1. Roles — who owns what

| Thing | Owner | Notes |
|---|---|---|
| **GTID** | the app + crib | **Source of truth.** The app functions off confirmed crib data. |
| **Preset length (GEOM H)** | the crib | Measured + confirmed. Static until the assembly is torn down. |
| **Diameter** | the CAM seat | The toolsetter *can* measure diameter; the shop relies on CAM for it. Consequence: physical diameter is never confronted with reality — see §6. |
| **WEAR D** | the operator | Tight-tolerance diameter sizing. Never app-written. |
| **WEAR H** | the operator | Fine length adjustment. Never app-written. |
| **Pot ↔ T mapping** | app writes it, machine owns it after | App writes the initial map (§10). On a random-access ATC pots drift as tools return, so the app is authoritative **only at load time** and is an observer thereafter. |

## 2. The unit of identity is the assembly

GTID = **preset assembly** (cutter + holder + stickout + measured length). The assembly is
**not broken down between jobs** — it stays built, and only moves between pot, spindle and
the crib. Its measured length therefore **does not change** except when the assembly is
physically torn down or re-presetted.

Teardown / re-entry is already locked in `spec-tool-numbering.md` §6:
- **Reset** — same cutter, re-measured: same GTID, same N, `regrind_count++`, log new length.
- **Retire + create new** — rebuilt into a different tool: old GTID soft-deleted, history
  preserved, new GTID takes the vacated permanent N or a burner N.
- **Never a hard delete.**

The crib's length is always the **latest logged** preset, not the original.

## 3. The machine has no GTID field

The pot table is **one BCD byte per pot** (`D105`–`D128`, values 0–99). The control's entire
vocabulary for "what is in pot 19" is the number 83. The app owns `GTID → N → T → pot`
internally and can only ever hand the machine a **T number**. GTID never reaches the control.

## 4. Measurement

- **One instrument.** The machine's toolsetter performs all measurements — new, reset,
  rebuilt. There is no bench presetter, so stored and checked values are like-for-like.
- **Both mills have a toolsetter, and they agree** (dbc00per, 2026-07-15) — a tool measured
  on the AP and on the AG returns the same measurement. This is the premise the fleet-wide
  static N length rests on.
- The app **must never encode a machine-to-machine tolerance** (`lessons.md`). Cross-mill
  portability is achieved machine-side via equalized homes. If the two setters ever disagree,
  that is fixed at the machine, not with a per-machine column.

**Provenance is required.** The crib stores `preset_length`, `preset_machine_id`,
`preset_at` — not just a length. Without which-machine-and-when you cannot distinguish a
worn tool from a drifted datum, or re-baseline a machine's tools.

## 5. The offset write — justified, H_GEOM only

The app writes the **confirmed crib length** to GEOM H before the operator loads the
carousel. Rationale (dbc00per): it removes the human from the equation — the fat-fingered
wrong offset — and writes proven data instead of typed data.

**Polarity: the crib is the authority; the toolsetter is the independent confirmation.**
Not the reverse. A fresh toolsetter reading is a single unverified measurement (a chip on
the setter, a dirty taper); the crib value is confirmed and long-lived. Writing the proven
value and letting the setter disagree with it is what catches a bad measurement — trusting
the fresh reading as truth would not.

Writable set = **H_GEOM only**, which is the existing `WRITABLE_TYPES_V1` and D2 decision:
- GEOM D — stays 0 (CAM programs from centerline). Nothing to write.
- WEAR H / WEAR D — operator-owned. Never written.

This is the already-specced **PR-4** path and stays behind the full HARD GATE (mode lockout
+ the ask + the entry, read-after-write verified). `spec-offset-units.md` is a prerequisite:
the drift gate must be in inches before it can catch a transposed digit (`5.5147` typo'd as
`5.5417` = 0.027").

## 6. Verification sequence

1. App resolves the job's tools from the `.set` → N → GTID → crib.
2. App writes confirmed GEOM H per tool (gated).
3. App shows the pot assignment; operator loads the carousel.
4. Machine runs the toolsetter against each tool.
5. App reads back and compares measured vs crib.
6. Disagreement stops the job.

**What the length check catches**: a wrong tool in a pot, or a swap between pots — the
lengths of tools in a job are separated by tens of thou (closest pair in the Viper on
2026-07-15: 0.036"), so a swap moves the measurement far outside any sane tolerance.

**What it does not catch**: physical diameter. Diameter comes from CAM and is never
confronted with reality, so a right-length / wrong-diameter tool passes clean. This is a
known, accepted limit of the gate — it is a plausibility check, not identity proof.

## 7. Wear is real and is a signal, not noise

The assembly is stable but the cutter is not — tips erode between presets. Since one
calibrated instrument measures every tool at every setup, **every touch-off is a wear
measurement of that assembly.** Logging `(GTID, machine, value, timestamp)` yields:

- one tool drifting on both mills → **wear** (the tool-life curve, measured not inferred);
- every tool off by the same delta on one mill → **that machine's datum moved**, not a tool
  problem;
- a tool clean on one mill and off on the other → **the two setters disagree** (§4's premise
  being audited automatically).

This logger is **read-only, needs no crib and no write**, and the whole chain is already
proven on hardware (2026-07-08: G31 skip → macro → toolsetter writes GEOM H → app read it
back and tagged `presetter_verified`).

## 8. Wear direction and the verification gate

**Wear makes GEOM H smaller** (dbc00per's brother, 2026-07-15) — the tip erodes, the
gauge-line-to-tip distance shrinks. This is monotonic and one-directional, which makes the
gate **asymmetric**:

| Measured vs crib | Meaning | Action |
|---|---|---|
| **Smaller**, within tolerance | Normal wear | Pass. Log the point on the wear curve (§7). |
| **Smaller**, beyond tolerance | Worn out, or the wrong (shorter) tool | Stop. |
| **Larger**, any amount | **Cannot be wear.** Built-up edge, chip on the setter, debris on the taper, an unrecorded re-preset, or the wrong tool. | Stop and look. |

A tool reading **longer** than its confirmed preset has no legitimate explanation on this
process. That direction is not a tolerance band — it is an anomaly by construction.

**Tolerance = 0.002"** (dbc00per, 2026-07-15: "2 to 3 thousandths"). The tight end of the
stated range is taken as the default because this is a safety gate; it is one config value
per machine and trivially widened to 0.003" if it proves noisy.

One threshold covers both jobs this gate does, because the numbers are far apart:
- **Condition** — a worn or damaged assembly trips at 0.002".
- **Identity** — a wrong tool or a pot swap moves the length by *tens* of thou (closest
  pair in the Viper on 2026-07-15: **0.036"**), so 0.002" catches every swap with ~18×
  margin and no reliance on the tolerance being tight.

## 9. Carousel clearance

**Max tool diameter = 3.8"** (dbc00per, 2026-07-15). The largest tool in the census is the
3" 8FL face mill, so **nothing in the current library requires empty neighbouring pots** —
any tool may occupy any empty pot, which is dbc00per's original position ("it could be any
5 empty pot locations feasibly"). No neighbour rule is needed in v1.

Any future tool over 3.8" invalidates this; the app should refuse to place a tool whose
crib diameter exceeds the machine's limit rather than assume clearance.

## 10. The pot-table write — APPROVED (dbc00per, 2026-07-15)

**Decision: the app writes pot ↔ T into the control.** Rationale is the same as the offset
write — remove the human from the equation, write confirmed data rather than typed data.
This was the one item where the recommendation was to display-only; dbc00per's call is to
write, and it is his machine and his risk to weigh.

**It is a new FOCAS write path and gets the full discipline:**

- **The HARD GATE already covers it.** CLAUDE.md is explicit: *no write to any FANUC
  control (offset, pot, parameter, any register)* executes without mode lockout + the ask +
  the entry. `write_safety.py` was built around offset targets and must be extended to
  understand pot targets.
- **Function verified present** (2026-07-15, rule R9): `pmc_wrpmcrng` is declared in
  `Fwlib64.h:15124` and exported by `Fwlib64.dll`. Note the signature differs from the read —
  `(handle, length, IODBPMC*)`, with the area/address carried inside the struct.
- **Target: PMC D-area `D105`–`D128`, packed BCD**, the same cells `read_pots_pmc` reads.
  `decode_pot_bcd` exists; an `encode_pot_bcd` and its round-trip test do not.
- **Probe protection (R12).** The probe floats — `probe_pot` is dynamic, resolved by
  whichever pot holds `probe_t_number`. The pot write must never displace or overwrite the
  probe's pot. This is a different check from the offset path's static probe-register guard.
- **Read-after-write is mandatory** — read the pot table back and confirm every cell.
- **PR order mirrors the offset path: mock-only first, gate-blocking tests second, real
  `pmc_wrpmcrng` binding LAST.** No test, script, soak or harness may target the real
  machine's write functions (CLAUDE.md anti-pattern #10).

**Known risks to carry into that spec** (recorded, not re-litigated): the magazine option is
unlicensed on this control (`cnc_rdmagazine` → `EW_NOOPT`), so there is no sanctioned FOCAS
magazine path and this writes raw ladder-owned memory; a wrong address or encoding corrupts
the ATC's model of itself, which is the failure mode of the documented off-by-one incident.
Whether the ladder overwrites these cells, and what happens if they are written mid-ATC-cycle,
are unknown and must be established on the mock and then under supervision before any live write.
