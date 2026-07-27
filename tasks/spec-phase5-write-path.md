# spec-phase5-write-path — FOCAS offset write path (HARD GATE)

> Status: **DRAFT for dbc00per review — NO code until sign-off.** This is the
> plan-node artifact for the highest-consequence work in the system (R6, R12, R24).
> Producing the plan does not authorize building it. Every write path change is
> confirm-gated and requires dbc00per sign-off before merge (CLAUDE.md Stop
> Conditions).

Grounding verified this session:
- **Write functions exist in `Fwlib64.h`** (R9 satisfied): `cnc_wrtofs`,
  `cnc_wrtofsr`, `cnc_wrtofsdrctinp`, `cnc_wrtofsms`, `cnc_wrmacror2`. Mode/state:
  `cnc_statinfo`, `cnc_rdopmode`; increment: `cnc_rdparam` (param 1013).
- **`tooling.offset_write_request` already models the lifecycle** (migration 0003,
  schema-only): `register_number/register_type/intended_value_mm/current_value_mm/
  reason/requested_by/requested_at/confirmed_by/confirmed_at/executed_at/
  verified_value_mm/success/error`. The two-stage flow is a table waiting for a path.

---

## 1. Goal / scope

Let an operator push a *reviewed* offset value to a FANUC register — safely, on a
machine that is not live, behind the double wall, with read-after-write proof and
a full audit trail. This is the first time this system writes to a control.

**In (v1, Viper mill only):**
- Offset writes only (`H_GEOM` tool length + optionally `H_WEAR`/`D_GEOM` — see D2).
- The full gate: mode lockout + double wall + drift abort + read-after-write.
- Mock-only write surface first; the real `cnc_wrtofs` binding lands LAST.
- Staging via `offset_write_request` (request → confirm → execute → verify).

**Out:**
- Parameter / macro / pot writes; G10 apply (staged only, docs/02); bulk/multi-machine
  writes; lathe register families (docs/11 profile-scoped, R8-fleet).
- `D_WEAR` writes — structurally unreadable/unwritable via FOCAS on this control
  (lessons.md), so it stays **panel-only**; the path must refuse it.
- Any write from a test / script / soak / harness against the real machine — **mock only**.

## 2. The HARD GATE (encoded from CLAUDE.md)

No write executes unless **ALL** hold, checked in this order, fail-closed:

1. **Mode lockout (precondition).** The machine is verified **NOT running and NOT
   in AUTO** via `cnc_statinfo` (+ `cnc_rdopmode`). If this fails the write is not
   even offered. Re-checked immediately before execute (state can change).
2. **The ask.** An explicit write-approval request is shown and dbc00per
   affirmatively grants it — a deliberate acknowledgement, never a default/auto-yes.
3. **The entry.** dbc00per keys the gated password `WRITE_APPROVAL_PASSWORD`
   (`.env` only — never hardcoded, never committed, rule 6) and it is verified.

Neither wall alone suffices: the ask without the entry blocks; the entry without
the ask blocks. Both, every single write. Plus, before the actual write:

4. **Pre-write re-read + drift abort (R14).** Re-read the live register; if it no
   longer matches `current_value_mm` captured at request time, **abort** — someone
   else moved it.
5. **Plausibility bound (R6).** Value within the configured range for that register
   type; a diff > **0.5 mm** vs the prior value is flagged for explicit operator
   confirmation, never silent (lessons.md / offset rules).
6. **Read-after-write verification (mandatory).** Read the register back; if it
   doesn't equal the intended value, mark the request failed + alarm. Store
   `verified_value_mm`.

Every attempt (success or block) writes an `audit_log` row:
`(timestamp, machine_id, register, old_value, new_value, user_id, reason)`.

## 3. First-PR order (LOCKED — policy before capability)

Build in this sequence; **`cnc_wrtofs` is bound LAST, behind the gate** — never first:

1. **PR-1 — mode-lockout helper + tests.** `is_write_locked_out(machine)` reads
   `cnc_statinfo`/`cnc_rdopmode`, returns "safe to offer write" only when not
   running / not AUTO. Pure-ish; unit-tested against the mock's status scenarios.
