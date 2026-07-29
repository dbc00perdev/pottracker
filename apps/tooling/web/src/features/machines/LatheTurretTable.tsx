import { useState } from "react";

import { useOffsets } from "@/hooks/useMachines";
import { timeAgo } from "@/lib/format";
import type { Machine, OffsetRegister } from "@/types/api";

/** Lathe (0i-TF) offsets view — X/Z/R geometry+wear plus tip code, one row per
 * register. The lathe class NEVER gets the mill pot map (R20); this table IS
 * the station state for a turret machine (a lathe offset row is the tool).
 * Non-zero registers first; empties behind a toggle. */

const BANKS = ["x_geom", "x_wear", "z_geom", "z_wear", "r_geom", "r_wear", "tip"] as const;
type Bank = (typeof BANKS)[number];

const HEADERS: Record<Bank, string> = {
  x_geom: "X GEOM",
  x_wear: "X WEAR",
  z_geom: "Z GEOM",
  z_wear: "Z WEAR",
  r_geom: "R GEOM",
  r_wear: "R WEAR",
  tip: "TIP",
};

interface Row {
  register: number;
  banks: Partial<Record<Bank, string>>;
  lastPolled: string | null;
}

function buildRows(offsets: OffsetRegister[]): Row[] {
  const byReg = new Map<number, Row>();
  for (const o of offsets) {
    if (!(BANKS as readonly string[]).includes(o.register_type)) continue;
    let row = byReg.get(o.register_number);
    if (!row) {
      row = { register: o.register_number, banks: {}, lastPolled: o.last_polled_at };
      byReg.set(o.register_number, row);
    }
    row.banks[o.register_type as Bank] = o.value_mm;
    row.lastPolled = o.last_polled_at;
  }
  return [...byReg.values()].sort((a, b) => a.register - b.register);
}

function hasValue(row: Row): boolean {
  return BANKS.some((b) => {
    const v = row.banks[b];
    return v !== undefined && Number(v) !== 0;
  });
}

export function LatheTurretTable({ machine }: { machine: Machine }) {
  const { data, isPending, isError } = useOffsets(machine.id);
  const [showEmpty, setShowEmpty] = useState(false);

  if (isPending) return <p className="text-neutral-500">Loading offsets…</p>;
  if (isError) return <p className="text-status-alarm">Failed to load offsets.</p>;

  const rows = buildRows(data ?? []);
  const active = rows.filter(hasValue);
  const shown = showEmpty ? rows : active;
  const latest = rows.reduce<string | null>(
    (acc, r) => (r.lastPolled && (!acc || r.lastPolled > acc) ? r.lastPolled : acc),
    null,
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-neutral-500">
        <span>
          {active.length} active of {rows.length} registers
          {latest ? <> · polled {timeAgo(latest)}</> : null}
        </span>
        <button
          type="button"
          className="min-h-[44px] px-2 text-neutral-400 hover:text-neutral-200"
          onClick={() => setShowEmpty((v) => !v)}
        >
          {showEmpty ? "Hide empty registers" : "Show all registers"}
        </button>
      </div>

      {shown.length === 0 && (
        <p className="text-neutral-500">No offsets mirrored yet.</p>
      )}

      {shown.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-neutral-800 text-left text-xs text-neutral-500">
                <th className="py-2 pr-3 font-medium">REG</th>
                {BANKS.map((b) => (
                  <th key={b} className="py-2 pr-3 font-medium">
                    {HEADERS[b]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="font-mono">
              {shown.map((r) => (
                <tr key={r.register} className="border-b border-neutral-900">
                  <td className="py-1.5 pr-3 text-neutral-400">{r.register}</td>
                  {BANKS.map((b) => {
                    const v = r.banks[b];
                    const zero = v === undefined || Number(v) === 0;
                    return (
                      <td
                        key={b}
                        className={zero ? "py-1.5 pr-3 text-neutral-700" : "py-1.5 pr-3 text-neutral-200"}
                      >
                        {v ?? "—"}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-neutral-600">
        Values verbatim from the control (0i-TF banks, panel-verified 2026-07-29).
        Turret position not yet read — pending per-machine verification.
      </p>
    </div>
  );
}
