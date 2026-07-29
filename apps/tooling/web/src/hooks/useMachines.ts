import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { Machine, OffsetRegister, Pot, Spindle, ToolLife, WorkOffset } from "@/types/api";

// Machine list + single-machine mirror reads. Live views poll at 5s (D-6); the
// machine list refreshes on the same cadence so connection state stays current.

export function useMachines() {
  return useQuery({
    queryKey: ["machines"],
    queryFn: () => apiFetch<Machine[]>("/machines"),
    refetchInterval: 5000,
  });
}

export function useMachine(id: string) {
  return useQuery({
    queryKey: ["machine", id],
    queryFn: () => apiFetch<Machine>(`/machines/${id}`),
    refetchInterval: 5000,
  });
}

export function useWorkOffsets(id: string) {
  return useQuery({
    queryKey: ["work-offsets", id],
    queryFn: () => apiFetch<WorkOffset[]>(`/machines/${id}/work-offsets`),
    refetchInterval: 5000,
  });
}

export function useOffsets(id: string, registerType?: string) {
  const qs = registerType ? `?register_type=${registerType}` : "";
  return useQuery({
    queryKey: ["offsets", id, registerType ?? null],
    queryFn: () => apiFetch<OffsetRegister[]>(`/machines/${id}/offsets${qs}`),
    refetchInterval: 5000,
  });
}

export function usePots(id: string) {
  return useQuery({
    queryKey: ["pots", id],
    queryFn: () => apiFetch<Pot[]>(`/machines/${id}/pots`),
    refetchInterval: 5000,
  });
}

export function useToolLife(id: string) {
  return useQuery({
    queryKey: ["tool-life", id],
    queryFn: () => apiFetch<ToolLife[]>(`/machines/${id}/tool-life`),
    refetchInterval: 5000,
  });
}

// Live spindle/NEXT state for the pot-map overlay (HEAD = tool in spindle,
// NEXT = tool on deck). Polled on the same 5s cadence as the pot map.
export function useSpindle(id: string) {
  return useQuery({
    queryKey: ["spindle", id],
    queryFn: () => apiFetch<Spindle>(`/machines/${id}/spindle`),
    refetchInterval: 5000,
  });
}
