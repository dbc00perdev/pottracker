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

## 7. Open decisions (need dbc00per — flagged, not assumed)

| # | Question | Recommended default |
|---|---|---|
| **D1** | Write granularity in v1 | **Single register per confirmed request**, explicit ack each (R6 "no bulk without per-entry ack"). Batches deferred. |
| **D2** | Writable register types in v1 | **`H_GEOM` only** to start (tool length — the presetter's domain, highest value, smallest surface); add `H_WEAR`/`D_GEOM` once the gate is proven. `D_WEAR` never (panel-only). |
| **D3** | Password cadence | **Per write** (CLAUDE.md "every write"), re-auth even if logged in (R18). No session caching. |
| **D4** | `cnc_wrtofs` vs `cnc_wrtofsr` | **`cnc_wrtofs`** (single register, mirrors our `cnc_rdtofs` read path); verify the exact signature + length arg on hardware before trusting (R8, cf. the `cnc_rdmacro` length-vs-sizeof trap). |
| **D5** | Where the first live write happens | Operator-supervised, machine mode-locked, single H_GEOM register, panel cross-check — like the Step-0 / #1-#2 live confirms. Not a soak. |

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

- [ ] PR-1 mode-lockout helper + mock-status tests
- [ ] PR-2 double-wall approval contract + gate-blocks tests (teeth before writes)
- [ ] PR-3 mock-only write surface + full lifecycle through `offset_write_request`
- [ ] PR-4 real `cnc_wrtofs` binding behind the gate + offset math + param-1013 check
- [ ] Docs: API (docs/04 write endpoints), UI flow (docs/05 two-stage confirm),
      operator runbook for write failures/reverts
- [ ] First supervised live write (D5) — read-after-write + panel cross-check
