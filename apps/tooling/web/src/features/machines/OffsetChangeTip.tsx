// Hover detail for an offset value: when it last changed, old → new, and
// presetter-vs-manual attribution (#2). Data = the offset_change audit trail
// via /machines/{id}/offset-changes; a register with no audit row predates
// the poller or has never changed — shown honestly, never guessed (R11).

import type { ReactNode } from "react";

import { timeAgo } from "@/lib/format";
import type { OffsetChange } from "@/types/api";

export function changeKey(register: number, type: string): string {
  return `${register}/${type}`;
}

export function buildChangeMap(changes: OffsetChange[] | undefined): Map<string, OffsetChange> {
  const map = new Map<string, OffsetChange>();
  for (const c of changes ?? []) map.set(changeKey(c.register_number, c.register_type), c);
  return map;
}

const SOURCE_LABELS: Record<string, { label: string; className: string }> = {
  presetter_verified: { label: "presetter-verified", className: "text-emerald-400" },
  manual_edit: { label: "manual edit", className: "text-amber-400" },
};

function TipBody({ change }: { change: OffsetChange | undefined }) {
  if (!change) {
    return <span className="text-neutral-500">no change recorded</span>;
  }
  const source = change.source ? SOURCE_LABELS[change.source] : null;
  if (change.old_value === null) {
    return (
      <>
        <span className="text-neutral-400">first observed {timeAgo(change.changed_at)}</span>
        {change.new_value !== null && (
          <span className="block text-neutral-200">{change.new_value}</span>
        )}
      </>
    );
  }
  return (
    <>
      <span className="block text-neutral-200">
        {change.old_value} <span className="text-neutral-500">→</span> {change.new_value}
      </span>
      <span className="block text-neutral-400">{timeAgo(change.changed_at)}</span>
      {source && <span className={`block ${source.className}`}>{source.label}</span>}
    </>
  );
}

export function OffsetChangeTip({
  change,
  children,
}: {
  change: OffsetChange | undefined;
  children: ReactNode;
}) {
  return (
    <span className="group/tip relative inline-block cursor-help underline decoration-dotted decoration-neutral-700 underline-offset-4">
      {children}
      <span
        role="tooltip"
        className="pointer-events-none invisible absolute bottom-full left-1/2 z-30 mb-1.5
                   w-max max-w-[240px] -translate-x-1/2 whitespace-nowrap rounded border
                   border-neutral-700 bg-neutral-900 px-2.5 py-1.5 text-left font-mono
                   text-xs shadow-xl group-hover/tip:visible group-focus-within/tip:visible"
      >
        <TipBody change={change} />
      </span>
    </span>
  );
}
