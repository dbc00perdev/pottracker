# 05 — UI Flows

## Design ethos

Built for the shop floor, not a desk. Operators wear gloves, glance at the screen, click big targets. Touch-friendly. Fast. Information density secondary to clarity. Color used meaningfully, never decoratively.

Critical actions (offset writes, retirements) require two-stage confirmation with explicit values shown.

---

## Top-level navigation

Single SPA at `/tooling`. Sidebar:

- **Dashboard** — multi-machine health, pending reviews, alerts
- **Tools** — global tool library
- **Machines** — per-machine view (Viper, AG100, ...)
- **Audit** — change log (admin)
- **Settings** — user, role, machine config (admin)

Top bar: current user, current machine selector (sticky), search box (global).

---

## Dashboard

Landing page after login.

Cards:

| Card | Content |
|---|---|
| **Machine status** | Each machine: connection state (green/red), last poll time, current T#, current mode (AUTO/MDI/etc.), alarm count |
| **Pending reviews** | Count + list of assignments with `pending_review=true`, sorted by detected_at desc |
| **Recent writes** | Last 10 offset write requests across all machines, with state |
| **Tool life alerts** | Tools with life > 80% used, sorted by % used desc |

Click on any card item drills into the relevant machine view.

---

## Machine view

Selected machine. Multi-tab.

### Tab: Pot Map

Visual layout of the 24-pot carousel. Each pot:

- Pot number (1–24)
- T-number currently in pot (from FOCAS)
- Tool short_id (from assignment, if any)
- Status badge: ✓ confirmed, ⚠ pending review, ✗ unassigned, 🛠 probe pot

Layout: ring or grid — start with grid for screen real estate. SVG-based for clarity.

Click a pot → side panel with full assignment + offsets + tool life + recent changes.

### Tab: Offset Table

Tabular view of all 400 offset registers.

Columns:
- Register number
- Register type (H_geom / H_wear / D_geom / D_wear)
- Current value (mm and inch toggle)
- Last changed at
- Assigned tool (if any)
- Action button: "Update value" (opens write request flow)

Filters: by type, by "has assignment", by "changed in last 24h".

### Tab: Assignments

List of all active assignments on this machine. Same filters as global tools list, scoped to machine.

Inline actions:
- Confirm pending review
- Retire assignment
- Move to different T# / register (admin/setter only)
- Push offset to machine (operator+ — opens write flow)

### Tab: Tool Life

Tool life data from FOCAS. Read-only view in v1.

### Tab: Alarms

Active alarms from FOCAS. Read-only.

---

## Tools view

### List

Search + filter UI as documented in `04-api.md` `GET /tools`. 

Search box autocompletes on `short_id`, `vendor_part_number`, and free-text on notes.

Filter chips: tool type, diameter range, flute count, substrate, coating, vendor, assigned status.

Sort: short_id, diameter, last used, recently created.

Each row:
- short_id
- compact spec (`1/4" 4F CRB sq EM, TiAlN`)
- assignment badge: "Viper T25 H125 D225" if assigned, "unassigned" otherwise
- vendor + P/N
- actions: assign, edit, retire, duplicate

### Tool detail

- Spec card (geometry, material, vendor)
- Assignments table (current + historical)
- Audit log scoped to this tool
- Notes (markdown)
- Buttons: edit, retire, duplicate, assign

### Tool create / edit

Form-based. Tool type selector first → conditional fields (corner radius only shown if tool type supports it; thread pitch only for taps; etc.).

Validation surfaces inline. `short_id` collision shown immediately.

---

## Assign-to-pot flow

Triggered from: tool detail "assign" button, or pot map "assign tool to this pot" button.

Steps:

1. **Select tool** (or pre-selected if entering from tool view)
2. **Select machine** (or pre-selected if entering from pot map)
3. **Tool capability check** — server validates, shows "✓ compatible" or "✗ this machine lacks TSC, this tool requires TSC" with override option for setter+
4. **Pick T-number** — UI shows next-available T# in the diameter range (e.g., T25 for 1/4" tools), but operator can override
5. **Pick H register** — UI shows next-available H# in the convention range, override allowed
6. **Pick D register** — same, optional for tools without diameter wear
7. **Review screen** — full summary before commit
8. **Submit** → assignment created with `pending_review=true`
9. **Operator next steps card** appears: "Load tool to machine pot. Run probing macro M100 H125. Then confirm here."
10. After probe runs, FOCAS poll catches new offset, UI shows "✓ probe complete — review and confirm" notification
11. Operator clicks confirm → assignment confirmed.

