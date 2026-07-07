import { useState } from "react";

import { useOffsets } from "@/hooks/useMachines";
import { mm, mmToInch, timeAgo } from "@/lib/format";

const TYPES = ["h_geom", "h_wear", "d_geom", "d_wear"];

// Read-only offset table. Machine is authoritative for the value; every row is
// labeled with how fresh the poll is (R11 — never present a mirror value as
// "current" without its timestamp).
export function OffsetTable({ machineId }: { machineId: string }) {
  const [type, setType] = useState<string>("");
  const [unit, setUnit] = useState<"mm" | "inch">("mm");
  const { data, isPending, isError } = useOffsets(machineId, type || undefined);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          aria-label="Register type"
          className="min-h-[44px] rounded-md border border-neutral-700 bg-neutral-950 px-3 text-sm"
        >
          <option value="">All types</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => setUnit(unit === "mm" ? "inch" : "mm")}
          className="min-h-[44px] rounded-md border border-neutral-700 px-3 text-sm"
        >
          {unit === "mm" ? "Show inch" : "Show mm"}
        </button>
      </div>

      {isError && <p className="text-status-alarm">Failed to load offsets.</p>}

      <div className="overflow-x-auto rounded-lg border border-neutral-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-900 text-neutral-400">
            <tr>
              <th className="px-3 py-2 font-medium">Register</th>
              <th className="px-3 py-2 font-medium">Type</th>
              <th className="px-3 py-2 font-medium">Value ({unit})</th>
              <th className="px-3 py-2 font-medium">Last polled</th>
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
            {data && data.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-center text-neutral-500">
                  No offsets mirrored yet.
                </td>
              </tr>
            )}
            {data?.map((r) => (
              <tr
                key={`${r.register_type}-${r.register_number}`}
                className="border-t border-neutral-800"
              >
                <td className="px-3 py-2 font-mono text-neutral-100">{r.register_number}</td>
                <td className="px-3 py-2 font-mono text-neutral-400">{r.register_type}</td>
                <td className="px-3 py-2 font-mono text-neutral-100">
                  {unit === "mm" ? mm(r.value_mm) : mmToInch(r.value_mm)}
                </td>
                <td className="px-3 py-2 text-xs text-neutral-500">{timeAgo(r.last_polled_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
