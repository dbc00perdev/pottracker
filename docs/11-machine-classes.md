# 11 — Machine Classes (mill vs lathe domain)

**Status**: planning / provisional. Product and domain truth for multi-class fleet.
> **STALE MARKER RETIRED 2026-08-05**: this doc's original "no lathe has answered on port 8193 yet" framing is obsolete. The **VIPER VT_23** (shop name **CNC Lathe 3**, 0i-TF, 10.1.10.53) had first FOCAS contact 2026-07-29 and has been **live in production polling** since (`shared/focas/lathe.py` profile, `reports/vt23-*.json`, SESSION_NOTES 07-29/07-30). A second lathe (0i-TF Plus, A02B-0348-B502, 10.1.10.56, 5-axis, 128 offset registers, tool-life licensed) passed a read-only capability sweep 2026-08-05 (`reports/lathe56-capability-sweep-20260805.json`) — not yet registered. Sections below predating this are read against that reality.  
**Related**: `docs/10-fleet-architecture.md` (profiles, onboarding, poller), `docs/02-data-model.md`, `docs/05-ui-flows.md`, `docs/08-glossary.md`, `tasks/spec-focas-calls.md` (mill/Viper only today), `tasks/lessons.md`.

---

## 1. Why this doc exists

The implemented system is a **mill + random ATC** mental model:

- Pot map (identity)
- HEAD / NEXT (location)
- H/D offset banks (geometry/wear)
- Occupancy = assignment + H_GEOM ≠ 0
- Probe lock T50/H50

A shop-wide rollout that is **mostly lathes** will fail if we force that model onto turning centers. This document:

1. Separates **what operators need** by class from **how FOCAS delivers it**.
2. Lists **open questions** that only first-contact hardware can close (same discipline as O1–O8 on the Viper).
3. States what **must not** be reused from the mill path without re-verification.

---

## 2. Class definitions

| Class | Shop meaning | v1 status |
|---|---|---|
| **mill** | Vertical/horizontal machining center; ATC magazine/pots; length/diameter tool offsets | **Implemented** (Viper profile) |
| **lathe** | Turning center; turret and/or gang; typically X/Z (and maybe Y) tool offsets | **Not implemented** — target majority of fleet |
| **mill_turn** | Combined; both magazine and turret semantics possible | Deferred; do not half-build |
| **other** | EDM, grinder, etc. | Status/alarms only until profiled |

`machine_class` is a **product** field. FOCAS profile is separate (`docs/10` §4).

---

## 3. Concept mapping (mill ↔ lathe)

| Concept | Mill (v1) | Lathe (intent) | Shared app idea |
|---|---|---|---|
| Tool identity | `tooling.tool` (GTID) | Same | Global library |
| Program callout | T-number | T-number / station callout (confirm per control) | Assignment row |
| Physical place | Pot in magazine | Turret station (or gang slot) | **Position** (class-specific) |
| In cut | Spindle HEAD (PMC R327 on Viper) | Spindle tool / turret index in cut | **Active tool** |
| Staged | NEXT (R325 on Viper) | May not exist; dual spindle possible | Optional **next** |
| Length-like offset | H geometry / wear | Often **Z** geometry / wear (tool length along Z) | Offset family |
| Radial offset | D geometry / wear | Often **X** geometry / wear | Offset family |
| Presence of a "real" tool | H_GEOM ≠ 0 after presetter | **Likely** non-zero geometry on the station's offset — **must verify** | Presence policy |
| Probe / reserved | probe pot + T/H lock | May be arm probe, tool setter, or none | Per-machine locks |
| Sticky identity hazard | PMC pot cells sticky / reinit | Turret tables may differ completely | Never assume mill stickiness |

**Rule:** rename in the UI for operators ("Station 4", not "Pot 4") even if the API reuses a generic `position_index` internally.

---

## 4. Operator needs by class (day-1 product)

What must be true for the app to earn trust on that class. Not all require FOCAS day one; all require honesty when missing.

### 4.1 Mill (Viper — current bar)

| Need | Source today |
|---|---|
| Which T is in the spindle / next | PMC HEAD/NEXT |
| What identity sits in each pot | PMC D-area BCD |
| Is a pot "really loaded" | Occupancy policy (assignment + H_GEOM) |
| Offset table live values | `cnc_rdtofs*` mirror |
| Presetter vs keypad edit | G31 skip macros + H_GEOM attribution |
| Probe not assignable | `probe_t_number` + `probe_h_register` |
| Freshness | `last_polled_at` / lag badge |

### 4.2 Lathe (target bar — provisional)

| Need | Notes |
|---|---|
| Active tool / station in cut | Critical; FOCAS source TBD per profile |
| Turret / station map (identity) | Critical if multi-station turret |
| Offset table (X/Z geometry + wear at minimum) | Critical; register layout TBD |
| Tool life if control exposes it | High value on production lathes |
| Mode / running / alarm | Same as mill (status) |
| Which library tool is assigned to which station/T | App assignment — same pattern |
| Write path for wear (later) | Same double wall; different registers |
| Dual spindle / sub-spindle | Explicitly out of v1 lathe alpha unless hardware forces it |

