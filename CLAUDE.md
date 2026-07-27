# CLAUDE.md — lance-tooling

> Operating directives for Claude Code CLI on the Lance tooling project.
> Read `tasks/lessons.md` and `docs/07-risks.md` at session start.
> Follow rules below without prompting.

---

## Project-Specific Reality Check

This system **writes to FANUC offset tables on production CNC machines.** A bad write = scrap, broken tools, or a crash. Every rule below exists to keep that from happening.

This is not a side project. It runs on the floor next to Lance CNC Tracker. Breaking tracker = breaking production scheduling. Breaking offsets = breaking parts.

---

## Core Principles

- **Simplicity First**: Minimal diff. Touch only what's necessary.
- **No Laziness**: Root causes only. No band-aids, no temp fixes.
- **Senior Bar**: Every change must pass a staff engineer review.
- **File Size Discipline**: No source file or logical section exceeds **400 LOC**. As a file approaches the cap, split it into cohesive modules along natural seams (pure logic vs. I/O, one domain per module) to keep context small and prevent bloat as the codebase grows. Split for cohesion, not just to hit a number — don't fragment tightly-coupled code or create premature abstractions. Existing over-cap files (e.g. `shared/focas/client.py`) are grandfathered; split them when next touched substantively, not preemptively.
- **Brevity**: Terse, technical, no preamble. No "Great question!" No emoji unless dbc00per uses them first.
- **Honesty**: If an approach is bad, say so. If you don't know, say so. Never fabricate.
- **Safety Default**: When in doubt about a write to FANUC, prompt the user. Never assume consent.

---

## Stack Context

- **Shell**: Git Bash on Windows. All commands in Git Bash syntax.
- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, `pyfocas` or Fanuc FOCAS2 DLL wrapper.
- **DB**: PostgreSQL. **Two physically separate databases on one native Postgres server** — `pottracker_db` (schemas `tooling.*` + `shared.*`) and the tracker's `tracker_db`, never commingled (Decision-10, `docs/12-database-topology.md`). `tooling.*` and `shared.*` are one indivisible unit (internal FKs); the wall is between `pottracker_db` and `tracker_db`. Any future tracker read goes via `postgres_fdw` over named views, never a merged DB.
- **Frontend**: React 18+, Vite, TypeScript, Tailwind.
- **Infra**: Docker Compose, single nginx, runs on the same box as tracker.
- **GPU**: Not required for this project. No local LLM inference in v1.
- **Editor flow**: Claude Code CLI > browser. Single-file HTML artifacts inappropriate here — this is a multi-module FastAPI + React app.

---

## Workflow Orchestration

### 1. Plan Node — Triggers
Enter plan mode when ANY of these are true:
- 3+ steps, 2+ files touched, or any new dependency
- Architectural decision (schema, API contract, auth, FOCAS poll cadence, sync state machine)
- **Anything touching FOCAS write paths, offset math, pot table updates, or tool-life logic**
- Anything that could affect Lance CNC Tracker (shared schema, shared auth, shared FOCAS poller, shared nginx config)
- Verification/audit tasks

If something goes sideways: **STOP, re-plan, don't push through.**
Specs go in `tasks/spec-<feature>.md`.

### 2. Subagent Strategy
- Use subagents liberally — keep main context clean
- Offload: FOCAS protocol research, Fanuc parameter lookups, parallel file analysis, exploratory reads, test runs
- One concrete task per subagent
- Complex problem → more subagents, not more tokens in main thread

### 3. Self-Improvement Loop
After ANY user correction:
1. Append pattern + rule to `tasks/lessons.md`
2. Format: `**Mistake**: ... → **Rule**: ...`
3. Review `tasks/lessons.md` at session start
4. If a lesson repeats, harden the rule until it stops

### 4. Verification Before Done
- Never mark complete without proof (test output, log, screenshot, diff, FOCAS read confirming write took effect)
- For FOCAS writes: read-after-write verification mandatory
- Run tests. Check logs. Demonstrate correctness inline.
- Self-check: *"Would a staff engineer approve this PR? Would I run this on the Viper Monday morning?"* If no, fix before presenting.

### 5. Demand Elegance (Balanced)
- Non-trivial change → pause: *"Is there a more elegant way?"*
- Hacky fix → *"Knowing what I know now, what's the clean version?"* — implement that instead
- Skip elegance pass for obvious one-liners. Don't gold-plate.
- Challenge own work before presenting.

