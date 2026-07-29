import { Link } from "react-router-dom";

import { StatusBadge } from "@/components/StatusBadge";
import { machineAccent } from "@/features/machines/machineAccent";
import { useMachines } from "@/hooks/useMachines";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

export function MachinesListPage() {
  const { data, isPending, isError } = useMachines();

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Machines</h1>
      {isPending && <p className="text-neutral-500">Loading…</p>}
      {isError && <p className="text-status-alarm">Failed to load machines.</p>}
      {data && data.length === 0 && <p className="text-neutral-500">No machines configured.</p>}

      <div className="grid gap-3 sm:grid-cols-2">
        {data?.map((m) => (
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
              <StatusBadge
                status={m.focas_state.connected ? "ok" : "alarm"}
                label={m.focas_state.connected ? "Connected" : "Unreachable"}
              />
            </div>
            <div className="mt-2 flex justify-between text-xs text-neutral-500">
              <span className="font-mono">{m.control_model}</span>
              <span>polled {timeAgo(m.focas_state.last_polled_at)}</span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
