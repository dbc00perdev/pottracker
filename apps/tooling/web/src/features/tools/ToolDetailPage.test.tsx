import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToolDetailPage } from "@/features/tools/ToolDetailPage";
import type { Page, Tool } from "@/types/api";

const TOOL: Tool = {
  id: "t1",
  short_id: "EM-1/4-4F-CRB-001",
  tool_type: { code: "em_square", display_name: "Square Endmill" },
  diameter_mm: "6.3500",
  diameter_inch: "0.25000",
  flute_count: 4,
  corner_radius_mm: null,
  flute_length_mm: null,
  overall_length_mm: null,
  shank_diameter_mm: null,
  substrate: "carbide",
  coating: "tialn",
  vendor: "MSC",
  vendor_part_number: "04512339",
  vendor_url: null,
  manufacturer: "Helical",
  edp_number: "59424",
  max_doc_mm: null,
  max_woc_mm: null,
  requires_tsc: false,
  requires_climb: true,
  is_consumable_class: false,
  regrind_count: 2,
  description: "0.25in 4FL SQ EM CARBIDE TIALN",
  notes: null,
  assignments: [
    { machine_id: "m1", machine_name: "Viper LG-1000AP", t_number: 25, h_register: 125, d_register: 225 },
  ],
  retired_at: null,
};

function auditPage(): Page<unknown> {
  return { items: [], total: 0, limit: 50, offset: 0 };
}

function mockFetch() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/audit") ? auditPage() : TOOL;
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
  });
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/tools/t1"]}>
        <Routes>
          <Route path="/tools/:id" element={<ToolDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ToolDetailPage", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("fetch", mockFetch());
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows the spec card and active assignment", async () => {
    renderDetail();
    expect(await screen.findByRole("heading", { name: "EM-1/4-4F-CRB-001" })).toBeInTheDocument();
    expect(screen.getByText("Square Endmill")).toBeInTheDocument();
    expect(screen.getByText("6.3500 mm")).toBeInTheDocument();
    expect(screen.getByText(/Viper LG-1000AP: T25 H125 D225/)).toBeInTheDocument();
    expect(screen.getByText("climb only")).toBeInTheDocument();
    // manufacturer + EDP + generated description
    expect(screen.getByText("Helical")).toBeInTheDocument();
    expect(screen.getByText("59424")).toBeInTheDocument();
    expect(screen.getByText("0.25in 4FL SQ EM CARBIDE TIALN")).toBeInTheDocument();
  });
});
