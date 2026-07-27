import type { ReactNode } from "react";

import type { ActiveLoadoutRow } from "@/features/machines/activeLoadout";
import { cn } from "@/lib/utils";

// Phase-3 sticky detail drawer (click). Actions gated / stubbed for later writes.

export function ToolDetailDrawer({
  row,
  open,
  onClose,
}: {
  row: ActiveLoadoutRow | null;
  open: boolean;
  onClose: () => void;
}) {
  if (!open || row == null) return null;

  const statusLabel =
    row.status === "no_record"
      ? "NO REC — machine identity only"
      : row.status === "pending"
        ? "VERIFY — pending review"
        : row.status === "probe"
          ? "PROBE"
          : row.status === "unverified"
            ? "UNVERIFIED — presence unconfirmed"
            : row.potVerified
              ? "Verified (presetter)"
              : "On file";

  return (
    <>
      <button
        type="button"
        className="fixed inset-0 z-40 bg-black/55"
        aria-label="Close detail"
        onClick={onClose}
      />
      <aside
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-neutral-800 bg-neutral-900 p-5 shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tool-detail-title"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-neutral-500">Detail</div>
            <h2 id="tool-detail-title" className="font-mono text-2xl font-bold">
              T{row.t_number}
              {row.n_register != null && (
                <span className="ml-2 text-base font-semibold text-neutral-400">
                  H{row.n_register}
                </span>
              )}
            </h2>
            <p className="mt-1 text-sm text-neutral-400">
              {row.description ?? row.short_id ?? "No crib record"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="min-h-[44px] rounded-md border border-neutral-600 px-3 text-sm"
          >
            Close
          </button>
        </div>

        <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-2 text-sm">
          <Dt>Where</Dt>
          <Dd>{row.where}</Dd>
          <Dt>Pot</Dt>
          <Dd>
            {row.pot_number != null
              ? String(row.pot_number)
              : row.whereKind === "spindle"
                ? "vacated → spindle"
                : "—"}
          </Dd>
          <Dt>Type</Dt>
          <Dd>{row.type_label ?? "—"}</Dd>
          <Dt>GTID</Dt>
          <Dd className="font-mono">{row.short_id ?? "—"}</Dd>
          <Dt>MFR / EDP</Dt>
          <Dd className="font-mono text-neutral-400">
            {[row.manufacturer, row.edp_number].filter(Boolean).join(" · ") || "—"}
          </Dd>
          <Dt>Shank</Dt>
          <Dd className="font-mono">{row.shank_mm ?? "—"}</Dd>
          <Dt>Status</Dt>
          <Dd
            className={cn(
              row.status === "no_record"
                ? "text-rose-300"
                : row.status === "pending" || row.status === "unverified"
                  ? "text-indigo-300"
                  : row.status === "probe"
                    ? "text-violet-300"
                    : "text-emerald-300",
            )}
          >
            {statusLabel}
          </Dd>
        </dl>

        <p className="mt-6 text-xs leading-relaxed text-neutral-500">
          Spindle is always the hub (cyan). NEXT sits at 6 o&apos;clock when known (sky).
          Offset write actions stay gated until the FOCAS write path is live.
        </p>

        <div className="mt-auto flex flex-wrap gap-2 pt-6">
          <button
            type="button"
            disabled
            title="Requires confirm path — not in this phase"
            className="min-h-[44px] rounded-md border border-cyan-800/50 px-3 text-sm text-cyan-500/50"
          >
            Confirm review
          </button>
          <button
            type="button"
            disabled
            title="Open full tool page — later"
            className="min-h-[44px] rounded-md border border-neutral-700 px-3 text-sm text-neutral-500"
          >
            Open tool
          </button>
        </div>
      </aside>
    </>
  );
}

function Dt({ children }: { children: ReactNode }) {
  return <dt className="text-neutral-500">{children}</dt>;
}
function Dd({ children, className }: { children: ReactNode; className?: string }) {
  return <dd className={cn("text-neutral-100", className)}>{children}</dd>;
}
