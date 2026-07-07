import { useState } from "react";

import { useAudit } from "@/hooks/useAudit";
import { StatusBadge } from "@/components/StatusBadge";
import { timeAgo } from "@/lib/format";

const ENTITY_TYPES = ["tool", "assignment", "machine", "tool_type"];
const PAGE_SIZE = 100;

export function AuditPage() {
  const [entityType, setEntityType] = useState("");
  const [offset, setOffset] = useState(0);
  const { data, isPending, isError } = useAudit({
    entity_type: entityType || undefined,
    limit: PAGE_SIZE,
    offset,
  });

  const total = data?.total ?? 0;
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Audit</h1>
        <span className="text-sm text-neutral-500">{total} entries</span>
      </div>

      <select
        value={entityType}
        onChange={(e) => {
          setEntityType(e.target.value);
          setOffset(0);
        }}
        aria-label="Entity type"
        className="min-h-[44px] rounded-md border border-neutral-700 bg-neutral-950 px-3 text-sm"
      >
        <option value="">All entities</option>
        {ENTITY_TYPES.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>

      {isError && <p className="text-status-alarm">Failed to load audit log.</p>}

      <div className="overflow-x-auto rounded-lg border border-neutral-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-900 text-neutral-400">
            <tr>
              <th className="px-3 py-2 font-medium">When</th>
              <th className="px-3 py-2 font-medium">Event</th>
              <th className="px-3 py-2 font-medium">Entity</th>
              <th className="px-3 py-2 font-medium">Result</th>
            </tr>
          </thead>
          <tbody>
            {isPending && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-center text-neutral-500">
                  Loading…
                </td>
              </tr>
            )}
            {data && data.items.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-center text-neutral-500">
                  No audit entries.
                </td>
              </tr>
            )}
            {data?.items.map((e) => (
              <tr key={e.id} className="border-t border-neutral-800">
                <td className="px-3 py-2 text-xs text-neutral-500">{timeAgo(e.occurred_at)}</td>
                <td className="px-3 py-2 text-neutral-200">{e.event_type}</td>
                <td className="px-3 py-2 font-mono text-xs text-neutral-400">
                  {e.entity_type}
                  {e.reason ? ` · ${e.reason}` : ""}
                </td>
                <td className="px-3 py-2">
                  {e.success ? (
                    <StatusBadge status="ok" label="ok" />
                  ) : (
                    <StatusBadge status="alarm" label={e.error ?? "failed"} />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="min-h-[44px] rounded-md border border-neutral-700 px-4 disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-neutral-400">
            Page {page} of {pages}
          </span>
          <button
            type="button"
            disabled={page >= pages}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="min-h-[44px] rounded-md border border-neutral-700 px-4 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
