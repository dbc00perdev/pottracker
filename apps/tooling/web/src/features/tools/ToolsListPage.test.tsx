import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToolsListPage } from "@/features/tools/ToolsListPage";
import type { Page, Tool } from "@/types/api";

function toolPage(): Page<Tool> {
  const tool: Tool = {
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
    vendor: "Helical",
    vendor_part_number: "HEM-Q-040250",
    vendor_url: null,
    max_doc_mm: null,
    max_woc_mm: null,
    requires_tsc: false,
    requires_climb: false,
    is_consumable_class: false,
    regrind_count: 0,
    notes: null,
    assignments: [
      { machine_id: "m1", machine_name: "Viper LG-1000AP", t_number: 25, h_register: 125, d_register: 225 },
    ],
    retired_at: null,
  };
  return { items: [tool], total: 1, limit: 50, offset: 0 };
}

function renderList() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ToolsListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ToolsListPage", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(toolPage()), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders a tool row with its compact spec and assignment badge", async () => {
    renderList();
    expect(await screen.findByText("EM-1/4-4F-CRB-001")).toBeInTheDocument();
    expect(screen.getByText(/6.3500mm 4F carbide, tialn/)).toBeInTheDocument();
    expect(screen.getByText(/Viper LG-1000AP T25 H125 D225/)).toBeInTheDocument();
  });
});
