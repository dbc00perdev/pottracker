# spec-offset-export — offset table export (G10 + CSV) and running-program export

Status: BUILT 2026-08-06 (dbc00per GO same day). Modules: `services/g10.py`
(pure build+parse), `services/offset_export.py`, `services/program_export.py`,
`routers/exports.py`, `shared/focas/programs.py`, `ExportMenu.tsx`.
Remaining gate: dbc00per's per-class panel run (§1.4) → populate
`_FORM_VERIFIED_CLASSES` in offset_export.py to drop the DO-NOT-RUN header.

---

## 0. Safety classification (read this first)

**Every surface in this spec is READ-ONLY against the machine.**

- Offset export reads the **existing mirror** (`shared.focas_offset_register`)
  — zero new FOCAS calls for G10/CSV.
- Program export binds `cnc_upstart3` / `cnc_upload3` / `cnc_upend3` — these
  **upload FROM the control TO the PC** (a read). The write counterpart
  (`cnc_download*`) is **never bound** under this spec.
- The app never sends any file to a control. A G10 file becomes a write only
  when an operator loads and runs it at the panel — outside the app, their
  action, standard shop practice. The HARD GATE is untouched: `cnc_wrtofs`
  stays unbound.

---

## 1. G10 export

### 1.1 Sparse vs full

- **Sparse (default):** emit a register iff **any bank is non-zero**
  (lathe: Xg/Zg/Xw/Zw/Rg/Rw/tip; mill: Hg/Hw/Dg/Dw). All-zero register →
  omitted. Rationale: matches the occupancy model (all-zero = empty station);
  the FANUC panel's own punch-everything dump is noise.
  - Any-nonzero, not geometry-nonzero: a register with leftover wear/tip on
    zeroed geometry is stale garbage the export must SHOW, not hide.
  - Tip-only-nonzero is included (honesty over tidiness; revisit if annoying).
