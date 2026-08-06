# Spec — VT Fleet Onboarding (4 × VIPER lathes)

**Status**: IN PROGRESS — read-only slice 2026-08-06 (gates 0–4 + 7).
**Owner**: dbc00per. **Gate checklist**: `docs/10-fleet-architecture.md` §7.
**Precedent**: VT_23 zero-to-live (07-29) + Panther slice (`spec-panther-onboarding.md`).

---

## 1. The machines (identity read 2026-08-06, read-only)

| Shop name | Registry name / UUID | IP | Control | Series | Offset regs |
|---|---|---|---|---|---|
| CNC Lathe 1 | **VIPER VT-21** `c275e3d7-f65a-4552-ad20-760bb9b9ea3f` | 10.1.10.51 | FANUC 0i-TD | D6F1 v05.0 | 64 |
| CNC Lathe 2 | **VIPER VT-23A** `552ff411-5bd0-48d3-8547-421017ba7288` | 10.1.10.52 | FANUC 0i-TF | D6G1 v07.0 | 99 |
| CNC Lathe 4 | **VIPER VT-25BL** `d738c0e1-2b70-4ff0-8eab-ce34705ed2fc` | 10.1.10.54 | FANUC 0i-TD | D6F1 v23.0 | 64 |
| CNC Lathe 5 | **VIPER VT-15L** `591bf5ec-af37-48c5-b940-87eb82ea0d5c` | 10.1.10.55 | FANUC 0i Mate-TD | D7F1 v38.0 | 64 |

All four: single-path (`mt_type=T`), 2-axis, **12-station single turret**
(`pot_count=12`), panels per dbc00per 2026-08-06. No sub-spindle / path-2
anywhere in this group.

**RENAME (dbc00per 2026-08-06):** the .52 unit is the same model as the live
CNC Lathe 3, so the pair is now **VT-23A (.52, Lathe 2)** and **VT-23B
(.53, Lathe 3, UUID `6844401d-…` — the row formerly named `VIPER VT_23`)**.
Historical docs/reports that say "VT_23" refer to today's VT-23B.

**New control generation:** D6F1/D7F1 (0i-D family) is older than anything
onboarded so far — capability sweeps are the licensing truth; nothing is
assumed from the F-series machines' sweeps.

## 2. Gate status (docs/10 §7)

| Stage | VT-21 (.51) | VT-23A (.52) | VT-25BL (.54) | VT-15L (.55) |
|---|---|---|---|---|
| 0 Registry draft (`enabled=false`) | ✅ 2026-08-06 | ✅ | ✅ | ✅ |
| 1 Network 8193 | ✅ | ✅ | ✅ | ✅ |
| 2 DLL path | ✅ (same Fwlib runtime) | ✅ | ✅ | ✅ |
| 3 Identity | ✅ (§1) | ✅ | ✅ | ✅ |
| 4 Capability sweep | ✅ clean (448 cells, 0 rejects) | ✅ (693 cells) | ✅ (448) | ✅ (448) — all four: 8 type codes answer, work offsets + WCS modal + `cnc_rdcommand` + **tool-life licensed**, even on 0i-D |
| 5 Active-tool source — **LOCKED: `cnc_rdcommand` full T word** | ✅ 2026-08-06 synced glance (T0808) | ✅ (T0505) | ✅ (T0100 cancel) | ✅ (T0100 cancel) |
| 6 Panel cross-check — **BANK MAP LOCKED** | ✅ 2026-08-06 | ✅ | ✅ | ✅ |
| 7 Unit lock | ✅ INI=inch, 1013 IS-B, 0.0001 (`reports/fleet-unit-verify-20260806.json`, all 10 fleet machines match) | ✅ | ✅ | ✅ |
| 8 Soak | ⬜ | ⬜ | ⬜ | ⬜ |
| 9 Enable | ⬜ | ⬜ | ⬜ | ⬜ |

## 2b. Bank maps — PANEL-LOCKED all four (gate 6, dbc00per 2026-08-06)

Live panel walk via CNC Screen Display viewer against FRESH per-machine
reads (not the morning sweeps — values re-pulled at comparison time). Map on
all four = the VT/Panther T-series interleave (0=Xw 1=Xg 2=Zw 3=Zg 4=Rw
5=Rg 6=tip), independently verified per machine:

- **VT-21**: 17-register table confirmed value-for-value incl. anchors
  WEAR X -0.0310 @ reg 11, GEOM Z 10.8898 @ reg 40 (one presentation typo
  in chat was corrected and re-confirmed against the true read).
- **VT-23A**: 15 registers confirmed; anchors GEOM R 0.0316 @ reg 1,
  GEOM Z 13.7037 @ reg 59, lone GEOM R 0.9040 @ reg 90.
- **VT-25BL**: 12 registers confirmed; anchors GEOM Z 17.5273 @ reg 40,
  13.4378 @ reg 16.
- **VT-15L**: 23 registers confirmed; anchors the wear-R/geom-R pair @
  reg 6, gauge values 7.8740/3.9370 @ regs 35/36, WEAR Z 0.0500 @ reg 17.

## 3. Open work

1. Gate 6: dbc00per verifies the four cross-check sheets (CNC Screen
   Display viewer works on all four — same :8193).
2. Gate 5: synced active-T glance per machine (`cnc_rdcommand` candidate,
   pending sweep confirmation it answers on 0i-D).
3. Gates 8–9: dev_stack poller blocks + soak + enable on a later go.
4. Fleet is now 10 machines — the one-process-per-machine model means 10
   pollers once all soak; the docs/10 §8.2 fleet launcher backlog item
   gets more attractive (not built in this slice).

## 4. Registry values used (stage 0)

`machine_class='lathe'`, `pot_count=12`, `offset_register_count` per §1,
`atc_strategy='sequential'`, `poll_interval_seconds=60`, probe fields NULL,
`enabled=FALSE`. Direct SQL (create-API still can't set machine_class).
