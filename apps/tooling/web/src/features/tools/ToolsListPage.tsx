import { useState } from "react";
import { Link } from "react-router-dom";

import { useTools } from "@/hooks/useTools";
import { compactSpec } from "@/lib/format";
import type { Tool } from "@/types/api";

const PAGE_SIZE = 50;

function AssignmentBadge({ tool }: { tool: Tool }) {
  if (tool.assignments.length === 0) {
    return <span className="text-neutral-500">unassigned</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {tool.assignments.map((a) => (
        <span
          key={`${a.machine_id}-${a.t_number}`}
          className="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-xs text-neutral-200"
        >
          {a.machine_name} T{a.t_number} H{a.h_register}
          {a.d_register != null ? ` D${a.d_register}` : ""}
        </span>
      ))}
    </div>
  );
}

export function ToolsListPage() {
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const { data, isPending, isError } = useTools({ q: q || undefined, limit: PAGE_SIZE, offset });

  const total = data?.total ?? 0;
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Tools</h1>
        <span className="text-sm text-neutral-500">{total} total</span>
      </div>

      <input
        type="search"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOffset(0);
        }}
        placeholder="Search short ID, vendor P/N, notes…"
        aria-label="Search tools"
        className="min-h-[44px] w-full rounded-md border border-neutral-700 bg-neutral-950 px-3 text-base outline-none focus:border-neutral-400"
      />

      {isError && <p className="text-status-alarm">Failed to load tools.</p>}

      <div className="overflow-x-auto rounded-lg border border-neutral-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-900 text-neutral-400">
            <tr>
              <th className="px-3 py-2 font-medium">Short ID</th>
              <th className="px-3 py-2 font-medium">Spec</th>
              <th className="px-3 py-2 font-medium">Assignment</th>
              <th className="px-3 py-2 font-medium">Vendor</th>
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
            {data?.items.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-center text-neutral-500">
                  No tools match.
                </td>
              </tr>
            )}
            {data?.items.map((tool) => (
              <tr key={tool.id} className="border-t border-neutral-800 hover:bg-neutral-900/50">
                <td className="px-3 py-2">
                  <Link to={`/tools/${tool.id}`} className="font-mono text-neutral-100 underline-offset-2 hover:underline">
                    {tool.short_id}
                  </Link>
                </td>
                <td className="px-3 py-2 text-neutral-300">{compactSpec(tool)}</td>
                <td className="px-3 py-2">
                  <AssignmentBadge tool={tool} />
                </td>
                <td className="px-3 py-2 text-neutral-400">
                  {tool.vendor ?? "—"}
                  {tool.vendor_part_number ? ` · ${tool.vendor_part_number}` : ""}
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
