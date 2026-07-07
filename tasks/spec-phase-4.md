# Spec — Phase 4: Frontend Foundation

Status: **DRAFT — awaiting dbc00per sign-off** (esp. the dependency decisions in §3).
Source of truth: `docs/05-ui-flows.md` (read-only paths), `docs/04-api.md` (contract),
`docs/06-phases.md` Phase 4 gate. Branch: continues `claude/summarize-build-eWINf`.

---

## 1. Goal & gate

Stand up the SPA under `apps/tooling/web/` so an operator can **log in and browse**
the system read-only. No writes, no assignment creation (those are Phase 5/6).

**Gate criteria (from docs/06):**
- Operator can log in, browse tools, browse machine state.
- Read flows match `docs/05-ui-flows.md` read-only paths.
- Responsive on tablet (1024px), phone-usable for monitoring (600px breakpoint).
- Dashboards reflect FOCAS state within 60s of underlying change (→ 5s polling, D-6).

---

## 2. Scope

### In
- Vite + React 19 + TS 6 scaffold: `index.html`, `vite.config.ts`, `tsconfig*.json`,
  `src/` entry, Tailwind 4 wired, path alias `@/`.
- Auth: login page, JWT access+refresh storage, refresh-on-401, `/auth/me` bootstrap,
  role in context, logout. Protected routes (redirect to login when unauthenticated).
- App shell: sidebar (Dashboard / Tools / Machines / Audit), top bar (user, machine
  selector, global search box — box present, wiring minimal), responsive drawer.
- **Tools**: list (filters/search/sort per `GET /tools`, consumes the `{items,total,…}`
  envelope + `limit`/`offset` paging) + tool detail (spec card, **active** assignments,
  tool-scoped audit via `GET /audit?entity_type=tool&entity_id=`).
- **Machines**: machine list (`GET /machines`, connection state), machine view with the
  **read-only** tabs: Pot Map (SVG grid, 24 pots, status badges incl. probe pot),
  Offset Table (`/machines/{id}/offsets`, type filter, mm/inch toggle, mono font),
  Tool Life (`/machines/{id}/tool-life`). Alarms tab = "not available in v1" placeholder
  (no alarm mirror table yet — migration 0004+, see todo).
- **Dashboard**: Machine-status card + Pending-reviews card (`/assignments?pending_review=true`)
  + Recent-writes card renders "no write path yet (Phase 6)" empty state. Tool-life-alerts
  card from tool-life reads.
- **Audit** view (admin full, others own): table over the enveloped `/audit`, filters, paging.
- Live data via **5s polling** (D-6), no WebSocket (v1.1).
- Health/connection banner from public `GET /health`.

### Out (deferred)
- Every write path: offset write flow, assign-to-pot create, confirm/retire actions,
  G10 export/import (Phases 5/6/7/9). Buttons for these render **disabled** with a
  "coming in a later phase" affordance, not wired.
- Alarms data (no backend table).
- CSV export of audit (nice-to-have, not gate).
- Drag-drop pot reassignment (v1 excluded, docs/05).

---

## 3. Stack decisions — LOCKED (dbc00per approved "full standard stack", 2026-07-07)

All `bun add` into `apps/tooling/web`, `--exact`, isolated from Python/Postgres. bun.lock
committed. **Approval covers this dependency set;** exact versions get pinned at install
time (latest-compatible with the already-pinned React 19 / Vite 8 / TS 6 / Tailwind 4) and
listed back before the `bun add` runs.

| # | Decision | CHOSEN | Deps |
|---|---|---|---|
| **D4-1** | Server-state / data-fetching | **TanStack Query v5** (5s polling = its core use case) | `@tanstack/react-query` |
| **D4-2** | Routing | **React Router v7**, library mode (no SSR/framework mode) | `react-router-dom` |
| **D4-3** | UI kit | **shadcn/ui** — components copied into `src/components/ui` | `class-variance-authority`, `tailwind-merge`, `clsx`, `lucide-react`, `@radix-ui/*` per component |
| **D4-4** | Forms/validation | **Deferred to Phase 5** (read-only needs none) | none now |
| **D4-5** | Component tests | **Vitest + React Testing Library**, thin (auth guard, one list render, api-client 401→refresh) | `-D vitest @testing-library/react @testing-library/jest-dom jsdom` |
| **D4-6** | Dev serving / CORS | **Vite dev proxy** `/api/tooling` → `http://localhost:8000`; no FastAPI CORS change. Prod nginx = Phase 10. | none |
| **D4-7** | Token storage | `localStorage` access+refresh + fetch interceptor: refresh on 401, retry once. Native fetch (no axios). | none |

