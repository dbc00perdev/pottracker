# 02 — Data Model

## Design principles

1. **Tool identity is global.** A tool exists once, regardless of which machine it lives on.
2. **Assignment is relational.** Tool ↔ machine ↔ register ↔ pot is a separate row.
3. **FANUC register state is mirrored, not owned.** The control is the source of truth for the *value* of an offset; the app is the source of truth for *which tool that register represents*.
4. **Soft delete only.** Retired tools, deleted assignments — all preserved with `retired_at` / `deleted_at` timestamps. Audit trail must survive.
5. **Audit everything that changes.** Offset writes, assignment changes, pot moves, tool retirement.

---

## Schemas

| Schema | Purpose |
|---|---|
| `shared` | machines, users, audit log, FOCAS state mirror |
| `tooling` | tool library, assignments, tool types, capabilities |
| `tracker` | existing tracker tables — untouched |

Foreign keys cross schemas only from `tooling` and `tracker` into `shared`. Never `tooling` → `tracker` or vice versa.

---

## Entities

### `shared.machine`

```sql
CREATE TABLE shared.machine (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,                    -- "Viper LG-1000AP", "AG100"
    serial_number   TEXT,
    control_model   TEXT NOT NULL,                            -- "FANUC 30i-B"
    ip_address      INET NOT NULL,
    focas_port      INTEGER NOT NULL DEFAULT 8193,
    pot_count       INTEGER NOT NULL,                         -- 24 (23 + 1 probe)
    probe_pot       INTEGER,                                  -- nullable; pot reserved for probe
    probe_t_number  INTEGER,                                  -- T# the probe macro expects
    offset_register_count INTEGER NOT NULL DEFAULT 400,
    atc_strategy    TEXT NOT NULL CHECK (atc_strategy IN ('random_access', 'sequential')),
    has_tsc         BOOLEAN NOT NULL DEFAULT FALSE,           -- through-spindle-coolant
    has_toolsetter  BOOLEAN NOT NULL DEFAULT FALSE,
    poll_interval_seconds INTEGER NOT NULL DEFAULT 60,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_at      TIMESTAMPTZ
);
```

Initial seeded rows: Viper LG-1000AP @ 10.1.10.58, AG100 (IP TBD, `enabled=false` until verified).

---

### `shared.user`

```sql
CREATE TABLE shared.user (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    email           TEXT,
    role            TEXT NOT NULL CHECK (role IN ('viewer', 'operator', 'setter', 'admin')),
    password_hash   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ,
    disabled_at     TIMESTAMPTZ
);
```

Shared with tracker if tracker has its own user table; reconcile in tracker integration phase.

---

### `shared.audit_log`

```sql
CREATE TABLE shared.audit_log (
    id              BIGSERIAL PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id         UUID REFERENCES shared.user(id),
    machine_id      UUID REFERENCES shared.machine(id),
    event_type      TEXT NOT NULL,                            -- 'offset_write', 'assignment_create', 'pot_move', etc.
    entity_type     TEXT NOT NULL,                            -- 'tool', 'assignment', 'offset_register', 'pot'
    entity_id       TEXT NOT NULL,                            -- ID or composite key as string
    before_value    JSONB,
    after_value     JSONB,
    reason          TEXT,
    success         BOOLEAN NOT NULL,
    error           TEXT
);

CREATE INDEX ix_audit_log_occurred ON shared.audit_log(occurred_at DESC);
CREATE INDEX ix_audit_log_machine ON shared.audit_log(machine_id, occurred_at DESC);
CREATE INDEX ix_audit_log_entity ON shared.audit_log(entity_type, entity_id);
```

Append-only. No updates, no deletes. Retention policy TBD; default keep forever.

---

### `shared.focas_state`

Mirror of FANUC state. Updated by poller. Read by tooling and tracker.

```sql
CREATE TABLE shared.focas_offset_register (
    machine_id      UUID NOT NULL REFERENCES shared.machine(id),
    register_number INTEGER NOT NULL,                         -- 1..400
    register_type   TEXT NOT NULL CHECK (register_type IN ('h_geom', 'h_wear', 'd_geom', 'd_wear')),
    value_mm        NUMERIC(10, 4) NOT NULL,
    last_polled_at  TIMESTAMPTZ NOT NULL,
    last_changed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (machine_id, register_number, register_type)
);

CREATE TABLE shared.focas_pot (
    machine_id      UUID NOT NULL REFERENCES shared.machine(id),
    pot_number      INTEGER NOT NULL,                         -- 1..98
    t_number        INTEGER,                                  -- nullable; null = empty pot
    last_polled_at  TIMESTAMPTZ NOT NULL,
    last_changed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (machine_id, pot_number)
);

CREATE TABLE shared.focas_tool_life (
    machine_id      UUID NOT NULL REFERENCES shared.machine(id),
    t_number        INTEGER NOT NULL,
    life_count      INTEGER,
    life_max        INTEGER,
    status          TEXT,                                     -- 'live', 'expired', 'skipped'
    last_polled_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (machine_id, t_number)
);
```

