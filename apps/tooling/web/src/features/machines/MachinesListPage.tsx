import { Link } from "react-router-dom";

import { StatusBadge, type Status } from "@/components/StatusBadge";
import { machineAccent } from "@/features/machines/machineAccent";
import { useMachines } from "@/hooks/useMachines";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { FocasState } from "@/types/api";

// Shop-at-a-glance chip. Mirror status is only trusted when the link is
// fresh (`connected`) — a stale mirror shows Unreachable, never a possibly
// false RUNNING/Idle.
function glance(s: FocasState): { status: Status; label: string } {
  if (!s.connected) return { status: "alarm", label: "Unreachable" };
  if (s.emergency_stop) return { status: "alarm", label: "E-STOP" };
  if (s.running) return { status: "ok", label: "RUNNING" };
  if (s.running === false) return { status: "idle", label: "Idle" };
  return { status: "warn", label: "No status" }; // connected, never polled status
}

export function MachinesListPage() {
  const { data, isPending, isError } = useMachines();
  const runningCount = data?.filter((m) => m.focas_state.connected && m.focas_state.running).length;

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Machines</h1>
        {data && data.length > 0 && (
          <span className="text-sm text-neutral-400">
            {runningCount} of {data.length} running
          </span>
        )}
      </div>
      {isPending && <p className="text-neutral-500">Loading…</p>}
      {isError && <p className="text-status-alarm">Failed to load machines.</p>}
      {data && data.length === 0 && <p className="text-neutral-500">No machines configured.</p>}

      <div className="grid gap-3 sm:grid-cols-2">
        {data?.map((m) => {
          const g = glance(m.focas_state);
          const program =
            m.focas_state.program_number != null
              ? `O${m.focas_state.program_number}${m.focas_state.program_name ? ` — ${m.focas_state.program_name}` : ""}`
              : null;
          return (
            <Link
              key={m.id}
              to={`/machines/${m.id}`}
              className={cn(
                "rounded-lg border-2 bg-neutral-900 p-4 hover:brightness-110",
                machineAccent(m).border,
              )}
            >
              <div className="flex items-center justify-between">
                <span className={cn("font-medium", machineAccent(m).text)}>{m.name}</span>
                <StatusBadge status={g.status} label={g.label} />
              </div>
              <div className="mt-1 truncate font-mono text-xs text-neutral-400">
                {program ?? " "}
              </div>
              <div className="mt-2 flex justify-between text-xs text-neutral-500">
                <span className="font-mono">{m.control_model}</span>
                <span>polled {timeAgo(m.focas_state.last_polled_at)}</span>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