- **Full (explicit option):** every register including zeros. This is the
  "restore/wipe" artifact (cf. the ATC-reinit incident — recovery was "zero
  everything"); sparse structurally cannot zero what it doesn't name.

### 1.2 Semantics banner (mandatory header comments)

A G10 program only touches registers it names. The file must say which kind
it is, in-band, for whoever runs it months later:

```
(POTTRACKER OFFSET EXPORT)
(MACHINE: VIPER VT-23B  2026-08-06 14:32)
(SPARSE - 61 OF 99 REGS - UNLISTED REGS UNTOUCHED)
```
or `(FULL TABLE - WRITES ALL 99 REGS INCL ZEROS)`.

### 1.3 Values

- **Native control values, native unit, always** (`spec-offset-units.md`):
  inch shop-wide, 0.0001 increment → 4 decimals. `G20` emitted as the first
  block. No conversion path exists in this feature.
- One line per register, ascending register order.
- Values come from the mirror; the file records mirror `last_full_read` /
  freshness in a header comment so a stale export is self-describing.

### 1.4 G10 addressing — MANUAL-VERIFIED 2026-08-06; panel run = final gate

Verified verbatim against downloaded FANUC operator manuals (B-64604EN-2/01
§6.10 p.271 mill 0i-F; B-64304EN-2/01 §6.8 p.214 mill 0i-D — identical text;
B-64604EN-1/01 §5.1.8 p.151 + §5.2.3 + p.312 lathe 0i-F), cross-checked
against secondary machinist references. Research session 2026-08-06.

**Mill (0i-MF/MD, memory type C):** `G10 L1x P<offset#> R<value>` —
**L10 = H geometry, L11 = H wear, L12 = D geometry, L13 = D wear** (manual
verbatim). Traps the export MUST handle:

- **`G90` forced in the same program, explicitly.** G90 → R replaces; G91 →
  R is ADDED to the current value. A stray G91 modal turns the file into an
  accumulator that corrupts every offset. Emit `G90` before the G10 block.
- **Omitted L (or `L1`) silently means L11 (H wear)** — legacy-format
  compatibility. Every line carries its explicit L code.
- Memory type is param 8136#6 (NGW=0 → memory C, L10-13 valid) — one-time
  panel confirm per mill.

**Lathe (0i-TF/TD, T series):** `G10 P_ X_ Z_ R_ Q_ ;` — **P 1..n = WEAR
offset n; P 10000+n = GEOMETRY offset n** (manual verbatim; this is also
FANUC's own OFFSET-screen F-OUTPUT punch format, p.312 — our export emits
exactly what the control itself round-trips). X/Z/R = absolute values,
Q = tip number. Traps:

- **Never emit G90 on the lathe** — in G-code system A, G90 is the turning
  canned cycle. Absolute-vs-incremental is carried by address choice alone
  (X/Z/R absolute; U/W/C incremental — export uses absolute only).
- **No T code in a G10 block** (PS1144 G10 FORMAT ERROR).
- Nose radius has separate geom/wear cells (effective R = OFGR+OFWR),
  addressed by the P form. **Tip (Q) is ONE shared field** across geom/wear
  — export writes it once (geometry line), not twice.
- Offset count (P upper bound) is model/option-dependent (64/99/200/400) —
  use each machine's registry count, already known per machine.

**Both families:**

- **Every value gets an explicit decimal point** — a bare number is read in
  least-increment COUNTS (manual note), a silent 10000× error.
- Values follow the INPUT unit (G20/G21) — matches our INI-verified inch +
  `G20` first block. Increment fine-ness = param 5042 OFA/OFC (one-time
  panel confirm; expect 0.0001 in, matching the fleet-verified 1013 IS-B).
- G10 is group-00 one-shot; no mode gate. Param 3290 WOF/GOF write-protect
  is documented as MDI-only — worth one live confirmation that a G10 file
  respects/ignores the protect key as documented, MTB ladders vary.

**Remaining gate before an export is handed over as runnable:** dbc00per
runs a generated sparse file on ONE machine per class against scratch-safe
registers and panel-confirms the values landed in the right banks (the
write is the operator's panel action, not the app's). Until that run:
`(FORM UNVERIFIED ON THIS MACHINE - DO NOT RUN)` header stays on.

### 1.5 Round-trip test (CLAUDE.md rule)

Export → parse (own parser) → compare to mirror source: bit-exact, no
precision loss. Applies to sparse and full. The parser is also the future
G10-import front half (import stays out of scope here; imports never
auto-apply).

## 2. CSV export (crib consumer)

Same source, human/spreadsheet-facing:

- Columns: machine, register N, per-bank values (headers carry the unit,
  e.g. `h_geom_inch`), unit, `last_changed_at`, and the identity join where
  an active assignment exists (GTID, description) — the crib wants "what
  tool is this," not just numbers.
- Sparse/full option applies identically. No round-trip requirement (CSV is
  a report, not a program), but values are the same native strings the G10
  emits — one formatting function feeds both.

## 3. Running-program export (side feature)

Export the text of the program currently under execution (or any program by
O number) to a file.

- Bindings (verified present in `Fwlib64.h` this session, R9 rule):
  `cnc_upstart3` (11790), `cnc_upload3` (11796), `cnc_upend3` (11799).
  O number source: existing `read_program_info` (`cnc_exeprgname`).
- **Live-behavior gate:** many FANUC controls refuse to upload the program
  that is foreground-executing (busy/protect rc). Expected and fine — the
  export then reports "program busy, machine running; export when idle"
  honestly rather than retrying. Actual rc behavior per control class gets
  verified live (read-only) and recorded in `spec-focas-calls.md`.
- Output: verbatim program text, `O<num>_<name>_<machine>_<ts>.nc`; no
  reformatting, no line edits — byte-faithful to what the control sent.
- Loop guard: upload runs on the machine's existing service thread (FOCAS
  handles are thread-affined) and must not starve the poll cycle — chunked
  reads with a size cap; abort cleanly via `cnc_upend3` on any error.

## 4. Out of scope

- G10 **import** (staged-review pipeline) — separate feature, separate spec.
- Any `cnc_download*` binding — never under this spec.
- Work-offset / work-shift G10 (`L2`) export — possible follow-on.

## 5. Open items

- [ ] G10 mill L-code ↔ bank mapping verified (manual + panel eyeball)
- [ ] G10 lathe P-number geometry/wear convention verified (manual + panel)
- [x] `cnc_upload3` busy-behavior observed + recorded (2026-08-06,
      `scripts/probe_upload3.py`): **0i-TF (VT-23B, O80) AND 0i-TF Plus TT
      (JAKE_2100LYS .57, O9040) both uploaded their foreground-executing
      programs while cutting in AUTO**; 0i-TD + 0i-MF uploaded clean while
      idle (running-state upload unobserved there — export still handles a
      busy rc gracefully). EW_BUFFER = rc +10 = retry, not an error.
      Panthers are IN read scope for these features (dbc00per 2026-08-06);
      .56/.60 powered off — .57 is the Panther read-test machine.
      Details: spec-focas-calls.md "Program upload".
- [x] Where exports land: **browser download** (dbc00per 2026-08-06; rewire
      later if a shared-drop need appears)
