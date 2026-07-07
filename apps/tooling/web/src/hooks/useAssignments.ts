import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { Assignment, Page } from "@/types/api";

export interface AssignmentFilters {
  machine_id?: string;
  tool_id?: string;
  pending_review?: boolean;
  limit?: number;
  offset?: number;
}

function toQuery(f: AssignmentFilters): string {
  const p = new URLSearchParams();
  if (f.machine_id) p.set("machine_id", f.machine_id);
  if (f.tool_id) p.set("tool_id", f.tool_id);
  if (f.pending_review !== undefined) p.set("pending_review", String(f.pending_review));
  p.set("limit", String(f.limit ?? 50));
  p.set("offset", String(f.offset ?? 0));
  return p.toString();
}

export function useAssignments(filters: AssignmentFilters, options?: { refetchInterval?: number }) {
  return useQuery({
    queryKey: ["assignments", filters],
    queryFn: () => apiFetch<Page<Assignment>>(`/assignments?${toQuery(filters)}`),
    refetchInterval: options?.refetchInterval,
    placeholderData: (prev) => prev,
  });
}