**Explicit non-need for lathe alpha:** mill-style pot reinit alarm, mill probe pot UI, G31 mill presetter attribution (unless that lathe actually uses the same macro pattern — unlikely).

---

## 5. Occupancy / location policy (do not share one function forever)

### 5.1 Mill policy (implemented)

See `apps/tooling/api/services/occupancy.py` and lessons:

1. **Identity** — sticky pot cell (may be wrong about presence).
2. **Presence** — H_GEOM via assignment (T ≠ H).
3. **Location** — HEAD/NEXT overlay vacates pots that hold those tools.
4. **Trust** — presetter_verified vs manual_edit on H_GEOM changes.
5. **Unverified** — identity without assignment → never claim loaded.

### 5.2 Lathe policy (not implemented — design constraints)

Until live data exists, only these rules are locked:

| Rule | Statement |
|---|---|
| L1 | Do **not** call mill `classify_pot` on lathe station data. |
| L2 | Presence must be defined from **measured lathe offset families**, not mill H_GEOM alone. |
| L3 | If station identity is sticky or unreliable, degrade to **unverified** rather than invent loaded/empty. |
| L4 | Location (in spindle vs in turret) needs a **lathe-specific** overlay once active-tool source is known. |
| L5 | Policy lives in API layer (`apps/tooling`), not `shared/`, same as mill (schema isolation). |

Likely shape later: `occupancy_mill.py` / `occupancy_lathe.py` or a registry `POLICY_BY_CLASS[machine_class]`.

---

## 6. Tool library implications

Global tools stay global. Class affects **attributes and types**, not identity rules (GTID non-significant — `tasks/spec-tool-numbering.md`).

| Topic | Mill today | Lathe later |
|---|---|---|
| tool_types | endmill, drill, tap, face mill, probe, … | insert geometry, turning/grooving/threading holders, boring bars, … |
| Geometry fields | Ø, flutes, LOC, corner radius, … | IC, nose radius, hand, holder size, projection, … |
| Generated description | mill-oriented `tool_label` | Separate formatter or class-aware branches |
| Assignment | T + H (+ D) per machine | T/station + X/Z (or control-native register numbers) |
| Capability flags | TSC, etc. | Live center, Y-axis, sub-spindle — only when needed |

**Do not** force lathe tools into mill flutes/Ø fields with magic nulls without a deliberate schema pass. Prefer nullable class-specific attributes or typed JSON extension **after** first lathe intake, not before.

Intake: same `import_tools.py` idea; new CSV columns / tool_types when the crib for turning is digitized.

---

## 7. UI routing (class-driven)

| Surface | Mill | Lathe |
|---|---|---|
| Fleet dashboard | Status card | Same card component; class icon/label |
| Machine home | Pot map hero | Turret/station map hero |
| Overlay | Spindle + Next | Spindle (+ sub if capability) |
| Offsets | H/D columns, mm/inch | X/Z (and others when known) |
| Probe | Locked pot/T/H | Hidden or different lock UI |
| Writes | Phase 6 mill | Lathe wear later; same confirmation chrome |

`docs/05-ui-flows.md` remains mill-centric until lathe alpha; then add a parallel flow section rather than overloading mill screens with conditionals everywhere.

---

## 8. FOCAS: what we know vs what we refuse to invent

### 8.1 Known (mill / Viper only)

Authoritative: `tasks/spec-focas-calls.md`.

- Magazine option may be **unlicensed** → PMC reverse-engineering.
- Active T may be **PMC**, not modal.
- Offset type codes may **disagree with FANUC docs**.
- Increment may **not** be 0.001 mm/count.
- `mt_type` for mills is `M` (stripped).

### 8.2 Expected differences on lathes (hypotheses — verify)

These are **not** implementation specs:

| Topic | Hypothesis | Verify by |
|---|---|---|
| `mt_type` | Often `T` or `TT` | `cnc_sysinfo` |
| Magazine APIs | May still be EW_NOOPT; turret may be PMC or different FOCAS option | capability probe |
| Offset memory | Different type codes / axis-oriented banks | `cnc_rdtofsinfo` + panel |
| Active tool | Turret position register / PMC / modal — unknown | snapshot/diff, not value search on a moving machine |
| Tool life | Often important and sometimes better supported | life APIs + panel |
| Presetter | Tool eye / setter macros ≠ mill G31 skip set | operator process + macros |

### 8.3 Hard rule (R9 / lessons)

> Never add a FOCAS function name, PMC address, or type-code map for a lathe (or any new profile) without grepping the SDK header **and** panel cross-check on that machine.

Copy-pasting Viper R327/D105 into a lathe profile is a **critical** defect class (wrong map, wrong tool, scrap risk when writes exist).

---

## 9. Open questions (lathe / multi-class)

Close these on **first lathe FOCAS contact**, the way O1–O8 were closed on Viper. Until closed, lathe remains `enabled=false`.

