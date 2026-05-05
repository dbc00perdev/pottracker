# 04 — API Surface

## Conventions

- All endpoints under `/api/tooling/*`
- JSON in/out
- Auth: JWT Bearer, scope per role (`viewer`, `operator`, `setter`, `admin`)
- Errors: RFC 7807 `application/problem+json`
- Timestamps: ISO 8601 UTC
- IDs: UUIDv4 strings
- Lengths: millimeters, decimal, 4 places

---

## Tools

### `GET /api/tooling/tools`

List tools. Supports filters and search.

Query parameters:

| Param | Type | Notes |
|---|---|---|
| `q` | string | substring search on `short_id`, `vendor_part_number`, `notes` |
| `tool_type` | string (code) | filter by tool type code |
| `diameter_mm_min` | number | inclusive |
| `diameter_mm_max` | number | inclusive |
| `flute_count` | int | exact |
| `substrate` | string | exact |
| `coating` | string | exact |
| `requires_tsc` | bool | exact |
| `assigned` | bool | true = only tools with active assignment, false = unassigned |
| `assigned_machine_id` | uuid | filter by machine |
| `include_retired` | bool | default false |
| `limit` | int | default 50, max 500 |
| `offset` | int | default 0 |

Response: `200`
```json
{
  "items": [
    {
      "id": "uuid",
      "short_id": "EM-1/4-4F-CRB-001",
      "tool_type": { "code": "em_square", "display_name": "Square Endmill" },
      "diameter_mm": 6.3500,
      "diameter_inch": 0.25000,
      "flute_count": 4,
      "corner_radius_mm": 0.0,
      "substrate": "carbide",
      "coating": "tialn",
      "vendor": "Helical",
      "vendor_part_number": "HEM-Q-040250",
      "requires_tsc": false,
      "assignments": [
        { "machine_id": "uuid", "machine_name": "Viper LG-1000AP", "t_number": 25, "h_register": 125, "d_register": 225 }
      ],
      "retired_at": null
    }
  ],
  "total": 412,
  "limit": 50,
  "offset": 0
}
```

Auth: any authenticated user.

---

### `POST /api/tooling/tools`

Create new tool record.

Body:
```json
{
  "short_id": "EM-1/4-4F-CRB-001",
  "tool_type_id": "uuid",
  "diameter_mm": 6.3500,
  "diameter_inch": 0.25000,
  "flute_count": 4,
  "corner_radius_mm": 0.0,
  "flute_length_mm": 19.05,
  "overall_length_mm": 63.50,
  "shank_diameter_mm": 6.3500,
  "substrate": "carbide",
  "coating": "tialn",
  "vendor": "Helical",
  "vendor_part_number": "HEM-Q-040250",
  "vendor_url": "https://...",
  "max_doc_mm": 6.35,
  "max_woc_mm": 1.27,
  "requires_tsc": false,
  "is_consumable_class": false,
  "notes": "general roughing 1/4 sq EM"
}
```

Response: `201` with full tool record.

Errors:
- `400` validation
- `409` `short_id` not unique

Auth: `setter`, `admin`.

---

### `GET /api/tooling/tools/{id}`

Single tool detail. Includes full assignment history.

Auth: any authenticated user.

---

### `PATCH /api/tooling/tools/{id}`

Update tool record. Audit log entry on every change.

Auth: `setter`, `admin`.

---

### `POST /api/tooling/tools/{id}/retire`

Soft-delete. Sets `retired_at`. If active assignments exist, returns `409` unless `force=true` query param + admin role + reason in body.

Body:
```json
{ "reason": "broken in op 30, replaced with new tool" }
```

Auth: `setter`, `admin`.

---

### `POST /api/tooling/tools/{id}/duplicate`

Create new tool record with same metadata, new `short_id` (caller provides). For "we just bought another one of these" workflow.

Auth: `setter`, `admin`.

---

## Tool types

### `GET /api/tooling/tool-types`

List all tool types. Used for UI dropdowns.

Auth: any authenticated user.

### `POST /api/tooling/tool-types`

Auth: `admin`.

---

## Assignments

### `GET /api/tooling/assignments`

List assignments. Filters:

| Param | Type |
|---|---|
| `machine_id` | uuid |
| `pending_review` | bool |
| `tool_id` | uuid |
| `include_deleted` | bool |

Response includes joined tool + machine + cached offset values.

Auth: any authenticated user.

---

### `POST /api/tooling/assignments`

Create assignment.

Body:
```json
{
  "tool_id": "uuid",
  "machine_id": "uuid",
  "t_number": 25,
  "h_register": 125,
  "d_register": 225
}
```

Validation:
- Tool exists, not retired
- Machine exists, enabled
- T-number not equal to machine's `probe_t_number`
- T-number unique on machine (no active assignment)
- H-register unique on machine
- D-register unique on machine if provided
- Tool capability check (e.g., `requires_tsc=true` and machine `has_tsc=false` → reject)

On success: assignment row created, `pending_review=true` until operator confirms current FOCAS values match expected.

Response: `201` assignment record.

Auth: `setter`, `admin`.

---

### `GET /api/tooling/assignments/{id}`

Single assignment detail with current FOCAS state.

---

### `PATCH /api/tooling/assignments/{id}`

Modify register assignment (move H125 to H130, etc.). Triggers re-confirmation flow.

Auth: `setter`, `admin`.

---

