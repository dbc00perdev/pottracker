# 13 — Pot Map UI (LOCKED visual + layout)

> **Status: LOCKED** (dbc00per, 2026-07-27).  
> **Canonical visual:** `docs/mockups/potmap-current-product.html`  
> **Implementation:** `apps/tooling/web/src/features/machines/`  
>   (`PotMap.tsx`, `ActiveLoadoutTable.tsx`, `ActiveOffsetsPanel.tsx`,  
>   `ToolDetailDrawer.tsx`, `activeLoadout.ts`, `ringLayout.ts`)
>
> Supersedes earlier potmap HTML mockups (deleted) and any “grid first” wording
> in older UI notes. If a future change conflicts with this doc **or** the
> locked HTML, update **both** in the same change — do not leave them diverged.

---

## 1. Purpose

Machine-view **Pot Map** is the operator’s spatial + loadout surface for one mill
(random-access ATC, Viper-class). It answers:

1. What is in the **spindle** (HEAD)?
2. What is **NEXT** (pre-called)?
3. What tools are **on the machine** (not the full shop crib)?
4. What is each pot’s **occupancy honesty** (loaded / empty / unverified / probe)?

It is **not** the global tool library (that is **Tools** nav) and **not** the full
400-register editor (machine **Offsets** tab).

---

## 2. Layout (desktop primary)

```
┌─────────────────────────────────────────────────────────────┐
│ Status chips: Spindle · Next · NEXT@6 · Loaded · …          │
├──────────────────────────┬──────────────────────────────────┤
│                          │  Tabs: [ Active ] [ Offsets ]    │
│   Ring carousel          │                                  │
│   (hub = spindle)        │  Active: on-machine table + search│
│   NEXT pot @ 6 o'clock   │  Offsets: 4 banks, active only   │
│                          │                                  │
│   Legend + short note    │  (hover cross-highlight)         │
└──────────────────────────┴──────────────────────────────────┘
        click pot / row / hub → sticky detail drawer (right)
```

| Region | Content |
|---|---|
| **Chips** | Spindle T#, Next T#, ring orientation cue, loaded count, optional unverified / probe / mode / e-stop |
| **Left** | 24-pot ring + hub + legend |
| **Right** | Mode tabs **Active** \| **Offsets** |
| **Drawer** | Sticky detail for selected T# (Esc / Close / backdrop) |

**Breakpoint:** stack ring above table below ~1100px. Phone remains read-only monitoring (Decision-9); dense loadout is desktop/tablet.

---

## 3. Ring geometry (locked)

| Rule | Value |
|---|---|
| Shape | Circular carousel, one face per pot 1…`pot_count` |
| Order | Pot numbers **ascend clockwise** |
| Orientation | Pot holding **NEXT** sits at **6 o’clock** (bottom center) when that pot is known |
| Fallback | If NEXT pot unknown → pot 1 at **12 o’clock** |
| Hub | **Spindle (HEAD)** — not a pot; dashed ring |
| Vacated pots | Tool in spindle or NEXT is **not** drawn as pot-resident; face `→sp` / `→nx` |
| Neighbor of NEXT | **Not a role** — adjacent pots are ordinary occupancy only |

Implementation: `ringLayout.potPosition(potNumber, potCount, anchorPot)` with
`anchorPot = findNextPotNumber(pots, next_t_number)`.

---

## 4. Color palette (locked — cool, low-orange)

Role colors are **semantic** (status), not decoration. Avoid warm orange competing
between hub and right panel.

| Role | Color intent | Tailwind / CSS cue |
|---|---|---|
| **Spindle / hub** | Cyan | `cyan-300`, slate hub fill |
| **NEXT** | Sky blue | `sky-300` |
| **Loaded** | Emerald | `emerald-300` / dark green fill |
| **Probe** | Violet | `violet-300` / deep violet fill |
| **Empty** | Neutral dashed | `neutral-700` |
| **Vacated** | Neutral dashed + cyan/sky face text | |
| **Unverified (ring)** | Amber (spatial only) | light amber border |
| **NO REC (table)** | Rose | `rose-300` |
| **VERIFY / pending** | Indigo | `indigo-300` |
| **UNVER (table)** | Slate | `slate-300` |
| **✓ verified** | Emerald | |
| **Type tags (EM default)** | Teal | not orange |
| **Offset banks** | GEOM H emerald · WEAR H sky · GEOM D violet · WEAR D teal | |

