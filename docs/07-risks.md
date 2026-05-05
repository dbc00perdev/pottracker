# 07 — Risk Register

Active risks tracked here. Reviewed at session start. Mitigations described, owners assigned (default: dbc00per).

Severity scale:
- **Critical** — could damage production machinery, scrap parts, or take Lance CNC Tracker down
- **High** — significant rework or operator distrust if it manifests
- **Medium** — annoyance, fixable
- **Low** — cosmetic or edge case

---

## R1 — Tracker coupling: shared schema migration breaks tracker

**Severity**: Critical
**Likelihood**: Medium

If a tooling Alembic migration accidentally targets a tracker table, or modifies a `shared.*` table in a way tracker depends on, tracker breaks.

**Mitigations**:
- Tooling migrations target `tooling.*` schema only — enforced by Alembic env config
- Shared schema migrations require explicit review + tracker regression test pass
- CI: tracker test suite runs against pre-migration and post-migration DB on every PR that touches `shared.*`
- Rollback plan: every migration paired with a documented downgrade

**Detection**:
- Tracker integration test in CI
- Shared schema diff in PR description (must be filled in by author)

**Owner**: dbc00per

---

## R2 — Tracker coupling: shared FOCAS poller crash takes both apps down

**Severity**: Critical
**Likelihood**: Low–Medium

The FOCAS poller is shared infrastructure. If it crashes (memory leak, infinite loop, library bug), both tracker and tooling lose their FANUC data feed.

**Mitigations**:
- Poller runs as a separate process, supervised by Docker (restart on crash)
- Poller does no DB writes outside `shared.focas_*` tables — limits blast radius
- Per-machine async tasks isolated — one machine's failure can't take down others
- Health endpoint reports poller state separately from web workers
- Circuit breaker on FOCAS connection level prevents one machine taking down the poller

**Detection**:
- Health endpoint surfaces lag time per machine
- Monitoring alerts if any machine's `lag_seconds > 300`

**Owner**: dbc00per

---

## R3 — Tracker coupling: dependency bump breaks tracker

**Severity**: High
**Likelihood**: High

Shared dependencies (`fastapi`, `sqlalchemy`, `pydantic`, `pyfocas`) pinned in one project but not the other = drift. Bumping in tooling could break tracker silently.

**Mitigations**:
- Single `requirements.txt` (or `pyproject.toml`) at repo root for shared deps
- Per-app `requirements.txt` only for app-specific deps
- CI runs both tracker and tooling test suites on every PR
- `litellm` and other supply-chain hot-zone packages locked, never bumped without audit (existing CLAUDE.md rule)

**Detection**:
- Tracker test suite must pass before tooling PR merges

**Owner**: dbc00per

---

## R4 — Tracker coupling: nginx route conflict

**Severity**: Medium
**Likelihood**: Low

If tooling routes are added under a path that conflicts with tracker, requests get misrouted.

**Mitigations**:
- Tooling namespaced under `/api/tooling/*` and `/tooling/*`
- nginx config managed in repo, reviewed in PR
- Smoke test: hit a known tracker endpoint after tooling deploy, verify still routes correctly

**Detection**:
- Post-deploy smoke test
- 404 monitoring on production

**Owner**: dbc00per

---

## R5 — Tracker coupling: shared auth changes break tracker login

**Severity**: High
**Likelihood**: Low

If tooling adds a role or modifies the JWT payload in a way tracker doesn't understand, tracker login fails or auth bypasses occur.

**Mitigations**:
- JWT payload version-tagged
- Adding roles is additive — existing roles never modified
- Tracker auth tests run against tooling auth changes

**Detection**:
- CI integration test

**Owner**: dbc00per

---

## R6 — Bad FOCAS write damages production setup

**Severity**: Critical
**Likelihood**: Medium without mitigations, Low with mitigations

App writes wrong value to an offset register. Next part run uses bad offset. Scrap, broken tool, or crashed machine.

**Mitigations**:
- Two-stage UI confirmation
- Pre-write re-read with drift abort
- Read-after-write verification
- Mode lockout (no writes during AUTO running)
- Plausibility validation (value within configurable range per register type)
- Audit log on every write
- No bulk writes without explicit acknowledgment of each entry