2. **PR-2 — double-wall approval contract + BLOCKING tests.** The API/service
   contract that verifies (a) an explicit approval flag on the request and (b) the
   `WRITE_APPROVAL_PASSWORD`. Tests **prove a write is refused** unless mode-lockout
   AND both walls hold — the gate has teeth before any write exists.
3. **PR-3 — mock-only write surface.** Extend `tooling/focas/mock.py` with a
   labeled `write_offset()` that records intended writes + simulates read-after-write.
   The whole request→confirm→execute→verify lifecycle runs end-to-end against the
   mock, exercising drift-abort + plausibility + verification — zero real hardware.
4. **PR-4 — real `cnc_wrtofs` binding (behind the gate).** Bind the write in
   `shared/focas/client.py` (grandfathered — split per LOC rule when touched).
   Offset math at the FOCAS boundary only. Gated behind PR-1/PR-2; the mock path
   (PR-3) is the default in every non-production context. First live write is an
   operator-supervised, mode-locked, single-register test with panel cross-check.

## 4. Offset math (from lessons.md — verified on Viper, non-negotiable)

- **Metric internal (mm); convert only at the FOCAS boundary**, never in business
  logic.
- **Increment 0.0001 mm/count** (panel-verified; NOT 0.001). Read **param 1013**
  via `cnc_rdparam` at write time and **refuse the write if the live increment
  disagrees** with the assumed value (closes the 10× hazard for a second control).
- **Type-code map (empirically locked on this 0i-MF, Memory-B):**
  `type=1=D_GEOM, type=2=H_WEAR, type=3=H_GEOM, type=4=D_WEAR`. Writable:
  `H_GEOM`(3), `H_WEAR`(2), `D_GEOM`(1). **`D_WEAR`(4) refused — panel-only.**
- **Wear and geometry are separate registers — never conflate** (rule).
- Diff > 0.5 mm vs prior → operator confirmation, never silent.

## 5. Guards that must compose (map to risks)

| Guard | Mechanism | Risk |
|---|---|---|
| No write to the probe | reject `t/h == probe_t_number/probe_h_register` (already enforced on assignment; re-enforce on write) | R12 |
| Mode lockout | `cnc_statinfo` not-running/not-AUTO, re-checked pre-execute | R6 |
| Drift abort | pre-write re-read vs `current_value_mm` | R14 |
| Plausibility | per-register-type range + 0.5 mm flag | R6 |
| Read-after-write | mandatory verify → `verified_value_mm` | R6 |
| Double wall | ask + `WRITE_APPROVAL_PASSWORD` | R24 |
| Reason quality | required, min length, for-the-next-person | R20 |
| Audit | every attempt, success or block | R6/R24 |

## 6. Test strategy