Note on `register_type`: FANUC 30i-B with mill option uses combinations of geometry and wear for both length (H) and diameter (D). Exact register-number-to-type mapping must be verified per machine. The four-type model above is the standard 30i-M layout. Document the exact mapping in `docs/03-focas-integration.md`.

---

### `tooling.tool_type`

Lookup table of tool categories. Not free-text — this drives UI filters and capability flags.

```sql
CREATE TABLE tooling.tool_type (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            TEXT NOT NULL UNIQUE,                     -- 'em_square', 'em_ball', 'em_corner_radius', 'drill', 'tap', 'reamer', 'face_mill', 'chamfer', 'spot_drill', 'probe', etc.
    display_name    TEXT NOT NULL,                            -- "Square Endmill"
    has_corner_radius BOOLEAN NOT NULL DEFAULT FALSE,
    has_thread_pitch BOOLEAN NOT NULL DEFAULT FALSE,
    has_taper_angle BOOLEAN NOT NULL DEFAULT FALSE,
    is_drilling     BOOLEAN NOT NULL DEFAULT FALSE,           -- affects probing strategy
    notes           TEXT
);
```

Seed data documented in `docs/02a-seed-data.md` (TBD).

---

### `tooling.tool`

The actual tool inventory. Each row = one physical cutter (or master record for a class of identical replacements — flagged via `is_consumable_class`).

```sql
CREATE TABLE tooling.tool (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    short_id            TEXT NOT NULL UNIQUE,                 -- human-readable, e.g. "EM-1/4-4F-CRB-001"
    tool_type_id        UUID NOT NULL REFERENCES tooling.tool_type(id),

    -- geometry
    diameter_mm         NUMERIC(8, 4) NOT NULL,
    diameter_inch       NUMERIC(8, 5),                        -- for human display, optional
    flute_count         INTEGER,
    corner_radius_mm    NUMERIC(8, 4),
    flute_length_mm     NUMERIC(8, 4),
    overall_length_mm   NUMERIC(8, 4),
    shank_diameter_mm   NUMERIC(8, 4),

    -- material
    substrate           TEXT,                                  -- 'carbide', 'hss', 'cobalt', 'cermet'
    coating             TEXT,                                  -- 'tialn', 'altin', 'tin', 'dlc', 'uncoated'

    -- vendor
    vendor              TEXT,
    vendor_part_number  TEXT,
    vendor_url          TEXT,

    -- behavior
    max_doc_mm          NUMERIC(8, 4),                         -- max recommended depth of cut
    max_woc_mm          NUMERIC(8, 4),                         -- max recommended width of cut
    requires_tsc        BOOLEAN NOT NULL DEFAULT FALSE,
    requires_climb      BOOLEAN NOT NULL DEFAULT FALSE,

    -- lifecycle
    is_consumable_class BOOLEAN NOT NULL DEFAULT FALSE,        -- TRUE = tool record represents a class, swappable replacements share offsets
    regrind_count       INTEGER NOT NULL DEFAULT 0,            -- reserved for v2
    notes               TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          UUID REFERENCES shared.user(id),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_at          TIMESTAMPTZ
);

CREATE INDEX ix_tool_type ON tooling.tool(tool_type_id);
CREATE INDEX ix_tool_diameter ON tooling.tool(diameter_mm);
CREATE INDEX ix_tool_short_id ON tooling.tool(short_id);
```

`short_id` is the human-readable handle. Operators see this on labels and in UI. Format suggestion: `<TYPE>-<DIAM>-<FLUTES>-<MATERIAL>-<SEQ>`. Free-form but unique.

---

### `tooling.assignment`

A tool assigned to a specific machine, occupying specific H/D registers.

