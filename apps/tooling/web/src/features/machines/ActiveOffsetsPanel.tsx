import { useMemo } from "react";

import type { ActiveLoadoutRow } from "@/features/machines/activeLoadout";
import { useOffsets } from "@/hooks/useMachines";
import { mm } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { OffsetRegister } from "@/types/api";

// Phase-3: offset banks for tools currently on the machine only (not all 400).

const BANKS = ["h_geom", "h_wear", "d_geom", "d_wear"] as const;
type Bank = (typeof BANKS)[number];

const BANK_LABEL: Record<Bank, string> = {
  h_geom: "GEOM H",
  h_wear: "WEAR H",
  d_geom: "GEOM D",
  d_wear: "WEAR D",
};

const BANK_COLOR: Record<Bank, string> = {
  h_geom: "text-emerald-300",
  h_wear: "text-sky-300",
  d_geom: "text-violet-300",
  d_wear: "text-teal-300",
};

export function ActiveOffsetsPanel({
  machineId,
  rows,
  hoverT,
  onHoverT,
  onActivateT,
}: {
  machineId: string;
  rows: ActiveLoadoutRow[];
  hoverT: number | null;
  onHoverT: (t: number | null) => void;
  onActivateT: (t: number) => void;
}) {
  const { data: offsets, isPending, isError } = useOffsets(machineId);

  const byReg = useMemo(() => groupByRegister(offsets ?? []), [offsets]);

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-950/40 p-4">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral-500">
        Offsets — on machine ({rows.length})
      </h2>

      {isError && <p className="text-status-alarm">Failed to load offsets.</p>}
      {isPending && <p className="text-neutral-500">Loading offsets…</p>}

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-[12.5px]">
          <thead>
            <tr className="text-[10.5px] uppercase tracking-wide text-neutral-500">
              <th className="border-b border-neutral-800 px-2 py-1.5">Where</th>
              <th className="border-b border-neutral-800 px-2 py-1.5">T</th>
              <th className="border-b border-neutral-800 px-2 py-1.5">H/N</th>
              {BANKS.map((b) => (
                <th
                  key={b}
                  className={cn(
                    "border-b border-neutral-800 px-2 py-1.5 text-right",
                    BANK_COLOR[b],
                  )}
                >
                  {BANK_LABEL[b]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const reg = r.n_register;
              const banks = reg != null ? byReg.get(reg) : undefined;
              return (
                <tr
                  key={r.t_number}
                  data-t={r.t_number}
                  className={cn(
                    "cursor-pointer border-b border-neutral-900",
                    hoverT === r.t_number && "bg-cyan-950/40",
                  )}
                  onMouseEnter={() => onHoverT(r.t_number)}
                  onMouseLeave={() => onHoverT(null)}
                  onClick={() => onActivateT(r.t_number)}
                >
                  <td className="px-2 py-1.5 text-neutral-500">{r.where}</td>
                  <td className="px-2 py-1.5 font-mono font-bold">T{r.t_number}</td>
                  <td className="px-2 py-1.5 font-mono text-neutral-400">
                    {reg != null ? `H${reg}` : "—"}
                  </td>
                  {BANKS.map((b) => (
                    <td
                      key={b}
                      className={cn(
                        "px-2 py-1.5 text-right font-mono tabular-nums",
                        banks?.[b] != null && banks[b] !== "0" && banks[b] !== "0.0000"
                          ? "text-neutral-100"
                          : "text-neutral-600",
                      )}
                    >
                      {reg == null ? "—" : mm(banks?.[b] ?? null)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && (
          <p className="py-6 text-center text-sm text-neutral-500">No tools on machine.</p>
        )}
      </div>
      <p className="mt-3 text-xs text-neutral-500">
        Active tools only. Full 400-register table is on the Offsets machine tab.
      </p>
    </div>
  );
}

function groupByRegister(
  offsets: OffsetRegister[],
): Map<number, Partial<Record<Bank, string>>> {
  const map = new Map<number, Partial<Record<Bank, string>>>();
  for (const o of offsets) {
    if (!BANKS.includes(o.register_type as Bank)) continue;
    let row = map.get(o.register_number);
    if (!row) {
      row = {};
      map.set(o.register_number, row);
    }
    row[o.register_type as Bank] = o.value_mm;
  }
  return map;
}
