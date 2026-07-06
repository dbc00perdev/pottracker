# tasks/spec-phase-3.md — Tooling schema + minimal FastAPI API

Status: **APPROVED — dbc00per signed off 2026-07-06.** Building.

Decisions locked: **D-A** 0003_tooling_core (alarm→0004+) · **D-B** partial unique indexes
`WHERE deleted_at IS NULL` · **D-C** ADD `shared.machine.probe_h_register` (approved shared-schema
touch) · **D-D** create `offset_write_request` now, schema only · **D-E** SQLAlchemy Core ·
**D-F** mirror-freshness health · **D-G** TCP-probe machine create + override · **D-H** install
`pytest-cov` (approved) · **D-I** passlib+bcrypt · **D-J** `scripts/manage_users.py`.

Branch: `claude/summarize-build-eWINf` (continues Phases 0–2).

---

## 1. Objective & gate criteria (docs/06-phases.md Phase 3)

Tool library exists; CRUD endpoints work; JWT auth wired. **No FOCAS writes** (Phase 6).

Gate:
- `POST /api/tooling/tools` creates, retrieves cleanly.
- Assignment creation enforces all unique constraints + capability + probe-lock.
- Tool capability validation (TSC mismatch rejected).
- OpenAPI auto-generated + manually reviewed.
- Test suite > 80% coverage on the API module.

Session scope note: the **async-poller exit-after-2-3-cycles** bug (lessons.md, deferred
to Phase 3) is a *separate* Phase 3 task. It is **out of scope for this API deliverable** —
the API reads FOCAS state from the `shared.focas_*` mirror the sync soak already populates;
it does not run a live poller. Tracked, not touched here.

---

## 2. Open decisions — need your sign-off before code

These change what I build. Defaults marked **(rec)**.

