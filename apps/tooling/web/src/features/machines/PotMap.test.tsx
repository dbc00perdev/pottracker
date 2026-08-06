import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PotMap } from "@/features/machines/PotMap";
import type { Machine, Pot, Spindle } from "@/types/api";

function pot(overrides: Partial<Pot> & Pick<Pot, "pot_number">): Pot {
  return {
    t_number: null,
    state: "empty",
    verified: false,
    assigned_h_register: null,
    offset_mm: null,
    location: null,
    last_polled_at: "2026-07-09T12:00:00Z",
    last_changed_at: "2026-07-09T12:00:00Z",
    ...overrides,
  };
}

const POTS: Pot[] = [
  pot({ pot_number: 1, t_number: 84, state: "loaded", verified: true, assigned_h_register: 84, offset_mm: "5.10" }),
  // T50 is physically in the spindle -> vacated, must NOT render as loaded.
  pot({ pot_number: 2, t_number: 50, state: "loaded", verified: true, assigned_h_register: 50, offset_mm: "3.40", location: "spindle" }),
  // T33 on deck -> vacated as "next".
  pot({ pot_number: 3, t_number: 33, state: "loaded", assigned_h_register: 33, offset_mm: "2.00", location: "next" }),
];

const SPINDLE: Spindle = {
  head_t_number: 50,
  next_t_number: 33,
  mode: "auto",
  active_wcs: null,
  running: true,
  emergency_stop: false,
  program_number: null,
  program_name: null,
  last_tool_t_word: null,
  last_tool_at: null,
  last_polled_at: "2026-07-09T12:00:00Z",
  last_changed_at: "2026-07-09T12:00:00Z",
};

function machine(): Machine {
  return {
    id: "m1",
    name: "Viper LG-1000AP",
    machine_class: "mill",
    serial_number: null,
    control_model: "0i-MF",
    ip_address: "10.1.10.58",
    focas_port: 8193,
    pot_count: 4,
    probe_pot: 24,
    probe_t_number: 50,
    probe_h_register: 50,
    offset_register_count: 400,
    atc_strategy: "random_access",
    has_tsc: false,
    has_toolsetter: true,
    poll_interval_seconds: 60,
    status_poll_interval_seconds: null,
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

function renderMap() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PotMap machine={machine()} />
    </QueryClientProvider>,
  );
}

describe("PotMap spindle/NEXT overlay", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/spindle")) return Promise.resolve(jsonResponse(SPINDLE));
        if (url.includes("/tools")) {
          return Promise.resolve(jsonResponse({ items: [], total: 0, limit: 200, offset: 0 }));
        }
        if (url.includes("/assignments")) {
          return Promise.resolve(jsonResponse({ items: [], total: 0, limit: 200, offset: 0 }));
        }
        return Promise.resolve(jsonResponse(POTS));
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders the Spindle (HEAD) and Next slots from the status mirror", async () => {
    renderMap();
    const spindle = await screen.findByLabelText("Spindle: tool T50");
    expect(spindle).toHaveTextContent("T50");
    const next = screen.getByLabelText("Next: tool T33");
    expect(next).toHaveTextContent("T33");
  });

  it("draws a pot whose tool is in the spindle as vacated, not loaded", async () => {
    renderMap();
    // Pot 2 holds T50's identity, but T50 is in the spindle -> vacated.
    // Ring face uses compact "→sp"; full "in spindle" is in the aria-label.
    const pot2 = await screen.findByLabelText(/^Pot 2 tool T50 in spindle/);
    expect(pot2).toHaveTextContent("→sp");
    expect(pot2).toHaveTextContent("T50");
  });

  it("draws the on-deck tool's pot as vacated 'next'", async () => {
    renderMap();
    const pot3 = await screen.findByLabelText(/^Pot 3 tool T33 in next/);
    expect(pot3).toHaveTextContent("→nx");
    expect(pot3).toHaveTextContent("T33");
  });

  it("renders a genuinely resident tool normally", async () => {
    renderMap();
    const pot1 = await screen.findByLabelText(/^Pot 1 loaded tool T84 presetter-verified/);
    expect(pot1).toHaveTextContent("T84");
  });

  it("shows active-on-machine table rows only (not full crib)", async () => {
    renderMap();
    // Spindle T50 + next T33 + resident T84 = 3 active identities.
    expect(await screen.findByText(/Active on machine/i)).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: /search active loadout/i })).toBeInTheDocument();
    // T84 appears on the ring face and in the loadout table.
    expect(screen.getAllByText("T84").length).toBeGreaterThanOrEqual(2);
    // NO REC for tools with no crib join
    expect(screen.getAllByText("NO REC").length).toBeGreaterThan(0);
  });

  it("notes NEXT pot at 6 o'clock when NEXT is known", async () => {
    renderMap();
    // NEXT T33 lives in pot 3 → ring anchors pot 3 at 6 o'clock.
    expect(await screen.findByText(/NEXT pot 3 at 6/i)).toBeInTheDocument();
    expect(screen.getAllByText("NEXT @ 6").length).toBeGreaterThan(0);
  });

  it("opens detail drawer on pot click", async () => {
    renderMap();
    const pot1 = await screen.findByLabelText(/^Pot 1 loaded tool T84/);
    fireEvent.click(pot1);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /T84/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Close$/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("switches right pane to on-machine offsets", async () => {
    renderMap();
    fireEvent.click(await screen.findByRole("tab", { name: /^Offsets$/i }));
    expect(await screen.findByText(/Offsets — on machine/i)).toBeInTheDocument();
  });
});
