import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { HealthResponse } from "@/types/api";

// Public endpoint (no auth). Live view → 5s poll (D-6).
export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiFetch<HealthResponse>("/health", { auth: false }),
    refetchInterval: 5000,
  });
}
