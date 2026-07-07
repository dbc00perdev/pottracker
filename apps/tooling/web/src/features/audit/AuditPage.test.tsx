import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuditPage } from "@/features/audit/AuditPage";
import type { AuditEntry, Page } from "@/types/api";

function auditPage(): Page<AuditEntry> {
  const entry: AuditEntry = {
    id: 1,
    occurred_at: new Date().toISOString(),
    user_id: "u1",
    machine_id: null,
    event_type: "tool_create",
    entity_type: "tool",
    entity_id: "t1",
    before_value: null,
    after_value: { short_id: "EM-1" },
    reason: null,
    success: true,
    error: null,
  };
  return { items: [entry], total: 1, limit: 100, offset: 0 };
}

function renderAudit() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuditPage />
    </QueryClientProvider>,
  );
}

describe("AuditPage", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(auditPage()), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders an audit row from the enveloped response", async () => {
    renderAudit();
    expect(await screen.findByText("tool_create")).toBeInTheDocument();
    expect(screen.getByText("1 entries")).toBeInTheDocument();
  });
});
