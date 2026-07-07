import { useToolLife } from "@/hooks/useMachines";
import { timeAgo } from "@/lib/format";

// Read-only tool-life mirror (docs/05 Tool Life tab; write-back is out of v1).
export function ToolLifeTable({ machineId }: { machineId: string }) {
  const { data, isPending, isError } = useToolLife(machineId);

  if (isPending) return <p className="text-neutral-500">Loading…</p>;
  if (isError) return <p className="text-status-alarm">Failed to load tool life.</p>;
  if (!data || data.length === 0)
    return <p className="text-neutral-500">No tool-life data mirrored yet.</p>;

  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-neutral-900 text-neutral-400">
          <tr>
            <th className="px-3 py-2 font-medium">T#</th>
            <th className="px-3 py-2 font-medium">Life</th>
            <th className="px-3 py-2 font-medium">Max</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Last polled</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r) => (
            <tr key={r.t_number} className="border-t border-neutral-800">
              <td className="px-3 py-2 font-mono text-neutral-100">T{r.t_number}</td>
              <td className="px-3 py-2 font-mono text-neutral-300">{r.life_count ?? "—"}</td>
              <td className="px-3 py-2 font-mono text-neutral-300">{r.life_max ?? "—"}</td>
              <td className="px-3 py-2 text-neutral-300">{r.status ?? "—"}</td>
              <td className="px-3 py-2 text-xs text-neutral-500">{timeAgo(r.last_polled_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
