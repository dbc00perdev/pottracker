import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { AuditEntry, Page } from "@/types/api";

export interface AuditFilters {
  event_type?: string;
  entity_type?: string;
  machine_id?: string;
  limit?: number;
  offset?: number;
}

function toQuery(f: AuditFilters): string {
  const p = new URLSearchParams();
  if (f.event_type) p.set("event_type", f.event_type);
  if (f.entity_type) p.set("entity_type", f.entity_type);
  if (f.machine_id) p.set("machine_id", f.machine_id);
  p.set("limit", String(f.limit ?? 100));
  p.set("offset", String(f.offset ?? 0));
  return p.toString();
}

// Enveloped; admins see all, other roles are server-scoped to their own actions.
export function useAudit(filters: AuditFilters) {
  return useQuery({
    queryKey: ["audit", filters],
    queryFn: () => apiFetch<Page<AuditEntry>>(`/audit?${toQuery(filters)}`),
    placeholderData: (prev) => prev,
  });
}