**Do not** reintroduce orange hub / orange default type tags / amber VERIFY on the
loadout table without an explicit design revisit.

---

## 5. Occupancy states (data → face)

Source: `GET /machines/{id}/pots` (occupancy service) + `GET .../spindle`.

| API `state` | Ring face | Loadout row? |
|---|---|---|
| `loaded` | T# + green face | Yes (unless HEAD/NEXT — listed as SPINDLE/NEXT) |
| `probe` | T# + violet face | Yes (PROBE badge); floats by T#, not fixed pot |
| `unverified` | T# + amber face | Yes (UNVER / NO REC as appropriate) |
| `empty` | `—` | **No** — including ordinal reinit `pot N == T N` with no assignment |

**Axes (never conflate):**

1. **Identity** — PMC pot cell (sticky)  
2. **Presence** — h_geom ≠ 0 via assignment bridge  
3. **Location** — HEAD / NEXT overlay (vacated pot)

See `tasks/lessons.md` occupancy findings; `apps/tooling/api/services/occupancy.py`.

---

## 6. Active loadout (right pane — Active tab)

**Default filter: on machine only.** Full crib / TechDB lives under **Tools**.

Include unique tools that are:

- HEAD (spindle), and/or  
- NEXT, and/or  
- Pot-resident with state ≠ `empty`

Columns:

| Column | Content |
|---|---|
| Where | SPINDLE · NEXT · pot *n* |
| T | Program / pot identity |
| H/N | Offset register when assigned |
| Type | Short type tag |
| Label | Generated description or short_id |
| MFR / EDP | When on file |
| Status | ✓ · VERIFY · NO REC · PROBE · UNVER |

**Search:** client-side over the active set only (T, H/N, type, label, EDP, status).

**Join:** tools with `assigned_machine_id` + assignments for `pending_review`.

---

## 7. Offsets pane (right pane — Offsets tab)

On-machine tools only; columns: Where · T · H/N · GEOM H · WEAR H · GEOM D · WEAR D.  
Full 400-register browser remains the machine **Offsets** tab (`OffsetTable.tsx`).

---

## 8. Interaction (desktop hybrid)

| Input | Behavior |
|---|---|
| **Hover** | Cross-highlight pot ↔ row (and hub if HEAD) |
| **Click** | Sticky **detail drawer**; scroll partner into view |
| **Esc / Close / backdrop** | Dismiss drawer |
| **Tablet later** | No hover; tap = click/drawer; stack layout |

Drawer fields (v1 read-only actions gated): Where, pot, type, GTID, MFR/EDP, shank, status, GEOM H placeholder; Confirm review / Open tool **disabled** until product paths exist.

**No neighbor role. No full-crib table on this page.**

---

## 9. Copy / honesty

- Prefer **T#** on ring faces (machine identity). Show **H/N** in table/detail when assignment exists (target model: N ≠ T possible; today often equal).  
- Stale poll / snapshot must remain visible when data is not live (chip or banner).  
- Empty ordinal: never list as active tool; ring shows `—`.

---

## 10. Implementation map

| Concern | File |
|---|---|
| Shell + ring + chips + tabs | `PotMap.tsx` |
| NEXT @ 6 geometry | `ringLayout.ts` |
| Active set build / filter | `activeLoadout.ts` |
| Active table | `ActiveLoadoutTable.tsx` |
| Offsets pane | `ActiveOffsetsPanel.tsx` |
| Drawer | `ToolDetailDrawer.tsx` |
| Occupancy API | `apps/tooling/api/services/occupancy.py` |
| Visual golden file | `docs/mockups/potmap-current-product.html` |

---

## 11. Explicit non-goals (this surface)

- Full shop crib / all N stations  
- Drag-and-drop pot reassignment  
- Neighbor-of-NEXT as a status  
- FOCAS writes from this page (gated elsewhere)  
- Lathe station map (different machine class — `docs/11`)

---

## 12. Change control

1. Edit **this doc** and **`potmap-current-product.html`** together when visuals change.  
2. Point `docs/05-ui-flows.md` Pot Map section here (do not re-derive grid layout).  
3. Code review: “Does this match §3–§8?” before merge of Pot Map UI PRs.
