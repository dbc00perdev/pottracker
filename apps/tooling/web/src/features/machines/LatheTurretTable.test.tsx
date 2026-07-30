import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LatheTurretTable } from "@/features/machines/LatheTurretTable";
import type { Machine, OffsetRegister, Spindle } from "@/types/api";

/** VT_23 hub: context-aware NO OFFSET (L1) + last-real-offset memory (L2).
 * The shop cancels the offset with Tnn00 at the end of EVERY op, so an idle
 * cancel is convention (neutral), while running-with-no-offset is alarming
 * (amber). */

const OFFSETS: OffsetRegister[] = [
  {
    register_number: 12,
    register_type: "x_geom",
    value_mm: "2.2457",
    last_polled_at: "2026-07-30T12:00:00Z",
    last_changed_at: "2026-07-30T12:00:00Z",
  },
];

function spindle(overrides: Partial<Spindle>): Spindle {
  return {
    head_t_number: null,
    next_t_number: null,
    mode: "mdi",
    running: false,
    emergency_stop: false,
    active_wcs: null,
    last_tool_t_word: null,
    last_tool_at: null,
    last_polled_at: "2026-07-30T12:00:00Z",
    last_changed_at: "2026-07-30T12:00:00Z",
    ...overrides,
  };
}

function machine(): Machine {
  return {
    id: "vt23",
    name: "VIPER VT_23",
    machine_class: "lathe",
    serial_number: null,
    control_model: "0i-TF",
    ip_address: "10.1.10.53",
    focas_port: 8193,
    pot_count: 12,
    probe_pot: null,
    probe_t_number: null,
    probe_h_register: null,
    offset_register_count: 99,
    atc_strategy: "random_access",
    has_tsc: false,
    has_toolsetter: false,
    poll_interval_seconds: 60,
    enabled: true,
    retired_at: null,
    focas_state: { connected: true, last_polled_at: null, lag_seconds: null },
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function renderTurret(sp: Spindle) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/spindle")) return Promise.resolve(jsonResponse(sp));
      if (url.includes("/work-offsets")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/tools")) {
        return Promise.resolve(jsonResponse({ items: [], total: 0, limit: 200, offset: 0 }));
      }
      return Promise.resolve(jsonResponse(OFFSETS));
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LatheTurretTable machine={machine()} />
    </QueryClientProvider>,
  );
}

describe("LatheTurretTable hub — context-aware active offset", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("shows red OFS nn when a real Tnnww is commanded", async () => {
    renderTurret(spindle({ head_t_number: 1224, running: true }));
    expect(await screen.findByText("S12")).toBeInTheDocument();
    expect(screen.getByText("OFS 24")).toBeInTheDocument();
    expect(screen.queryByText("NO OFFSET")).not.toBeInTheDocument();
  });

  it("shouts amber NO OFFSET only when RUNNING with a cancel word", async () => {
    renderTurret(spindle({ head_t_number: 1200, running: true }));
    expect(await screen.findByText("NO OFFSET")).toBeInTheDocument();
    expect(screen.queryByText(/offset canceled \(idle\)/)).not.toBeInTheDocument();
  });

  it("renders a neutral idle-cancel note when NOT running (Tnn00 convention)", async () => {
    renderTurret(spindle({ head_t_number: 1200, running: false }));
    expect(await screen.findByText("offset canceled (idle)")).toBeInTheDocument();
    expect(screen.queryByText("NO OFFSET")).not.toBeInTheDocument();
  });

  it("treats unknown running state as idle, not alarming", async () => {
    renderTurret(spindle({ head_t_number: 1200, running: null }));
    expect(await screen.findByText("offset canceled (idle)")).toBeInTheDocument();
    expect(screen.queryByText("NO OFFSET")).not.toBeInTheDocument();
  });

  it("shows the last-real-offset memory alongside a cancel (L2)", async () => {
    renderTurret(
      spindle({
        head_t_number: 1200,
        running: false,
        last_tool_t_word: 1208,
        last_tool_at: new Date(Date.now() - 5 * 60_000).toISOString(),
      }),
    );
    expect(await screen.findByText("offset canceled (idle)")).toBeInTheDocument();
    expect(screen.getByText(/last OFS 08/)).toBeInTheDocument();
  });

  it("omits the memory line when a real offset is active", async () => {
    renderTurret(spindle({ head_t_number: 1224, running: true, last_tool_t_word: 1208 }));
    expect(await screen.findByText("OFS 24")).toBeInTheDocument();
    expect(screen.queryByText(/last OFS/)).not.toBeInTheDocument();
  });
});
