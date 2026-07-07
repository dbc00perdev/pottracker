import { useHealth } from "@/hooks/useHealth";
import { StatusBadge } from "@/components/StatusBadge";

// Dashboard foundation: live machine-status card off the public /health poll.
// Pending-reviews, recent-writes, and tool-life cards land in a later step.
export function DashboardPage() {
  const { data, isPending, isError } = useHealth();

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Dashboard</h1>

      <section className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-3 text-sm font-medium text-neutral-400">Machine status</h2>
        {isPending && <p className="text-neutral-500">Loading…</p>}
        {isError && <p className="text-status-alarm">Unable to reach the API.</p>}
        {data && data.machines.length === 0 && (
          <p className="text-neutral-500">No machines configured.</p>
        )}
        <ul className="space-y-2">
          {data?.machines.map((m) => (
            <li key={m.id} className="flex items-center justify-between gap-4">
              <span className="text-neutral-200">{m.name}</span>
              <div className="flex items-center gap-4">
                {m.lag_seconds != null && (
                  <span className="font-mono text-xs text-neutral-500">
                    lag {Math.round(m.lag_seconds)}s
                  </span>
                )}
                <StatusBadge
                  status={m.focas_connected ? "ok" : "alarm"}
                  label={m.focas_connected ? "Connected" : "Unreachable"}
                />
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