Install command (versions pinned + shown before running):
```
bun add --exact @tanstack/react-query react-router-dom \
  class-variance-authority tailwind-merge clsx lucide-react
bun add --exact -d vitest @testing-library/react @testing-library/jest-dom jsdom
# shadcn init pulls @radix-ui/* per component as components are added
```

---

## 4. Proposed layout

```
apps/tooling/web/
  index.html
  vite.config.ts            # react plugin, tailwind plugin, @/ alias, /api proxy
  tsconfig.json, tsconfig.node.json
  src/
    main.tsx                # QueryClientProvider + RouterProvider + AuthProvider
    app/router.tsx          # route table, protected-route wrapper
    lib/api.ts              # fetch wrapper: base /api/tooling, bearer, 401→refresh→retry
    lib/auth.tsx            # AuthProvider, useAuth(), token store, login/logout
    lib/format.ts           # mm/inch, 4-dp, T#/register mono helpers
    hooks/                  # useTools, useMachine, useOffsets, usePending, useAudit (Query)
    components/ui/          # shadcn components
    components/             # AppShell, Sidebar, TopBar, StatusBadge, MachineSelector
    features/
      auth/LoginPage.tsx
      dashboard/DashboardPage.tsx
      tools/ToolsListPage.tsx, ToolDetailPage.tsx
      machines/MachinesListPage.tsx, MachineView.tsx, PotMap.tsx, OffsetTable.tsx, ToolLife.tsx
      audit/AuditPage.tsx
    types/api.ts            # hand-written types matching docs/04 responses
```

400-LOC cap applies. `MachineView` tabs split into per-tab files from the start.
Colors/typography from docs/05 §"Color & typography" go into Tailwind theme tokens.

## 5. Data & polling
- One `QueryClient`; per-resource hooks set `refetchInterval: 5000` only on live views
  (machine state, dashboard, pending). Tools list/detail poll slower or on-focus.
- API types hand-written in `types/api.ts` from docs/04 (no codegen in v1; revisit if drift).
- Envelope-aware list hooks return `{items,total}`; paging via `limit`/`offset`.

## 6. Verification (Phase-4 gate proof)
- `bun run typecheck` (tsc) + `bun run build` clean.
- `bun run dev` + FastAPI up (`.venv/Scripts/python -m uvicorn apps.tooling.api.main:create_app --factory`,
  DATABASE_URL=dev): manual walkthrough — log in as each seeded role, browse tools, open a
  machine, see offsets/pot-map/tool-life, watch a value change reflect within 60s.
- Thin Vitest suite green (if D4-5 = yes).
- CI: add a `web` job (bun install --frozen-lockfile, typecheck, build, vitest). Mirrors
  the Python jobs; keep it a separate job.

## 7. Task checklist (fills into tasks/todo.md on approval)
1. Scaffold (index.html, vite/ts config, Tailwind, `@/`, proxy) → `bun run dev` shows a blank shell.
2. `lib/api.ts` + `lib/auth.tsx` + LoginPage; protected routing; `/auth/me` bootstrap.
3. App shell (sidebar/topbar/responsive drawer) + StatusBadge + health banner.
4. Tools list (filters/paging) + tool detail (+ tool-scoped audit).
5. Machines list + MachineView tabs (PotMap, OffsetTable, ToolLife); Alarms placeholder.
6. Dashboard cards; Audit view.
7. 5s polling wired on live views; format helpers; a11y pass (focus, ARIA, 44px targets).
8. Vitest thin suite (if approved); CI `web` job; verify gate; docs/05 read-paths checked off.

## 8. Risks / notes
- **No write UI** — every mutating affordance is visibly disabled; avoids implying a
  capability that isn't safety-reviewed yet (R6/R11: don't let the UI over-promise).
- **R11 (trust)**: machine values must always be labeled with `last_polled_at`; never show
  an offset as "current" without its poll timestamp (docs/05, R11 mitigation).
- Prod nginx/Docker wiring is Phase 10; Phase 4 is dev-serve only.
- shadcn init writes a `components.json` + tailwind tweaks — keep that diff reviewable.
```
