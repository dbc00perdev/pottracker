import { QueryClient } from "@tanstack/react-query";

// Live machine/dashboard views opt into `refetchInterval: 5000` per-hook (D-6);
// the global default stays conservative. Don't retry auth failures — the api
// wrapper already handles 401/refresh, and a hard 401 should surface fast.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
