import { Link } from "react-router-dom";

import { StatusBadge } from "@/components/StatusBadge";
import { useAssignments } from "@/hooks/useAssignments";
import { useHealth } from "@/hooks/useHealth";
import { timeAgo } from "@/lib/format";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-3 text-sm font-medium text-neutral-400">{title}</h2>
      {children}
    </section>
  );
}

function MachineStatusCard() {
  const { data, isPending, isError } = useHealth();
  return (
    <Card title="Machine status">
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
    </Card>
  );
}

function PendingReviewsCard() {
  const { data, isPending, isError } = useAssignments(
    { pending_review: true, limit: 10 },
    { refetchInterval: 5000 },
  );
  return (
    <Card title={`Pending reviews${data ? ` (${data.total})` : ""}`}>
      {isPending && <p className="text-neutral-500">Loading…</p>}
      {isError && <p className="text-status-alarm">Failed to load.</p>}
      {data && data.items.length === 0 && <p className="text-neutral-500">Nothing pending.</p>}
      <ul className="space-y-2">
        {data?.items.map((a) => (
          <li key={a.id} className="flex items-center justify-between gap-3 text-sm">
            <Link
              to={`/machines/${a.machine_id}`}
              className="font-mono text-neutral-100 hover:underline"
            >
              {a.tool_short_id}
            </Link>
            <span className="font-mono text-xs text-neutral-500">
              {a.machine_name} T{a.t_number} · {timeAgo(a.assigned_at)}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function DashboardPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      <div className="grid gap-4 lg:grid-cols-2">
        <MachineStatusCard />
        <PendingReviewsCard />
        <Card title="Recent writes">
          <p className="text-neutral-500">
            Offset writes arrive in Phase 6 — none to show yet.
          </p>
        </Card>
        <Card title="Tool-life alerts">
          <p className="text-neutral-500">
            Activates once tool-life is mirrored from the machines.
          </p>
        </Card>
      </div>
    </div>
  );
}