UI never auto-confirms. The probe run + operator-eyeball is the safety gate.

---

## Offset write flow

Triggered from: machine view → offset table → "update value", or tool detail → "push preset offsets to machine".

Steps:

1. **Intent submission** — user enters intended value, reason. UI shows current value alongside.
2. **Validation feedback** — inline. "Value out of plausible range", "Machine in AUTO mode, write blocked", etc.
3. **Submission** → POST `/offsets/write`, returns request_id
4. **Confirmation modal** — full-screen:
   - Machine: Viper LG-1000AP
   - Register: H125 (length geometry)
   - Tool: EM-1/4-4F-CRB-001 (1/4" 4F CRB sq EM)
   - Current value: **63.4998 mm**
   - Intended value: **63.5042 mm**
   - Diff: **+0.0044 mm** (color-coded by magnitude)
   - Reason: "preset offline, length verified at toolsetter"
   - Buttons: **Cancel** | **Confirm Write**
5. Operator clicks Confirm → POST `/offsets/write/{id}/confirm` with the current value as cross-check
6. **Execution feedback**:
   - "Re-reading current value..." → if drift detected, abort with explanation
   - "Writing..." → progress indicator
   - "Verifying..." → progress indicator
   - "✓ Write verified — H125 now reads 63.5042 mm" or "✗ Write failed: [error]"
7. Audit log entry visible in machine view audit tab.

---

## Pending review queue

Persistent UI element (notification badge in top bar + dashboard card).

Each item:
- Tool short_id
- Machine + T# + register
- What changed (e.g., "H_wear changed by +0.012 mm at 14:22")
- Quick actions: ✓ Confirm  |  ⚠ Investigate  |  ✗ Retire assignment

"Confirm" is the common case (operator just probed). "Investigate" parks it for later. "Retire" if the change indicates the tool is broken.

---

## G10 export

From machine view → menu → "Export offsets as G10 program."

Modal:
- Select register types (checkboxes, default all)
- Format: FANUC G10 (only option)
- Download button → downloads `.NC` file
- Copy-to-clipboard button (for paste into machine over DNC if appropriate)

Filename convention: `{machine_short_name}_offsets_{YYYYMMDD_HHMMSS}.NC`

---

## G10 import

Admin/setter only. From machine settings:

1. Upload file
2. Server parses, returns diff vs current state
3. UI renders diff table: for each register, current value vs file value, color-coded
4. Admin reviews, ticks which to apply
5. Each ticked register goes through standard write_request flow (one bulk submission, individual confirmations skipped — single bulk confirmation modal listing all)

Ergonomic shortcut for "I just rebuilt the offset table from scratch externally." Audit-logged the same as individual writes.

---

## Audit view

Admin-only top-level. Other roles see filtered view (their own actions).

Filters: machine, user, event type, entity, date range.

Table view, sortable, exportable as CSV.

---

## Mobile responsiveness

Phone breakpoint: 600px. Tablet: 1024px. Layout adjusts:

- Sidebar collapses to drawer
- Pot map shifts from grid to stacked list
- Offset table allows horizontal scroll, fixed register column
- Confirmation modals are full-screen on mobile

Operator phone is acceptable for read-only monitoring + confirming pending reviews. Offset writes require tablet/desktop in v1 (deliberate friction — small phone screens make value cross-check error-prone).

---

## Color & typography conventions

- Status green: `#16a34a` (confirmed, healthy, connected)
- Status amber: `#d97706` (pending review, warning)
- Status red: `#dc2626` (alarm, write failed, machine unreachable)
- Status grey: `#6b7280` (inactive, retired, disabled)
- Mono font for register numbers, T-numbers, offset values (always)
- Sans-serif for everything else

Diff display: red strikethrough for old, green for new, magnitude shown.

Numeric precision: 4 decimals mm always. Inch fields toggleable, 5 decimals.

---

## Accessibility

- Keyboard nav full coverage
- ARIA labels on all icon buttons
- Color is never the sole indicator — pair with icon and text
- Confirmation dialogs trap focus, escape cancels, enter does nothing (must click)
- Minimum tap target 44x44 px

---

## What v1 deliberately excludes

- Drag-and-drop pot reassignment (looks slick, error-prone with gloves)
- Bulk operations on tools (defer to v2)
- Tool comparison view (defer)
- Reports / analytics (use audit export to spreadsheet)
- Embedded G-code preview (out of scope)
- In-app messaging / notes between operators (use Slack)