**Detection**:
- Operator notices on next probe, files write_request to revert
- Audit log review

**Owner**: dbc00per — reviews every write_request feature change personally

---

## R7 — FOCAS option not actually licensed on AG100

**Severity**: Medium
**Likelihood**: Medium

Assumed FOCAS-live based on the Viper's confirmed configuration, but never tested. AG100 might not have the option bit even though the hardware supports it.

**Mitigations**:
- AG100 onboarding (Phase 8) starts with port test
- AG100 not added to `shared.machine` table until verified
- Architecture supports per-machine enable/disable so AG100 can be deferred without blocking Viper-only operation

**Detection**:
- Phase 8 entry gate

**Owner**: dbc00per

---

## R8 — `pyfocas` library inadequate for write paths

**Severity**: High
**Likelihood**: Medium

Library may not cover all the write functions needed, or may have bugs. Discovered in Phase 6.

**Mitigations**:
- Phase 1 gate verifies write coverage exists before building further
- Fallback plan: direct ctypes wrappers around `Fwlib32.dll`
- Vendored DLL license review queued before commit

**Detection**:
- Phase 1 integration test
- Phase 6 write tests

**Owner**: dbc00per

---

## R9 — FOCAS function name mismatch with 30i-B reality

**Severity**: High
**Likelihood**: Medium

The function names in `docs/03-focas-integration.md` are provisional. 30i-B may have different names than 16/18/21-series. Calls fail at runtime.

**Mitigations**:
- Phase 1 includes verifying every call name against actual FOCAS2 SDK documentation for 30i-B
- All mappings documented in `tasks/spec-focas-calls.md` before implementation
- Fail-fast on unknown function names — log clearly, don't silently degrade

**Detection**:
- Phase 1 integration test

**Owner**: dbc00per

---

## R10 — Random-access ATC pot tracking drift

**Severity**: Medium
**Likelihood**: High (this is the design assumption, not a fluke)

Pots reorder during operation. App's "expected pot" shows stale info. Operator gets confused.

**Mitigations**:
- App treats pot as observed state, not commanded state
- UI shows current pot from FOCAS, not assumed pot
- Pot observations tracked over time for visibility, not enforcement
- "Where is T125 right now" answered by FOCAS read, not app DB

**Detection**:
- UI shows divergence as informational, not error

**Owner**: dbc00per

---

## R11 — Operator distrust if app and machine disagree

**Severity**: High
**Likelihood**: High in early operation

If operator sees app value vs machine value mismatch, they stop trusting the app. Once trust is lost, adoption fails.

**Mitigations**:
- Pending-review flag is visible, never hidden
- Diffs shown explicitly with timestamps
- Audit log accessible to operators
- Operator training emphasizes: machine is always authoritative for current value, app is authoritative for identity
- UI never claims an offset value as "current" without sourcing it from a recent FOCAS poll

**Detection**:
- Operator feedback during Phase 10 shadow operation
- Adoption metric: % of assignments confirmed within 1 hour of probe completion

**Owner**: dbc00per

---

## R12 — Probe pot configuration error causes write to active probe

**Severity**: Critical
**Likelihood**: Low

If the probe pot is misconfigured in `shared.machine.probe_pot` / `probe_t_number`, an assignment could overwrite probe offsets, breaking probing on the machine.

**Mitigations**:
- Probe pot fields validated at machine config time
- API explicitly rejects assignments where `t_number == probe_t_number`
- Probe pot UI shown distinctly with lock icon
- Admin can change probe config but UI requires explicit confirmation + reason

**Detection**:
- Validation tests
- Pre-deploy smoke test on probe macro after any probe-related config change

**Owner**: dbc00per

---

## R13 — Multi-tenant assumption violated (tool on two machines)

**Severity**: Medium
**Likelihood**: Medium

Operator assigns the same physical tool to Viper and AG100 simultaneously, forgetting it's one cutter. Both machines try to use it. Crash on one.