```sql
CREATE TABLE tooling.assignment (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_id             UUID NOT NULL REFERENCES tooling.tool(id),
    machine_id          UUID NOT NULL REFERENCES shared.machine(id),

    t_number            INTEGER NOT NULL,                      -- 1..98 (excluding probe T#)
    h_register          INTEGER NOT NULL,                      -- 1..400
    d_register          INTEGER,                               -- nullable for tools that don't use D (e.g. drills, taps)

    -- last known FANUC values (denormalized cache, authoritative source is shared.focas_offset_register)
    cached_h_geom_mm    NUMERIC(10, 4),
    cached_h_wear_mm    NUMERIC(10, 4),
    cached_d_geom_mm    NUMERIC(10, 4),
    cached_d_wear_mm    NUMERIC(10, 4),

    -- pending operator confirmation flag
    pending_review      BOOLEAN NOT NULL DEFAULT FALSE,
    pending_reason      TEXT,                                  -- e.g., "offset changed by 0.045mm during last poll"

    -- lifecycle
    assigned_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    assigned_by         UUID REFERENCES shared.user(id),
    last_confirmed_at   TIMESTAMPTZ,
    last_confirmed_by   UUID REFERENCES shared.user(id),
    deleted_at          TIMESTAMPTZ,                           -- soft delete

    UNIQUE (machine_id, t_number) DEFERRABLE INITIALLY DEFERRED,
    UNIQUE (machine_id, h_register) DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_assignment_tool ON tooling.assignment(tool_id);
CREATE INDEX ix_assignment_machine ON tooling.assignment(machine_id);
CREATE INDEX ix_assignment_pending ON tooling.assignment(pending_review) WHERE pending_review = TRUE;
```

Constraints:
- Same tool can be assigned to multiple machines simultaneously (different rows, different machine_id).
- Same tool cannot be assigned twice on the same machine (would conflict on T-number).
- T-number unique per machine; H-register unique per machine.
- `t_number` cannot equal the machine's `probe_t_number`.

---

### `tooling.pot_observation`

What pot the tool is currently sitting in, observed from FOCAS pot table. Random-access ATC means this drifts; track it for visibility but don't enforce.

```sql
CREATE TABLE tooling.pot_observation (
    id              BIGSERIAL PRIMARY KEY,
    machine_id      UUID NOT NULL REFERENCES shared.machine(id),
    t_number        INTEGER NOT NULL,
    pot_number      INTEGER NOT NULL,
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_pot_obs_machine_t ON tooling.pot_observation(machine_id, t_number, observed_at DESC);
```

History table — keep latest N per (machine, t_number) via background prune job, default N=20.

---

### `tooling.offset_write_request`

Write paths require operator confirmation. This table tracks pending and completed writes.

```sql
CREATE TABLE tooling.offset_write_request (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id      UUID NOT NULL REFERENCES shared.machine(id),
    register_number INTEGER NOT NULL,
    register_type   TEXT NOT NULL CHECK (register_type IN ('h_geom', 'h_wear', 'd_geom', 'd_wear')),
    intended_value_mm NUMERIC(10, 4) NOT NULL,
    current_value_mm  NUMERIC(10, 4),                          -- snapshot at request time
    reason          TEXT NOT NULL,
    requested_by    UUID NOT NULL REFERENCES shared.user(id),
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_by    UUID REFERENCES shared.user(id),
    confirmed_at    TIMESTAMPTZ,
    executed_at     TIMESTAMPTZ,
    verified_value_mm NUMERIC(10, 4),                          -- value after read-after-write
    success         BOOLEAN,
    error           TEXT
);

CREATE INDEX ix_owr_pending ON tooling.offset_write_request(machine_id, executed_at) WHERE executed_at IS NULL;
```

State machine:
1. `requested` (just inserted, no `confirmed_at`)
2. `confirmed` (operator clicked confirm in UI, `confirmed_at` set)
3. `executing` (FOCAS write in flight)
4. `executed` (write returned)
5. `verified` (read-after-write matched)
6. `failed` (any error or mismatch)

---

## Relationships diagram

```
shared.machine ─┬── shared.focas_offset_register
                ├── shared.focas_pot
                ├── shared.focas_tool_life
                ├── tooling.assignment ──── tooling.tool ──── tooling.tool_type
                ├── tooling.pot_observation
                └── tooling.offset_write_request

shared.user ────── shared.audit_log
            │
            └──── (referenced by tooling.tool, tooling.assignment, tooling.offset_write_request)
```

---

## Reserved fields for v2

These columns are added to v1 tables to avoid migration churn later:

- `tooling.tool.regrind_count` — tracks regrind cycles
- `tooling.tool.is_consumable_class` — flag for swappable replacement model
- `shared.machine` capability flags — already supports filtering, room to grow

Not yet added but documented as future migrations:

- `tooling.tool_inventory` — quantity on hand, reorder thresholds
- `tooling.regrind_event` — when a tool was reground, by whom, dimension delta
- `tooling.tool_cost` — purchase cost, regrind cost, allocated per-part cost
- `tooling.preset_record` — offline presetter measurement (Zoller/Speroni input)
