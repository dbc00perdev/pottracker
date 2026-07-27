import { useMemo, useState } from "react";

import {
  filterActiveLoadout,
  type ActiveLoadoutRow,
  type LoadoutStatus,
} from "@/features/machines/activeLoadout";
import { cn } from "@/lib/utils";

// Phase-2 active loadout: only tools on the machine + local search.
// Hover/click cross-link with the ring via t_number (parent owns hoverT).

export function ActiveLoadoutTable({
  rows,
  hoverT,
  onHoverT,
  onActivateT,
}: {
  rows: ActiveLoadoutRow[];
  hoverT: number | null;
  onHoverT: (t: number | null) => void;
  onActivateT: (t: number) => void;
}) {
  const [q, setQ] = useState("");
  const filtered = useMemo(() => filterActiveLoadout(rows, q), [rows, q]);

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-950/40 p-4">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral-500">
        Active on machine — {filtered.length}
        {q.trim() ? ` / ${rows.length}` : ""} tools
      </h2>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-emerald-500/40 bg-emerald-950/50 px-2.5 py-1 text-[11px] text-emerald-300">
          filter: on machine
        </span>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search T · H/N · type · label · EDP…"
          aria-label="Search active loadout"
          className="min-h-[44px] min-w-[180px] flex-1 rounded-md border border-neutral-700 bg-neutral-950 px-3 font-mono text-sm outline-none focus:border-sky-500"
        />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-[12.5px]">
          <thead>
            <tr className="text-[10.5px] uppercase tracking-wide text-neutral-500">
              <th className="border-b border-neutral-800 px-2 py-1.5 font-semibold">Where</th>
              <th className="border-b border-neutral-800 px-2 py-1.5 font-semibold">T</th>
              <th className="border-b border-neutral-800 px-2 py-1.5 font-semibold">H/N</th>
              <th className="border-b border-neutral-800 px-2 py-1.5 font-semibold">Type</th>
              <th className="border-b border-neutral-800 px-2 py-1.5 font-semibold">Label</th>
              <th className="border-b border-neutral-800 px-2 py-1.5 font-semibold">MFR / EDP</th>
              <th className="border-b border-neutral-800 px-2 py-1.5 font-semibold">Shank</th>
              <th className="border-b border-neutral-800 px-2 py-1.5 font-semibold" />
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <tr
                key={r.t_number}
                data-t={r.t_number}
                tabIndex={0}
                onMouseEnter={() => onHoverT(r.t_number)}
                onMouseLeave={() => onHoverT(null)}
                onClick={() => onActivateT(r.t_number)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onActivateT(r.t_number);
                  }
                }}
                className={cn(
                  "cursor-pointer border-b border-neutral-900",
                  (r.status === "pending" || r.status === "no_record") && "bg-slate-900/80",
                  hoverT === r.t_number && "bg-cyan-950/40",
                )}
              >
                <td className="px-2 py-1.5">{whereCell(r)}</td>
                <td className="px-2 py-1.5 font-mono font-bold">T{r.t_number}</td>
                <td className="px-2 py-1.5 font-mono text-neutral-400">
                  {r.n_register != null ? `H${r.n_register}` : "—"}
                </td>
                <td className="px-2 py-1.5">
                  {r.type_label ? (
                    <TypeTag code={r.type_code} label={r.type_label} />
                  ) : (
                    <span className="text-neutral-600">—</span>
                  )}
                </td>
                <td className="max-w-[220px] px-2 py-1.5">
                  {r.description || r.short_id ? (
                    <span title={r.short_id ?? undefined}>
                      {r.description ?? r.short_id}
                    </span>
                  ) : (
                    <span className="text-rose-300/90">no crib record</span>
                  )}
                </td>
                <td className="max-w-[180px] px-2 py-1.5 font-mono text-[11px] text-neutral-500">
                  {mfrEdp(r)}
                </td>
                <td className="whitespace-nowrap px-2 py-1.5 font-mono text-[11px] text-neutral-500">
                  {r.shank_mm != null ? `${r.shank_mm}` : "—"}
                </td>
                <td className="px-2 py-1.5">{statusBadge(r.status)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <p className="py-6 text-center text-sm text-neutral-500">
            {rows.length === 0
              ? "No tools currently on the machine."
              : "No active tools match that search."}
          </p>
        )}
      </div>

      <p className="mt-3 text-xs leading-relaxed text-neutral-500">
        On-machine tools only — full crib is under Tools. T = pot/program identity;
        H/N = offset register when assigned. NO REC = machine has identity, app has no tool.
      </p>
    </div>
  );
}