- **Mock-only, always.** No test/script/soak/harness targets the real machine's
  write functions (anti-pattern #3/#10). `tooling/focas/mock.py` is the only write
  surface under test.
- **The gate-blocks test is the centerpiece** (required by CLAUDE.md for any write
  PR): a matrix proving the write is refused when mode-lockout fails, when the ask
  is absent, when the password is wrong, when the probe is targeted, when drift is
  detected, when the value is implausible — and permitted only when *all* pass.
- Offset-math unit tests (increment, type-code map, mm↔count round-trip, D_WEAR
  refusal, 0.5 mm flag).
- Lifecycle integration test against the dev DB: `offset_write_request` transitions
  request → confirm → execute(mock) → verify, audit rows correct.

## 7. Open decisions

Recommended defaults were the starting point; **D1 and D5 are now DECIDED by
dbc00per (2026-07-10, pm-4)**. D2–D4 remain at their recommended defaults pending
explicit confirmation.

| # | Question | Decision |
|---|---|---|
| **D1** | Write granularity in v1 | **DECIDED — batch allowed: one confirmation (single ask + single password entry) may cover multiple registers.** Reconciled with R6 / anti-pattern #10 ("no bulk without per-entry ack"): the **double wall is per-batch, but each register in the batch retains an explicit per-entry acknowledgment** (operator sees + acks each value individually before the shared ask+entry). The password is not re-keyed per register within a confirmed batch — that is the intended speed-up for post-probe bulk confirms. Drift abort (R14) is evaluated per register at execute time; any drifted register in the batch aborts that register, not the whole batch. |
| **D2** | Writable register types in v1 | **`H_GEOM` only** to start (tool length — the presetter's domain, highest value, smallest surface); add `H_WEAR`/`D_GEOM` once the gate is proven. `D_WEAR` never (panel-only). *(recommended default — unconfirmed)* |
| **D3** | Password cadence | **Per confirmation** (one entry per ask). With D1 batch, one entry authorizes the confirmed batch; a new batch = a new entry. Re-auth even if logged in (R18). No session caching. *(recommended default, adjusted for D1 batch — unconfirmed)* |
| **D4** | `cnc_wrtofs` vs `cnc_wrtofsr` | **`cnc_wrtofs`** (single register, mirrors our `cnc_rdtofs` read path); a batch is a loop of single-register writes, each read-after-write verified. Verify the exact signature + length arg on hardware before trusting (R8, cf. the `cnc_rdmacro` length-vs-sizeof trap). *(recommended default — unconfirmed)* |
| **D5** | Where the first live write happens | **DECIDED — single supervised H_GEOM register, machine mode-locked, operator supervising, read-after-write + panel cross-check** (like the Step-0 / #1-#2 live confirms). Not a soak, not a batch. A deliberate subset of the D1 capability: the code supports batch, but *first contact* is one register. |

## 8. Risks touched

- **R24** (write path is policy not code) — this spec is its retirement plan; the
  gate becomes code (PR-1/PR-2) before any write (PR-4).
- **R6** (bad write) — mode lockout + plausibility + drift abort + read-after-write.
- **R12** (probe overwrite) — probe-lock re-enforced on the write path.
- **R14** (concurrent writes) — drift abort.
- **R8** (write coverage unproven) — PR-4 verifies the binding against the mock,
  then one supervised live write; param-1013 live-check closes the units hazard.
- **R9** (function names) — `cnc_wrtofs`/`cnc_wrtofsr` confirmed in `Fwlib64.h`.

## 9. Task checklist (PR-by-PR; each gated on dbc00per sign-off)

- [x] **PR-1 mode-lockout helper** — `mode_lockout_ok(status)` (not running + safe
      mode; fail-closed on MEM/AUTO/UNKNOWN) in `apps/tooling/api/services/write_safety.py`.
- [x] **PR-2 double-wall approval contract + gate-blocks tests** — `authorize_write()`
      composes probe-lock (R12) → mode-lockout → ask (`approved`) → entry
      (`verify_write_approval` vs `WRITE_APPROVAL_PASSWORD`, constant-time, fail-closed
      when unset). 22 tests prove refusal on every wall + correct precedence. No
      `cnc_wrtofs`, no live write. (Done 2026-07-10.)
- [x] **PR-3 mock-only write surface + full lifecycle** (done 2026-07-10, mock-only,
      no `cnc_wrtofs`, no live write). `shared/focas/offset_math.py` (pure: verified
      0.0001 mm/count increment, H/D-swapped type-code map, D2 writability with D_WEAR
      never-writable, 0.5 mm flag, param-1013 `verify_increment` hook for PR-4);
      `MockOffsetWriter` in `shared/focas/mock.py` (labeled write surface, round-trips
      + simulates reject / corrupt-readback); `apps/tooling/api/services/offset_write.py`
      (`create_request` → `execute_request` → `execute_batch` composing the PR-2 gate →
      drift abort → plausibility/ack → mock write → read-after-write verify → audit, with
      an injected `OffsetWriteTarget` protocol PR-4 will also implement). Tests: offset-math
      (11) + mock-writer (5) pure units + 8 dev-DB lifecycle (happy/bad-pw/running/drift/
      large-diff-ack/verify-mismatch/probe/D_WEAR). Suite 470 pass, ruff+mypy clean.
      **No HTTP router yet** — endpoints + docs/04/05 are the next slice (deliberately
      not exposing a write endpoint, even mock, until that PR).
- [ ] PR-3b write endpoints (router) + docs/04 write API + docs/05 two-stage confirm UI
- [ ] PR-4 real `cnc_wrtofs` binding behind the gate + offset math + param-1013 check
- [ ] Docs: API (docs/04 write endpoints), UI flow (docs/05 two-stage confirm),
      operator runbook for write failures/reverts
- [ ] First supervised live write (D5) — read-after-write + panel cross-check