### 6. Autonomous Bug Fixing
- Bug report → fix it. No clarifying questions unless blocking.
- **Exception**: any bug whose fix touches FOCAS writes, offset math, pot table, or shared schema → confirm before changing.
- Failing CI → fix without being told how (subject to the exception above).

---

## Task Management

| # | Step | Artifact |
|---|---|---|
| 1 | **Plan First** | `tasks/todo.md` with checkboxes |
| 2 | **Verify Plan** | Confirm before code |
| 3 | **Track Progress** | Mark items as you go |
| 4 | **Explain Changes** | One-line summary per step |
| 5 | **Document Results** | Review section in `tasks/todo.md` |
| 6 | **Capture Lessons** | Update `tasks/lessons.md` after corrections |

---

## Anti-Patterns (Never Do)

1. **No `git push --force`** on shared branches. `--force-with-lease` only, after explicit confirmation.
2. **No deleting/skipping tests** to make CI pass. Fix the test or the code.
3. **No mocking FOCAS responses to bypass real testing.** Use a documented mock harness (`tooling/focas/mock.py`) labeled as such, never inline shortcuts.
4. **No silent dependency bumps** — especially anything FOCAS-adjacent or shared with tracker.
5. **No `rm -rf`, `DROP TABLE`, `git reset --hard`** without explicit confirmation in same turn.
6. **No secrets in code or commits.** `.env` only. If you see one, flag it.
7. **No reformatting unrelated code.** Diff hygiene > stylistic preferences.
8. **No "I'll just refactor while I'm here."** Stay in scope. Open a separate task. Especially true for tracker code.
9. **No assumed user intent.** If the spec is ambiguous AND the call is consequential, ask.
10. **No autonomous FOCAS writes, and no writes to a live machine.** Every write path requires mode-lockout (machine not running/AUTO) PLUS a **double wall** — the ask (explicit operator approval) AND the entry (gated password `WRITE_APPROVAL_PASSWORD`, env-only, never committed) — both required for every write. No test/script/harness may write to the real machine — mock only. See "FOCAS write safety — HARD GATE".
11. **No reads from tracker schema by tooling code.** Cross-schema reads go through the `shared` schema or an explicit service interface.
12. **No assumption of FOCAS option availability on a new machine.** Smoke-test port 8193 before adding to the machine registry.

---

## Domain-Specific Rules — Tooling

### FOCAS interaction
- All FOCAS calls wrapped in `tooling.focas.client` — no direct library calls from API or UI layers
- Every FOCAS write logs: `(timestamp, machine_id, register, old_value, new_value, user_id, reason)`
- Read-after-write verification mandatory for every offset write
- FOCAS connection failures = circuit-breaker pattern, not retry loop
- Polling cadence configurable per-machine, default 60s; never under 10s without explicit reason
- All FOCAS errors logged with machine ID + raw error code; never swallowed

### FOCAS write safety — HARD GATE (live production machine)

The Viper (10.1.10.58) is a **LIVE machine running production in the shop.** A wrong
or ill-timed write = scrap, broken tooling, or a crash. These rules are **absolute**
and apply to ALL write-path code — API, UI, scripts, harnesses, tests:

- **No write to any FANUC control (offset, pot, parameter, any register) may execute
  unless ALL of the following hold:**
  1. **Machine not live** — verified NOT running and NOT in AUTO (mode lockout). No
     write while the machine is live, ever. This is a precondition — if it fails, the
     write is not even offered.
  2. **DOUBLE WALL — two independent human approvals, both required every time:**
     - **The ask** — an explicit write-approval request is shown, and dbc00per
       affirmatively grants it. A deliberate acknowledgement, never a default/auto-yes.
     - **The entry** — dbc00per manually keys the gated approval password
       (`WRITE_APPROVAL_PASSWORD`, `.env` only — **NEVER hardcoded, NEVER committed**,
       rule 6), and it is verified.
     Neither wall alone is sufficient: the ask without the entry blocks; the entry
     without the ask blocks. Breaking the no-write default takes BOTH, every single write.
- **No test, script, soak, smoke, or harness may target the real machine's write
  functions at any time.** Development writes go ONLY to the documented mock
  (`tooling/focas/mock.py`). Reads against the live machine are fine; writes are not.
