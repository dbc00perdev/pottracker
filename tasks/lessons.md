# tasks/lessons.md

Captured corrections and rules. Reviewed at session start.

Format: `**Mistake**: ... → **Rule**: ...`

---

**Mistake**: First pass at the FOCAS target function list (Decision-2 brief) included names like `cnc_rdmode`, `cnc_rdtcode`, `cnc_rdsysinfo`, `cnc_rdtoolgrp_id` that look correct but are Series 16/18/21-era names. The FS30i processing DLL (`fwlib30i64.dll`) that serves 0i-MF does not expose them. The extractor flagged them all as NOT FOUND on first run against the real `Fwlib64.h`. → **Rule**: Never add a FOCAS function name to the target list, the spec doc, or the client without first grepping `Fwlib64.h` to confirm it exists. The function-name set differs between FS-16/18/21 and FS30i families, and our docs/training data leak the older names. R9 (FOCAS function name mismatch with reality) is exactly this risk — treat it as a structural hazard, not a one-time mistake.

**Mistake**: Decision-2 brief asked Claude to populate `tasks/spec-focas-calls.md` "verbatim from `C:\Fanuc\FwLib64-runtime\Fwlib64.h`" while the agent was in a Linux container with no Windows mount. → **Rule**: Header / SDK / DLL access lives on the Windows dev box. The agent's job is to write tooling (the extractor) that the operator runs on Windows; the agent does not invent verbatim text it cannot read. Anything claiming to be verbatim from a file the agent didn't read is fabrication.

**Mistake**: First R1 mitigation in `migrations/env.py` checked only `op.schema` — but `CreateForeignKeyOp` stashes `source_schema` and `referent_schema` in `op.kw`, not as direct attributes. A migration creating an FK from `tooling.x` to `tracker.users` walked past the guard silently. → **Rule**: Any guard introspecting Alembic ops must walk both direct attributes ending in `schema` AND keys in `op.kw` ending in `schema`. Spot-check coverage with real op constructors — the text-scraping test harness we had didn't catch this because it didn't exercise FK ops.

**Mistake**: `_check_schema(schema, source)` returned early when `schema is None`, on the assumption "schemaless ops don't need checking." But Postgres routes unqualified DDL through `search_path`, defaulting to `public` — outside our allowlist. A bare `op.create_table('foo')` migration would happily land in `public.foo`. → **Rule**: `schema=None` means "fall through to the connection's search_path default" in Postgres. Treat it as forbidden, not safe. Pair with `SET search_path TO tooling, shared` on the migration connection so unqualified DDL has a safe deterministic landing zone (`tooling`).

**Mistake**: First R1 implementation was autogenerate-only — `process_revision_directives` and `include_object` only fire during `alembic revision --autogenerate`. A hand-written migration with a forbidden FK would never pass through them and would run unchecked at `alembic upgrade` time. → **Rule**: Schema isolation needs layered defense. (1) Runtime DDL inspection via SQLAlchemy `before_cursor_execute` is the primary line — fires on every cursor execute regardless of how the migration was authored. (2) Search-path lockdown on the connection. (3) Autogenerate-time op walker as early-warning. (4) Database-level GRANT as the ultimate belt. Code stops honest mistakes; DB GRANTs stop adversaries.