function whereCell(r: ActiveLoadoutRow) {
  if (r.whereKind === "spindle") {
    return (
      <span className="rounded-full border border-cyan-400/50 px-1.5 py-0.5 text-[9.5px] font-bold text-cyan-300">
        SPINDLE
      </span>
    );
  }
  if (r.whereKind === "next") {
    return (
      <span className="rounded-full border border-sky-400/50 px-1.5 py-0.5 text-[9.5px] font-bold text-sky-300">
        NEXT
      </span>
    );
  }
  return <span className="text-neutral-500">pot {r.pot_number}</span>;
}

function TypeTag({ code, label }: { code: string | null; label: string }) {
  const short = shortType(code, label);
  const color = typeColor(code, label);
  return (
    <span
      className={cn(
        "rounded-full border px-1.5 py-0.5 text-[9.5px] font-bold whitespace-nowrap",
        color,
      )}
    >
      {short}
    </span>
  );
}

function shortType(code: string | null, label: string): string {
  const c = (code ?? "").toLowerCase();
  if (c.includes("drill") && !c.includes("spot")) return "DRILL";
  if (c.includes("spot")) return "SPOT";
  if (c.includes("tap")) return "TAP";
  if (c.includes("ream")) return "REAM";
  if (c.includes("probe")) return "PROBE";
  if (c.includes("ball")) return "BALL EM";
  if (c.includes("corner") || c.includes("radius")) return "CR EM";
  if (c.includes("chamfer")) return "CHMF";
  if (c.includes("em") || c.includes("mill") || c.includes("end")) return "SQ EM";
  return label.length > 10 ? label.slice(0, 10) : label;
}

function typeColor(code: string | null, label: string): string {
  const s = `${code ?? ""} ${label}`.toLowerCase();
  if (s.includes("probe")) return "border-violet-400 text-violet-300";
  if (s.includes("tap")) return "border-indigo-400/60 text-indigo-300";
  if (s.includes("ream")) return "border-emerald-400/70 text-emerald-300";
  if (s.includes("drill") || s.includes("spot")) return "border-sky-400/70 text-sky-300";
  // End mills / default — teal, not orange
  return "border-teal-400/60 text-teal-300";
}

function mfrEdp(r: ActiveLoadoutRow): string {
  if (!r.manufacturer && !r.edp_number) return "—";
  if (r.manufacturer && r.edp_number) return `${r.manufacturer} · ${r.edp_number}`;
  return r.manufacturer ?? r.edp_number ?? "—";
}

function statusBadge(status: LoadoutStatus) {
  // Cool accents only — no amber/orange (that competes with the ring).
  if (status === "no_record") {
    return (
      <span className="rounded-full border border-rose-400/60 px-1.5 py-0.5 text-[9.5px] font-bold text-rose-300">
        NO REC
      </span>
    );
  }
  if (status === "pending") {
    return (
      <span className="rounded-full border border-indigo-400/60 px-1.5 py-0.5 text-[9.5px] font-bold text-indigo-300">
        VERIFY
      </span>
    );
  }
  if (status === "probe") {
    return (
      <span className="rounded-full border border-violet-400 px-1.5 py-0.5 text-[9.5px] font-bold text-violet-300">
        PROBE
      </span>
    );
  }
  if (status === "unverified") {
    return (
      <span className="rounded-full border border-slate-500 px-1.5 py-0.5 text-[9.5px] font-bold text-slate-300">
        UNVER
      </span>
    );
  }
  return <span className="text-emerald-400">✓</span>;
}
