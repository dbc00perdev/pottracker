import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { Page, Tool } from "@/types/api";

export interface ToolFilters {
  q?: string;
  tool_type?: string;
  assigned?: boolean;
  include_retired?: boolean;
  limit?: number;
  offset?: number;
}

function toQuery(filters: ToolFilters): string {
  const p = new URLSearchParams();
  if (filters.q) p.set("q", filters.q);
  if (filters.tool_type) p.set("tool_type", filters.tool_type);
  if (filters.assigned !== undefined) p.set("assigned", String(filters.assigned));
  if (filters.include_retired) p.set("include_retired", "true");
  p.set("limit", String(filters.limit ?? 50));
  p.set("offset", String(filters.offset ?? 0));
  return p.toString();
}

export function useTools(filters: ToolFilters) {
  return useQuery({
    queryKey: ["tools", filters],
    queryFn: () => apiFetch<Page<Tool>>(`/tools?${toQuery(filters)}`),
    placeholderData: (prev) => prev, // keep the page visible while refetching
  });
}