| ID | Question | Why it blocks |
|---|---|---|
| L-O1 | What is the live active-tool source on the first lathe? | Overlay + location |
| L-O2 | How is the turret/station table exposed (FOCAS option vs PMC vs none)? | Map |
| L-O3 | Encoding of station identity (raw / BCD / word)? | Decode |
| L-O4 | Offset layout: which type codes are X/Z geom/wear? Panel map for ≥1 known tool | Offset table labels |
| L-O5 | Increment (param / empirical)? | Numeric truth |
| L-O6 | Is presence = non-zero geometry valid on this control? | Occupancy policy |
| L-O7 | Dual spindle / sub-spindle present? | Location model |
| L-O8 | Tool setter / probe reserved resources? | Assignment locks |
| L-O9 | Write surface desired for v1 lathe (wear only? none?) | Phase planning |
| L-O10 | Control family / DLL (still FS30i or other)? | Loader path |

Record answers under a new profile section in `tasks/spec-focas-calls.md` (mirror Viper's "Verified … bindings" section).

---

## 10. First-lathe runbook (when hardware appears)

Do **not** start from mill client constants. Run the fleet onboarding pipeline (`docs/10` §7) with this emphasis:

1. **TCP 8193** smoke; leave `enabled=false`.
2. **Identity** dump (`cnc_sysinfo`) — record raw fields before strip.
3. **Status** cycle (`cnc_statinfo`) — mode/running semantics.
4. **Offset layout** (`cnc_rdtofsinfo`) + single-register panel cross-check (pick a station the operator knows).
5. **Active tool**: prefer change-diff over value search if the machine is live (`tasks/lessons.md` PMC rules).
6. **Station map**: try documented magazine/turret calls **only if present in header for that family**; else PMC snapshot/diff; else manual-only capability.
7. **Write nothing.** Reads only until double wall + profile allow-list exist for that class.
8. Capture report JSON + panel photos/notes; draft profile binding; PR review before enable.

Probe script pattern to reuse (read-only):

- `scripts/focas_smoke.py` (extend profile/expect, do not assume Viper).
- Snapshot/diff style probes for PMC (see pot/modal probe history).
- Never target live write entry points.

---

## 11. Assignment model notes

| Topic | Guidance |
|---|---|
| Uniqueness | T-number (or station callout) unique among **active** assignments **per machine** — already mill rule; keep. |
| Offset registers | Mill: H (and D). Lathe: store the control's register numbers explicitly; do not overload `h_register` with "Z register" without a schema decision. |
| Preferred path | When lathe lands, prefer clear columns or a small `assignment_offsets` structure (`axis` / `role` / `register_number`) rather than silent reuse of `h_register` for Z. |
| Cross-machine | Same physical insert body on two machines → R13 warning still applies. |

Schema change is a **migration + API** event at lathe alpha — not a silent reinterpretation of mill columns.

---

## 12. Glossary additions (class terms)

| Term | Meaning here |
|---|---|
| **Station** | Indexed tool position on a lathe turret (or gang); class analogue of pot |
| **Turret map** | UI/grid of station → tool identity (observed) |
| **Position source** | Capability: how tool positions are read (PMC, magazine FOCAS, manual) |
| **Machine class** | Product category: mill / lathe / … |
| **FOCAS profile** | Integration binding pack for a control/OEM |
| **Capability** | Discrete thing the control+app can do (active_tool, offsets, …) |

Promote into `docs/08-glossary.md` when lathe work starts in earnest.

---

## 13. What this changes about v1 work (and what it does not)

### Do now (cheap alignment)

- Design Step-0 poller as multi-machine (`enabled` rows), even if only Viper is enabled.
- Keep OEM constants clearly labeled **Viper / mighty_viper_0i_mf**.
- Avoid new mill-only globals that cannot be profiled later.
- When touching `shared.machine`, prefer additive nullable fields over mill-hardcoded checks.

### Do not do now

- Build TurretMap UI.
- Add lathe tool_types "for completeness."
- Bind guessed lathe FOCAS functions.
- Generalize occupancy until a second class has live data.
- Delay Viper write path planning on lathe unknowns — mill Phase 6 stays mill-scoped.

---

## 14. Success criteria for "lathe class supported"

Minimum for calling lathe more than a placeholder:

1. At least one lathe profile with live panel cross-check (L-O1–L-O6 closed).
2. Onboarding artifacts stored; `enabled=true` only after soak.
3. UI shows station map or an honest "positions unavailable" state — never a fake pot map.
4. Offset table uses lathe vocabulary and verified type map.
5. Occupancy policy is lathe-specific or explicitly "identity only."
6. Writes (if any) pass the global double wall and profile allow-list tests.
7. Mill Viper regression still green (same suite + live smoke as needed).

---

## 15. Document maintenance

- Close L-O* items in place with date + machine name + report path (lessons style).
- When lathe alpha ships, add `tasks/spec-lathe-profile-<name>.md` or a section under `spec-focas-calls.md` and link here.
- If a mill that is **not** Mighty Viper appears, add a second **mill** profile — class stays `mill`, profile changes (F1).
