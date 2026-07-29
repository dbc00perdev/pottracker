import { useState } from "react";

import { potPosition } from "@/features/machines/ringLayout";
import { useOffsets, useWorkOffsets } from "@/hooks/useMachines";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Machine, OffsetRegister, WorkOffset } from "@/types/api";

/** Lathe (0i-TF) view — turret ring + offsets table. The lathe class NEVER
 * gets the mill pot map (R20); on a turret machine the offset row IS the
 * station state. Station n displays register n (the shop's Tnnnn convention:
 * station == primary offset); registers beyond the turret live in the table.
 * Turret position is not read yet (pending per-machine verification), so no
 * station is drawn "active". */

const BANKS = ["x_geom", "z_geom", "x_wear", "z_wear", "r_geom", "r_wear", "tip"] as const;
type Bank = (typeof BANKS)[number];

const HEADERS: Record<Bank, string> = {
  x_geom: "X GEOM",
  z_geom: "Z GEOM",
  x_wear: "X WEAR",
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

function num(v: string | undefined): number {
  return v === undefined ? 0 : Number(v);
}

function hasValue(row: Row): boolean {
  return BANKS.some((b) => num(row.banks[b]) !== 0);
}

/** geometry set → solid; wear-only → amber hint; nothing → dashed empty */
function stationStyle(row: Row | undefined): string {
  if (!row) return "border-dashed border-neutral-700 bg-neutral-950 text-neutral-600";
  const geom = num(row.banks.x_geom) !== 0 || num(row.banks.z_geom) !== 0;
  if (geom) return "border-emerald-500 bg-emerald-950/40 text-neutral-100";
  if (hasValue(row)) return "border-amber-500/70 bg-amber-950/30 text-neutral-300";
  return "border-dashed border-neutral-700 bg-neutral-950 text-neutral-600";
}

function fmt(v: string | undefined): string {
  if (v === undefined) return "—";
  const n = Number(v);
  return Number.isInteger(n) ? String(n) : n.toFixed(4);
}

const SLOT_LABELS: Record<string, string> = {
  work_shift: "WORK SHIFT",
  ext: "EXT",
  g54: "G54",
  g55: "G55",
  g56: "G56",
  g57: "G57",
  g58: "G58",
  g59: "G59",
};
const SLOT_ORDER = ["work_shift", "ext", "g54", "g55", "g56", "g57", "g58", "g59"];

/** WORK SHIFT + non-zero work offsets — per-job setup truth (T1 sets the
 * shift on this machine). WORK SHIFT always shown; G5x slots only when set. */
function WorkShiftCard({ machineId }: { machineId: string }) {
  const { data } = useWorkOffsets(machineId);
  if (!data || data.length === 0) return null;

  const bySlot = new Map<string, Partial<Record<"x" | "z", WorkOffset>>>();
  for (const wo of data) {
    const s = bySlot.get(wo.slot) ?? {};
    s[wo.axis] = wo;
    bySlot.set(wo.slot, s);
  }
  const shown = SLOT_ORDER.filter((slot) => {
    const s = bySlot.get(slot);
    if (!s) return false;
    if (slot === "work_shift") return true;
    return Number(s.x?.value ?? 0) !== 0 || Number(s.z?.value ?? 0) !== 0;
  });
  if (shown.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-3">
      {shown.map((slot) => {
        const s = bySlot.get(slot)!;
        const isShift = slot === "work_shift";
        return (
          <div
            key={slot}
            className={cn(
              "rounded-lg border bg-neutral-900 px-3 py-2",
              isShift ? "border-emerald-600" : "border-neutral-800",
            )}
          >
            <div className={cn("text-[10px] uppercase tracking-wide", isShift ? "text-emerald-400" : "text-neutral-500")}>
              {SLOT_LABELS[slot] ?? slot.toUpperCase()}
            </div>
            <div className="font-mono text-sm text-neutral-200">
              <span className="text-neutral-500">X</span> {s.x ? Number(s.x.value).toFixed(4) : "—"}
              <span className="ml-3 text-neutral-500">Z</span>{" "}
              {s.z ? Number(s.z.value).toFixed(4) : "—"}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function TurretRing({
  rows,
  stationCount,
  selected,
  onSelect,
}: {
  rows: Row[];
  stationCount: number;
  selected: number | null;
  onSelect: (station: number | null) => void;
}) {
  const byReg = new Map(rows.map((r) => [r.register, r]));
  return (
    <div className="relative mx-auto aspect-square w-full max-w-[460px]">
      {/* hub */}
      <div className="absolute left-1/2 top-1/2 z-[1] flex h-[150px] w-[150px] -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center rounded-full border-2 border-dashed border-emerald-400/60 bg-neutral-950 text-center sm:h-32 sm:w-32">
        <span className="text-[10px] uppercase tracking-wide text-neutral-500">Turret</span>
        <span className="font-mono text-lg font-bold text-neutral-200">{stationCount} STN</span>
        <span className="px-2 text-[9px] leading-tight text-neutral-600">
          position not read yet
        </span>
      </div>

      <div role="list" aria-label="Turret stations">
        {Array.from({ length: stationCount }, (_, i) => i + 1).map((stn) => {
          const pos = potPosition(stn, stationCount, null);
          const row = byReg.get(stn);
          const sel = selected === stn;
          return (
            <div
              key={stn}
              role="listitem"
              aria-label={`Station ${stn}`}
              style={{ left: pos.left, top: pos.top }}
              onClick={() => onSelect(sel ? null : stn)}
              className={cn(
                "absolute flex h-[62px] w-[62px] -translate-x-1/2 -translate-y-1/2 cursor-pointer flex-col items-center justify-center rounded-full border-2 text-center leading-tight transition-transform hover:z-10 hover:scale-110 sm:h-14 sm:w-14",
                stationStyle(row),
                sel && "z-20 shadow-[0_0_0_3px_rgba(165,180,252,0.65)]",
              )}
            >
              <span className="font-mono text-[9px] text-neutral-500">S</span>
              <span className="font-mono text-sm font-bold">{stn}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StationDetail({ row, station }: { row: Row | undefined; station: number }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-3 font-mono text-sm">
      <span className="mr-3 font-bold text-indigo-300">Station {station}</span>
      {row ? (
        BANKS.map((b) => (
          <span key={b} className="mr-3 whitespace-nowrap">
            <span className="text-neutral-500">{HEADERS[b]}</span>{" "}
            <span className={num(row.banks[b]) === 0 ? "text-neutral-600" : "text-neutral-200"}>
              {fmt(row.banks[b])}
            </span>
          </span>
        ))
      ) : (
        <span className="text-neutral-500">no offset data mirrored</span>
      )}
    </div>
  );
}

export function LatheTurretTable({ machine }: { machine: Machine }) {
  const { data, isPending, isError } = useOffsets(machine.id);
  const [showEmpty, setShowEmpty] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  if (isPending) return <p className="text-neutral-500">Loading offsets…</p>;
  if (isError) return <p className="text-status-alarm">Failed to load offsets.</p>;

  const rows = buildRows(data ?? []);
  const active = rows.filter(hasValue);
  const shown = showEmpty ? rows : active;
  const stationCount = machine.pot_count > 0 ? machine.pot_count : 12;
  const latest = rows.reduce<string | null>(
    (acc, r) => (r.lastPolled && (!acc || r.lastPolled > acc) ? r.lastPolled : acc),
    null,
  );

  return (
    <div className="space-y-4">
      <WorkShiftCard machineId={machine.id} />
      <TurretRing
        rows={rows}
        stationCount={stationCount}
        selected={selected}
        onSelect={setSelected}
      />

      <div className="flex flex-wrap items-center gap-3 text-xs text-neutral-500">
        <span className="flex items-center gap-1">
          <span className="inline-block h-3 w-3 rounded-full border-2 border-emerald-500 bg-emerald-950/40" /> geometry set
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-3 w-3 rounded-full border-2 border-amber-500/70 bg-amber-950/30" /> wear/tip only
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-3 w-3 rounded-full border-2 border-dashed border-neutral-700" /> empty
        </span>
      </div>

      {selected != null && (
        <StationDetail row={rows.find((r) => r.register === selected)} station={selected} />
      )}

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

      {shown.length === 0 && <p className="text-neutral-500">No offsets mirrored yet.</p>}

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
                <tr
                  key={r.register}
                  className={cn(
                    "border-b border-neutral-900",
                    selected === r.register && "bg-indigo-950/30",
                  )}
                >
                  <td className="py-1.5 pr-3 text-neutral-400">{r.register}</td>
                  {BANKS.map((b) => {
                    const v = r.banks[b];
                    const zero = num(v) === 0;
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
        Station n shows register n; higher registers are alternate offsets.
      </p>
    </div>
  );
}