**Mitigations**:
- UI warns when assigning tool already assigned elsewhere (`is_consumable_class=false` only)
- Warning requires explicit override
- Audit log records the override
- For consumable-class tools, multiple assignments are expected and silently allowed

**Detection**:
- UI warning at assignment time
- Admin review of audit log

**Owner**: dbc00per

---

## R14 — Concurrent write requests on same register race

**Severity**: Medium
**Likelihood**: Low

Two operators submit write requests on H125 within seconds of each other. First completes, second's pre-write re-read catches the drift, aborts. UX is "your write was rejected because someone else just wrote." Confusing but safe.

**Mitigations**:
- Drift abort is the safety net
- UI shows recent writes on register so operator can see why their request was rejected
- Activity feed in UI shows in-flight writes

**Detection**:
- Audit log shows pattern of aborts on same register

**Owner**: dbc00per

---

## R15 — Database backup includes inconsistent state during poll

**Severity**: Low
**Likelihood**: Medium

PG backup runs while poller is mid-write. Backup captures partial state.

**Mitigations**:
- PG dumps are point-in-time consistent (transaction-level)
- Poller updates atomic per-cycle (single transaction per machine per poll)
- Acceptable to back up snapshot of mirror tables — they re-converge on next poll if restored

**Detection**:
- Restore drill once per quarter

**Owner**: dbc00per

---

## R16 — Single host failure takes down both apps

**Severity**: High
**Likelihood**: Low

Host running both tracker and tooling crashes. Both unavailable.

**Mitigations**:
- Existing tracker deployment already has this risk — not introduced by tooling
- Manual paper / spreadsheet fallback for offset records (operators have machine printouts)
- Daily DB backup, restore documented
- Future: HA setup with replica, deferred to v2

**Detection**:
- Monitoring uptime check

**Owner**: dbc00per

---

## R17 — Audit log grows unbounded

**Severity**: Low
**Likelihood**: High over time

Every poll cycle that detects a change writes audit entries. Over years, the table is huge.

**Mitigations**:
- Indexes designed for time-bounded queries
- Retention policy decision deferred to v2 — for now, keep all
- Hot-cold partitioning available if needed

**Detection**:
- Quarterly DB size review

**Owner**: dbc00per

---

## R18 — User account for "Operator" shared across people

**Severity**: Medium
**Likelihood**: High in shop-floor context

Shop floor reality: one operator account gets shared across the shift. Audit log shows the shared account did everything, not the actual person.

**Mitigations**:
- Per-person accounts mandated in Phase 10 training
- Cheap accounts: anyone can have one, no license cost
- UI password prompt at every offset write (re-auth) — even if logged in, prove identity for the high-stakes action

**Detection**:
- Audit log review

**Owner**: dbc00per

---

## R19 — Network partition between app host and FANUC

**Severity**: Medium
**Likelihood**: Low

Shop network outage isolates app from controls. Reads stop. Writes fail.

**Mitigations**:
- Circuit breaker handles transient failures gracefully
- UI clearly indicates "machine unreachable" state
- Operators continue with paper/manual workflow during outage
- App resumes on reconnection, audit log captures the gap

**Detection**:
- Health endpoint, monitoring

**Owner**: dbc00per

---

## R20 — Operator submits write with wrong reason / bypasses intent

**Severity**: Low (each event); High (cultural drift)
**Likelihood**: Medium

Operators copy-paste reason field, click through confirmations, defeat the safety design.

**Mitigations**:
- Reason field has minimum length, free-text but required
- Periodic admin review of reason field quality
- Training emphasizes the reason is for the next person, not for compliance theater
- For repetitive operations (post-probe confirms), make reason optional but provide structured templates

**Detection**:
- Admin review
- Pattern detection on identical reason strings

**Owner**: dbc00per

---

## Risks not tracked (out of scope or accepted)

- Hardware failure on FANUC controls (not our problem)
- Power outage taking down host (existing risk for tracker, accepted)
- Operator physically loading wrong tool to pot (mitigated by labeling, scope of v1 is software side)
- Tool wear during runtime (handled by FANUC tool life, mirrored read-only in v1)