| # | Decision | Options | Rec |
|---|---|---|---|
| **D-A** | Migration revision id (alarm table was penciled as "0003" in todo.md) | `0003_tooling_core` now, alarm → `0004+` later **/** reserve 0003 for alarm, tooling → `0004` | **0003_tooling_core now** (rec) — tooling is real and landing first; alarm is deferred with no file yet |
| **D-B** | Assignment uniqueness under soft-delete | (a) partial unique **index** `WHERE deleted_at IS NULL` — allows T#/H# reuse after soft-delete, **not** deferrable; (b) `DEFERRABLE` unique **constraint** on all rows — allows atomic register swaps, but soft-deleted rows block reuse | **(a)** (rec). No swap UI until Phase 5; reuse-after-retire is the real Phase 3 need. Revisit deferrable swaps in Phase 5. Data-model doc shows (b) — this is a deliberate deviation |
| **D-C** | Enforce Decision-4 "reject **H50**" | Add `shared.machine.probe_h_register INTEGER` (nullable), seed 50 for Viper, reject `h_register == probe_h_register` **/** hardcode 50 | **Add column** (rec). **This is a `shared.*` schema change** — CLAUDE stop-condition, needs your explicit OK. `probe_t_number` already exists and covers T50; there is no column today for H50, so the rule can't be enforced non-hardcoded without it |
| **D-D** | `tooling.offset_write_request` table | Create now (schema only, **no endpoints**) **/** defer to Phase 6 | **Create now** (rec) — your scope + todo.md both list it in the Phase 3 migration; harmless with no write path; avoids a second migration. (Note: docs/06 lists the *table* under Phase 6 — minor doc drift, flagging it) |
| **D-E** | Data-access layer | SQLAlchemy **Core** + explicit Tables (matches Phase 2 `shared/db.py`) **/** ORM | **Core** (rec) — one paradigm in the repo; UPSERT/soft-delete/joins all expressible; reuse the mirror-vs-migration reconciliation-test pattern |
| **D-F** | `health.focas_connected` with no live poller in the API process | Infer from `shared.focas_*` mirror freshness (`lag = now - max(last_polled_at)`, connected if `lag < 2×poll_interval`) **/** live socket check | **Infer from mirror** (rec). Document that "connected" = mirror is fresh, not a live handle. True live state returns when the poller runs in-process (Phase 4+) |
| **D-G** | `POST /machines` FOCAS reachability check (data model: "rejects if 8193 not reachable") | Plain **TCP connect** probe to `ip:port`, short timeout, `skip_probe=true` override for seed/tests **/** full FOCAS handshake **/** none | **TCP probe + override** (rec). Full handshake needs DLLs + Windows + thread-affinity plumbing — too heavy for Phase 3. TCP connect proves the port is open cross-platform |
| **D-H** | Coverage measurement (>80% gate) | Install `pytest-cov` (or `coverage`) **/** skip automated coverage, spot-check | Needs **one install** — `pytest-cov`. Per your standing rule I will **not** install without approval. Say the word and I add it to `[dev]` + run `--cov=apps.tooling.api` |
| **D-I** | Password hashing | `passlib[bcrypt]` (**already installed**, no new dep) **/** argon2 (needs install) **/** stdlib pbkdf2 | **passlib+bcrypt** (rec) — present, standard, zero new deps |
| **D-J** | Initial-admin bootstrap (password_hash is NOT NULL — can't log in with zero users) | `scripts/manage_users.py` (create / set-password / list) **/** alembic data seed **/** test-only fixture | **manage_users.py** (rec) — operator-runnable, also feeds the seed row; tests create users via DB fixture directly |

---

## 3. Migration `0003_tooling_core` (+ `shared.machine.probe_h_register` per D-C)

Hand-written, same conventions as 0001/0002: explicit `schema=`, `server_default=sa.text("shared.gen_random_uuid()")`,
`Identity` for bigserial, FKs into `shared.*` (guard-allowed). No `op.execute` needed
(schemas already exist). Downgrade drops in reverse dep order.

Tables (columns per docs/02-data-model.md verbatim unless noted):

1. **`tooling.tool_type`** — PK uuid; `code` UNIQUE; capability booleans; `display_name`.
2. **`tooling.tool`** — PK uuid; `short_id` UNIQUE; FK `tool_type_id → tooling.tool_type`;
   FK `created_by → shared.user`; geometry/material/vendor/behavior/lifecycle cols;
   `retired_at` soft-delete; indexes on `tool_type_id`, `diameter_mm`, `short_id`.
3. **`tooling.assignment`** — PK uuid; FK `tool_id → tooling.tool`, `machine_id → shared.machine`,
   `assigned_by`/`last_confirmed_by → shared.user`; `t_number`, `h_register`, nullable
   `d_register`; `cached_*_mm` NUMERIC(10,4); `pending_review`/`pending_reason`;
   lifecycle + `deleted_at`.
   **Uniqueness (D-B):** partial unique indexes
   `uq_assignment_machine_tnum (machine_id, t_number) WHERE deleted_at IS NULL`,
   `uq_assignment_machine_hreg (machine_id, h_register) WHERE deleted_at IS NULL`,
   `uq_assignment_machine_dreg (machine_id, d_register) WHERE deleted_at IS NULL AND d_register IS NOT NULL`.
   CHECK `t_number >= 1`, `h_register >= 1`. Non-unique indexes on `tool_id`, `machine_id`,
   partial on `pending_review`.
4. **`tooling.pot_observation`** — bigserial Identity PK; FK `machine_id → shared.machine`;
   `t_number`, `pot_number`, `observed_at`; index `(machine_id, t_number, observed_at DESC)`.
5. **`tooling.offset_write_request`** (D-D, schema only) — per data-model; FKs to
   `shared.machine` + `shared.user`; CHECK `register_type IN (...)`; partial pending index.

Schema change (D-C): `ALTER shared.machine ADD COLUMN probe_h_register INTEGER` (nullable),
via `op.add_column(..., schema="shared")`. Guard-allowed (shared). Seed Viper's value to 50.

App-side Core Tables mirroring this migration:
- `shared.machine` + `shared.user` → **add to `shared/db.py`** (shared schema; API needs them for auth + machine/assignment joins; currently absent there).
- `tooling.*` → **new `apps/tooling/api/tables.py`** (API-owned).
- Reconciliation test (`alembic upgrade head` → reflect → assert column parity) covering both
  shared and tooling — also closes the pending Phase 2 drift-guard task.

---

## 4. API module layout (each file < 400 LOC)

```
apps/tooling/api/
  __init__.py
  main.py            # create_app(): app factory, router include, exception handlers, /openapi
  config.py          # Settings from env: DATABASE_URL, JWT_SECRET, JWT_ACCESS_TTL, JWT_REFRESH_TTL, LOG_LEVEL
  db.py              # sync Engine + Session; get_session() FastAPI dependency (per-request tx)
  security.py        # passlib CryptContext (bcrypt); JWT encode/decode (jose, HS256, ver claim)
  deps.py            # get_current_user, require_role(min_role), role hierarchy
  errors.py          # RFC7807 problem+json handlers (validation, http, integrity, domain)
  tables.py          # tooling.* Core Table defs (mirror migration 0003)
  schemas/           # Pydantic v2 request/response models, one file per domain
    __init__.py  common.py  auth.py  tool.py  tool_type.py  assignment.py  machine.py  audit.py
  routers/           # one router per domain, thin — validation/query in services
    __init__.py  health.py  auth.py  tools.py  tool_types.py  assignments.py  machines.py  audit.py
  services/          # DB query + business rules (Core selects/inserts/updates), one per domain
    __init__.py  tools.py  tool_types.py  assignments.py  machines.py  audit.py  users.py
```

Split routers ↔ services so no file approaches the cap. Audit writes reuse
`shared.audit.record_audit` (already exists).

---

## 5. Auth (Decision-7: standalone, no tracker integration)

- **Roles** (existing `shared.user` CHECK): `viewer < operator < setter < admin`. `require_role`
  does *minimum-role* checks against this order.
- **Hashing:** passlib `CryptContext(schemes=["bcrypt"])`.
- **JWT:** jose HS256, `JWT_SECRET`. Access (TTL 900s) + refresh (86400s). Claims: `sub` (user id),
  `role`, `username`, `ver` (payload version, R5 mitigation), `exp`, `iat`, `typ` (access/refresh).
- **Endpoints:** `POST /api/tooling/auth/login` (username+password → access+refresh, updates
  `last_login_at`), `POST /api/tooling/auth/refresh`, `GET /api/tooling/auth/me`. Reject
  `disabled_at IS NOT NULL` users.
- **Bootstrap:** `scripts/manage_users.py create|set-password|list` (D-J).

---

## 6. Endpoints (all `/api/tooling/*`, RFC7807 errors, UUID ids, mm/4dp)

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/health` | none | status/version/machines[] — `focas_connected` inferred from mirror freshness (D-F) |
| POST | `/auth/login` `/auth/refresh` | none | JWT issue/rotate |
| GET | `/auth/me` | any | current user |
| GET | `/tools` | any | filters per docs/04 (q, tool_type, diameter range, flute, substrate, coating, requires_tsc, assigned, machine, include_retired, limit/offset); joins active assignments |
| POST | `/tools` | setter+ | 409 on dup `short_id` |
| GET | `/tools/{id}` | any | + assignment history |
| PATCH | `/tools/{id}` | setter+ | audit each change |
| POST | `/tools/{id}/retire` | setter+ | 409 if active assignments unless `force=true`+admin+reason |
| POST | `/tools/{id}/duplicate` | setter+ | new `short_id` from caller |
| GET/POST | `/tool-types` | any / admin | |
| GET | `/assignments` | any | filters: machine_id, pending_review, tool_id, include_deleted; joins tool+machine+cached offsets |
| POST | `/assignments` | setter+ | **validation below** |
| GET | `/assignments/{id}` | any | + current FOCAS mirror state |
| PATCH | `/assignments/{id}` | setter+ | re-confirmation flow (sets pending_review) |
| POST | `/assignments/{id}/confirm` | operator+ | sets last_confirmed_*, clears pending_review |
| DELETE | `/assignments/{id}` | setter+ | soft delete + reason, audit |
| GET | `/machines` | any | + inferred focas state |
| POST | `/machines` | admin | TCP reachability probe (D-G), `skip_probe` override |
| PATCH | `/machines/{id}` | admin | |
| GET | `/machines/{id}/offsets` `/pots` `/tool-life` | any | **read-only** from `shared.focas_*` mirror (thin; supports assignment cached view) |
| GET | `/audit` | admin (all) / others (own actions only) | filters per docs/04 |

**`POST /assignments` validation (order matters):**
1. Tool exists, `retired_at IS NULL`.
2. Machine exists, `enabled=TRUE`.
3. `t_number != machine.probe_t_number` → 422 (Decision-4 / R12; T50 on Viper).
4. `h_register != machine.probe_h_register` → 422 (Decision-4, needs D-C column; H50 on Viper).
5. `t_number` unique among active (`deleted_at IS NULL`) on machine.
6. `h_register` unique among active on machine.
7. `d_register` unique among active on machine if provided.
8. Capability: `tool.requires_tsc AND NOT machine.has_tsc` → 422 (R13-adjacent, TSC mismatch).
9. Success → insert with `pending_review=TRUE`; audit `assignment_create`.

Probe-lock (steps 3–4) gets dedicated tests asserting **422 on T50 and on H50** for the Viper row.

---

## 7. Testing (>80% coverage gate, D-H)

- **Unit (no DB):** security (hash round-trip, wrong-password, JWT encode/decode/expiry/tamper),
  role hierarchy, RFC7807 shaping, config loading, pure validation helpers.
- **Integration (`@pytest.mark.integration`, skip w/o `DATABASE_URL`):** FastAPI `TestClient`
  (httpx, installed) against the live dev DB (localhost:5433, head 0003 after migrate). Per-test
  **transactional rollback** fixture (outer tx + SAVEPOINT, roll back on teardown) so tests don't
  pollute the dev DB. Fixtures seed users (all 4 roles), Viper machine, tool types, tools.
- **Coverage:** `pytest --cov=apps.tooling.api` once `pytest-cov` approved (D-H). Target > 80% on
  the API package.
- Reconciliation test (§3) for schema drift.
- Full suite stays green (currently 247 passing), ruff clean, mypy clean on new files.

---

## 8. Task checklist (maps to tasks/todo.md Phase 3)

1. [ ] Sign-off on §2 decisions (esp. **D-C shared-schema change**, **D-H install**).
2. [ ] Migration `0003_tooling_core` + `shared.machine.probe_h_register`; downgrade; migrate dev DB to 0003.
3. [ ] Extend `shared/db.py` (machine, user); `apps/tooling/api/tables.py` (tooling.*); reconciliation test.
4. [ ] `config.py`, `db.py`, `errors.py`, `security.py`, `deps.py`, `main.py` scaffold.
5. [ ] Auth endpoints + `scripts/manage_users.py` + seed Viper row.
6. [ ] tool-types → tools → assignments (probe-lock!) → machines → audit → health, with services + schemas.
7. [ ] Tests (unit + integration + reconciliation) to > 80%.
8. [ ] Review OpenAPI at `/openapi.json` + `/docs`; manual pass.
9. [ ] Update `tasks/todo.md` Phase 3 checkboxes + Review section; `tasks/lessons.md` if corrected.

## 9. Out of scope (Phase 3)

FOCAS **writes** & `offset_write_request` endpoints (Phase 6); frontend (Phase 4);
async-poller exit-bug fix; live in-process poller; WebSockets; G10; AG100.

## 10. Risks touched

R1 (shared-schema migration — D-C ALTER, guard-covered, needs your OK), R5 (JWT payload — `ver`
claim), R11 (never surface a mirror value as "current" without its poll timestamp — enforced in
offset/assignment responses), R12 (probe-lock validation — dedicated tests).

---

## 11. Review — outcome (2026-07-06)

**Delivered.** Migration `0003_tooling_core` applied to dev DB (head=0003), downgrade round-trips,
R1 held. FastAPI app: 18 routes under `/api/tooling`, RFC7807 errors, JWT auth, all files < 400 LOC.

**Verification (proof):**
- Full repo suite: **312 passed, 1 skipped** (async-poller skip); ruff clean on all new code.
- API coverage: **94%** on `apps.tooling.api` (gate >80%). 63 API tests.
- Reconciliation drift test green (shared + tooling Core Tables ⟷ migrated DB).
- **Live end-to-end smoke** (real app, real `get_session`, no test overrides, against dev DB):
  login→201; assign T10/H110→201; **assign T50→422 (t_number)**; **assign H50→422 (h_register)**;
  duplicate→409; health→ok. Demo rows cleaned up.

**Deviations from doc, all pre-approved:** partial unique indexes (D-B) instead of DEFERRABLE
constraints; `shared.machine.probe_h_register` added (D-C) — the data model had a T-lock column
but no H-lock column, so Decision-4's H50 rule was previously unenforceable; `offset_write_request`
created schema-only (D-D).

**Not done (tracked):** committed Viper seed row (needs verified `probe_pot`; tests seed
in-transaction); async-poller exit bug (separate task); OpenAPI is auto-generated + spot-reviewed
but a full manual contract review against docs/04 is worth a dedicated pass before Phase 4 builds UI on it.
