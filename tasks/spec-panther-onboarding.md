# Spec — Panther Group Onboarding (3 × 0i-TF Plus lathes)

**Status**: IN PROGRESS — read-only slice done 2026-08-05 (gates 0–4 + 7).
**Owner**: dbc00per. **Gate checklist**: `docs/10-fleet-architecture.md` §7.
**Precedent**: VT_23 zero-to-live (SESSION_NOTES 2026-07-29).

---

## 1. The machines

| Shop name | Registry name / UUID | IP | Identity (sysinfo, read 2026-08-05) |
|---|---|---|---|
| CNC Lathe 6 | **PANTHER JAKE_2100LY** `77d657a0-6f75-4a3d-867d-584c8589216a` | 10.1.10.56 | `0` / **T** / **D6G3** v29.0, 5 axes. Panel model **A02B-0348-B502** (0i-TF Plus, dbc00per-supplied) |
| CNC Lathe 7 | **PANTHER JAKE_2100LYS** `5f263ff3-3a24-4d73-9652-e3955ee5253a` | 10.1.10.57 | `0` / **TT** / **D6G3** v35.0, 5 axes |
| CNC Lathe 8 | **PANTHER PROD_2100LYS-2** `9b406589-12ac-4829-a722-258a9a67a3cf` | 10.1.10.60 | `0` / **TT** / **D6G3** v55.0, 5 axes |

Physical (dbc00per 2026-08-05): every turret is 12-station **half-indexing → 24
tool positions** (`pot_count=24`; matches the observed Tnnww numbering, e.g.
T1919 live in O9034 on .57). Lathe 6 has **no sub-spindle** (single path, `T`);
Lathes 7/8 have **sub-spindles** (two-path controls, `TT`).

**IP conflict, resolved**: dbc00per's shop list first had Lathe 8 at
10.1.10.58 — that IP answered as the **VIPER AG_1000 mill** (M / D4F1); the
identity gate stopped the sweep after one sysinfo read. Lathe 8 is at **.60**
(confirmed by full sweep). Never re-derive Lathe 8 from the old list.

---

## 2. Gate status (docs/10 §7)

| Stage | JAKE_2100LY (.56) | JAKE_2100LYS (.57) | PROD_2100LYS-2 (.60) |
|---|---|---|---|
| 0 Registry draft (`enabled=false`) | ✅ 2026-08-05 | ✅ | ✅ |
| 1 Network 8193 | ✅ | ✅ | ✅ |
| 2 DLL path | ✅ (same Fwlib64 runtime as VT) | ✅ | ✅ |
| 3 Identity | ✅ sysinfo above | ✅ | ✅ |
| 4 Capability probe | ✅ `reports/lathe56-capability-sweep-20260805.json` | ✅ `…lathe57…` (+ `…lathe57-active-program…`) | ✅ `…lathe60…` |
| 5 Binding discovery (active tool / turret) | ⬜ | ⬜ | ⬜ |
| 6 Panel cross-check | ⬜ sheet: `reports/panther-panel-crosscheck-lathe56.md` | ⬜ `…lathe57.md` | ⬜ `…lathe60.md` |
| 7 Increment / unit lock | ✅ fleet-verified (see §3) | ✅ | ✅ |
| 8 Soak | ⬜ | ⬜ | ⬜ |
| 9 Enable | ⬜ | ⬜ | ⬜ |

### Capability summary (stage 4, all three)

`ofs_type=1`, **128 offset registers**, `cnc_rdtofs` types **0–7** all answer
(VT-style T-series interleave expected; type 7 duplicates 6 — panel lock
pending, stage 6). Work offsets `cnc_rdzofs` EXT+G54–G59 + `cnc_rdwkcdshft`
all rc=0 (5 axes of data). `cnc_rdgcode` grp 13 (active WCS) works.
`cnc_rdcommand` returns the full commanded word set (T/S/M/O/N). **Tool-life
group reads answer** (licensed — unlike the mills' magazine option; tables
currently empty). Program-under-execution surface verified on .57:
`cnc_exeprgname(2)`, `cnc_rdprgnum`, `cnc_rdseqnum`, `cnc_rdexecprog` (live
block text), `cnc_pdf_rdmain`. Full sweep cycle ≈ 39 s (.56) / 22 s (.57/.60)
→ `poll_interval_seconds=60`.

---

## 3. Units — stage 7, CLOSED fleet-wide (2026-08-05)

New binding `shared/focas/params.py` (`cnc_rdparam` + `cnc_rdset`, read-only):

- **Setting 0000#2 INI = 1 (inch input)** on all six fleet machines;
- **Param 1013 = all zeros → IS-B** on every configured axis of all six
  (matches dbc00per's panel reading);
- **Param 1001#0 INM = 0 (metric MACHINE system) on all six** — the machines
  are metric-mechanics running inch input. **INM must never be used to pick
  offset units; INI is the offset/display unit.** (First run of the verifier
  used INM and "found" metric everywhere — including the mills whose inch
  panels are operator-verified. That contradiction was the tell.)
- Derived: **0.0001 inch/count everywhere** == `DEFAULT_OFFSET_INCREMENT`.

Artifact: `reports/fleet-unit-verify-20260805.json`. Corroboration: `G20` in
the live program (O9034 on .57); r_geom raws 312/310 → 1/32", 156 → 1/64"
standard inch nose radii.

Follow-up (spec-offset-units slice 3, unchanged): `shared.machine.offset_unit`
column + connect-time refuse-on-mismatch using `read_increment_system()`.

---

## 4. Open work (in order)

1. **Stage 6 — panel cross-check** (dbc00per at each panel with the printed
   sheet). Locks each machine's bank map; do NOT inherit the VT map without
   this, per docs/11 §8 ("never copy another machine's map").
2. **Stage 5 — active tool / turret position source.** `cnc_rdcommand` full
   T word is the VT-proven candidate (already answers on all three); verify
   two-point at the panel like the VT (T0808 vs T1224 test). Zero PMC.
3. **PATH 2 discovery (Lathes 7/8 only — TT controls).** Everything read so
   far is the DEFAULT PATH. The sub-spindle path needs `cnc_setpath`
   discovery: its own offset table? its own program/T word? Nothing in
   `lathe.py`/`service.py` models multi-path today (docs/11 L-O7). Blocks
   nothing for main-path onboarding but must be answered before "the machine
   is mirrored" can be claimed honestly.
4. **Stages 8–9** — add three `start poller-…` blocks to `scripts/dev_stack.sh`
   (`--profile lathe`, UUIDs in §1, `--interval-seconds 60`), soak, then
   `enabled=true` + `status_poll_interval_seconds=10` if the fast tier is
   wanted from day one.
5. Tool-life reads are licensed here (unlike the mills) — decide whether the
   lathe profile should read them once tables are populated (docs/11 L-O8).

## 5. Registry row values used (stage 0)

`machine_class='lathe'`, `pot_count=24`, `offset_register_count=128`,
`atc_strategy='sequential'`, `poll_interval_seconds=60`,
`status_poll_interval_seconds=NULL`, probe fields NULL, `enabled=FALSE`,
`control_model='FANUC 0i-TF Plus'`. Inserted by hand-SQL (the create API
cannot set `machine_class` — known gap, same as VT_23).