### `POST /api/tooling/assignments/{id}/confirm`

Operator confirms current cached offsets are correct.

Body:
```json
{ "reason": "verified after probe run" }
```

Sets `last_confirmed_at`, `last_confirmed_by`, clears `pending_review`.

Auth: `operator`, `setter`, `admin`.

---

### `DELETE /api/tooling/assignments/{id}`

Soft delete. Audit logged.

Body:
```json
{ "reason": "removing from machine" }
```

Auth: `setter`, `admin`.

---

## Offsets — read

### `GET /api/tooling/machines/{id}/offsets`

Current offset table for a machine. Returns mirror from `shared.focas_offset_register`.

Query params:
- `register_type` filter
- `with_assignment` bool — join with assignment so UI can show "register 125 = T25 = EM-1/4-4F-CRB-001"

Response: array of register rows + optional assignment join.

Auth: any authenticated user.

---

### `GET /api/tooling/machines/{id}/pots`

Current pot table.

Auth: any authenticated user.

---

### `GET /api/tooling/machines/{id}/tool-life`

Current tool life data.

Auth: any authenticated user.

---

## Offsets — write

### `POST /api/tooling/offsets/write`

Submit a write intent. Does NOT execute immediately.

Body:
```json
{
  "machine_id": "uuid",
  "register_number": 125,
  "register_type": "h_geom",
  "intended_value_mm": 63.5042,
  "reason": "preset offline at presetter, length verified"
}
```

Validation:
- Machine reachable
- Register in valid range
- Value plausible
- User has `operator`+ role

Response: `201` write_request record with `state=requested`.

Auth: `operator`, `setter`, `admin`.

---

### `POST /api/tooling/offsets/write/{id}/confirm`

Operator confirms after seeing diff dialog. Triggers FOCAS write.

Body:
```json
{ "acknowledge_current_value_mm": 63.4998 }
```

The `acknowledge_current_value_mm` field forces the UI to round-trip the current value the operator was shown — server rejects if it doesn't match the latest re-read snapshot. Catches stale UIs.

Response:
- `200` with final state (`verified` or `failed` + error message)
- `409` if value drifted, mode locked, machine unreachable

Auth: `operator`, `setter`, `admin`.

---

### `POST /api/tooling/offsets/write/{id}/cancel`

Cancel a pending write before confirmation.

Auth: requestor, `setter`, `admin`.

---

### `GET /api/tooling/offsets/writes`

List recent write requests (for review/audit screen).

Query params: `machine_id`, `state`, `requested_by`, `since` (timestamp).

Auth: any authenticated user.

---

## G10 export / import

### `GET /api/tooling/machines/{id}/g10-export`

Export current offset table as a FANUC G10 program.

Query params:
- `register_types` comma-separated, default `h_geom,h_wear,d_geom,d_wear`
- `format` = `fanuc_g10` (only option v1)

Response: `text/plain` with `.NC` filename.

Auth: any authenticated user.

---

### `POST /api/tooling/machines/{id}/g10-import`

Upload a G10 program for staged review. Does NOT auto-apply.

Body: multipart upload of `.NC` / `.TXT` file.

Response: `200` with parsed diff against current state. Operator must apply via separate write_request flow.

Auth: `setter`, `admin`.

---

## Machines

### `GET /api/tooling/machines`

List machines (joined with FOCAS connection state).

Response includes `focas_state.connected`, `last_polled_at`.

Auth: any authenticated user.

---

### `POST /api/tooling/machines`

Add a machine. Triggers FOCAS connectivity test before insert; rejects if port 8193 not reachable.

Body:
```json
{
  "name": "AG100",
  "control_model": "FANUC 30i-B",
  "ip_address": "10.1.10.59",
  "focas_port": 8193,
  "pot_count": 24,
  "probe_pot": 24,
  "probe_t_number": 99,
  "offset_register_count": 400,
  "atc_strategy": "random_access",
  "has_tsc": false,
  "has_toolsetter": true,
  "poll_interval_seconds": 60
}
```

Auth: `admin`.

---

### `PATCH /api/tooling/machines/{id}`

Modify machine config.

Auth: `admin`.

---

## Audit

### `GET /api/tooling/audit`

Query audit log.

Query params: `machine_id`, `user_id`, `event_type`, `entity_type`, `entity_id`, `since`, `until`, `limit`, `offset`.

Auth: `admin`. Other roles: scoped to their own actions only.

---

## Health

### `GET /api/tooling/health`

```json
{
  "status": "ok",
  "version": "0.1.0",
  "machines": [
    { "id": "uuid", "name": "Viper LG-1000AP", "focas_connected": true, "last_polled_at": "...", "lag_seconds": 12 },
    { "id": "uuid", "name": "AG100", "focas_connected": false, "last_polled_at": null, "lag_seconds": null }
  ]
}
```

Auth: any (used by monitoring).

---

## WebSocket / live updates (optional v1.1)

### `WS /api/tooling/live`

Push events to subscribed clients:
- `assignment.pending_review`
- `offset.changed`
- `pot.changed`
- `write_request.state_changed`
- `machine.connection_changed`

Subscription filters by machine_id.

Optional in v1; if not built, frontend uses 5s polling on relevant endpoints.

---

## Rate limiting

Standard tier rate limits per user (TBD). FOCAS-write endpoints have a stricter floor: max 60 write requests per user per hour, max 10 per minute. Audit log filled regardless.
