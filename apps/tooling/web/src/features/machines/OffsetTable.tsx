import { useState } from "react";

import {
  buildChangeMap,
  changeKey,
  OffsetChangeTip,
} from "@/features/machines/OffsetChangeTip";
import { useOffsetChanges, useOffsets } from "@/hooks/useMachines";
import { timeAgo } from "@/lib/format";

const TYPES = ["h_geom", "h_wear", "d_geom", "d_wear"];

// Values are CONTROL-NATIVE — inch shop-wide (INI=1 fleet-verified
// 2026-08-05; spec-offset-units: what the app shows must equal what the
// panel shows). The old mm/inch toggle divided native-inch values by 25.4
// and is deliberately gone.
function native(value: string): string {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(4) : "—";
}

// Read-only offset table. Machine is authoritative for the value; every row is
// labeled with how fresh the poll is (R11 — never present a mirror value as
// "current" without its timestamp). Hover a value for its last audited change.
export function OffsetTable({ machineId }: { machineId: string }) {
  const [type, setType] = useState<string>("");
  const { data, isPending, isError } = useOffsets(machineId, type || undefined);
  const { data: changes } = useOffsetChanges(machineId);
  const changeMap = buildChangeMap(changes);

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
        <span className="text-xs text-neutral-500">
          values control-native (inch) · hover a value for its last change
        </span>
      </div>

      {isError && <p className="text-status-alarm">Failed to load offsets.</p>}

      <div className="overflow-x-auto rounded-lg border border-neutral-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-neutral-900 text-neutral-400">
            <tr>
              <th className="px-3 py-2 font-medium">Register</th>
              <th className="px-3 py-2 font-medium">Type</th>
              <th className="px-3 py-2 font-medium">Value (inch)</th>
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
                  <OffsetChangeTip
                    change={changeMap.get(changeKey(r.register_number, r.register_type))}
                  >
                    {native(r.value_mm)}
                  </OffsetChangeTip>
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