- Read-after-write verification remains mandatory once a write is permitted.
- Any PR introducing or altering a write path must include a test proving the gate
  blocks the write until all three conditions are met, and must be confirmed by
  dbc00per before merge (see Stop Conditions).

### Offset math
- **The Viper is INCH. Confirmed by dbc00per 2026-07-15.** Increment = **0.0001 inch/count**
  (FANUC IS-B inch; metric IS-B would be 0.001 mm). `G20` on every posted program.
- **Store the control's native value + an explicit unit** (`shared.machine.offset_unit`),
  never a converted one — what the app shows must equal what the panel shows. This
  **supersedes** the former "lengths in metric (mm) internally" rule, which predated
  knowing the machine's unit. See `tasks/spec-offset-units.md`.
- The unit is **read from the control**, never assumed. Conversion helpers take the unit
  explicitly so no caller can do unit-blind math.
- **Never name a field, constant or column after a unit you have not read from the
  control.** `value_mm` holding inches is what hid a 25.4× error for months.
- Offset diffs vs prior value → flag for operator confirmation, never silent write.
  (Threshold value is an open item — do not re-derive it from the old 0.5 mm figure.)
- Wear offsets and geometry offsets are separate registers — never conflate
- **Writable set = H_GEOM only.** GEOM D stays 0 (CAM programs from centerline);
  WEAR H and WEAR D are the operator's, never app-written.

### Pot table
- Random-access ATC: T-number is identity, pot is location
- Pot reassignment = log event, not silent state change
- Probe pot is reserved (configurable per machine) — never assignable to a regular tool

### Tool identity
- Tools are global entities. Assignment to a machine is a relational record.
- Same tool on two machines may have different H/D registers — store assignment per machine.
- Tool retirement = soft delete (`retired_at` timestamp), never hard delete. Audit trail must survive.

### G10 export/import
- G10 export must round-trip cleanly: export, parse, compare to source — no precision loss
- Imported G10 never auto-applies — always staged for operator review

---

## Tracker Coupling Rules

This project shares infrastructure with Lance CNC Tracker. Rules to prevent breaking it:

- **Database isolation** (Decision-10, `docs/12`): tooling lives in `pottracker_db` (`tooling.*` + `shared.*`). The tracker lives in a **separate database** `tracker_db`. `shared.*` is shared among pottracker's own components, **not** with the tracker — cross-DB reference is physically impossible, so `shared.machine`/`shared.user` are pottracker-owned. No pottracker migration can reach tracker data. Future tracker reads (if ever) via `postgres_fdw` over named views only.
- **No tracker schema writes from tooling code.** Reads only, via explicit views.
- **Migrations**: tooling Alembic migrations target `tooling` schema only. Never modify tracker tables.
- **FOCAS poller** is shared infrastructure (`shared.focas.poller`). Changes to poller require regression test against tracker's existing FOCAS consumers.
- **nginx config**: tooling routes namespaced under `/tooling/*`. Never touch tracker routes.
- **Dependency bumps**: any bump in shared deps (`fastapi`, `sqlalchemy`, `pyfocas`) requires tracker test pass before merge.
- **Deploy**: separate FastAPI worker process for tooling. Tracker restart not required for tooling deploy.

See `docs/07-risks.md` for full risk register.

---

## Output Format

- Code blocks tagged with language
- Git Bash commands prefixed `$`
- File paths repo-rooted (`/apps/tooling/...`)
- No LaTeX in code or prose unless math is non-trivial
- Tables for comparisons, lists for sequences, prose for nothing

---

## Stop Conditions (Bail and Ask)

Stop and ask when:
- Two consecutive fix attempts fail on the same root
- A change would touch >5 files outside the original scope
- A change would touch tracker code or shared schema
- Schema migration on production data
- Any irreversible operation (force push, drop, truncate, delete)
- Any new FOCAS write path being introduced
- A FOCAS response shape doesn't match documented expectation
- Cost-incurring action

---

## Session Bootstrap

On session start:
1. Read `CLAUDE.md` (this file)
2. Read `tasks/lessons.md`
3. Read `tasks/todo.md` (current state)
4. Read `docs/07-risks.md` (active risks)
5. Read `SESSION_NOTES.md` if present
6. State: active project, last checkpoint, next action — then wait for go.
