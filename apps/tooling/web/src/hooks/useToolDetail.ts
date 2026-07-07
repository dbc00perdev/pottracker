import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { AuditEntry, Page, Tool } from "@/types/api";

export function useTool(id: string) {
  return useQuery({
    queryKey: ["tool", id],
    queryFn: () => apiFetch<Tool>(`/tools/${id}`),
  });
}

// Tool-scoped audit. Admins see all; other roles only their own actions
// (server-enforced), so this may be empty for non-admin viewers — by design.
export function useToolAudit(id: string) {
  return useQuery({
    queryKey: ["tool-audit", id],
    queryFn: () =>
      apiFetch<Page<AuditEntry>>(`/audit?entity_type=tool&entity_id=${id}&limit=50`),
  });
}
