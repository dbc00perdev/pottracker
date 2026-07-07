import { Link, useParams } from "react-router-dom";

import { useTool, useToolAudit } from "@/hooks/useToolDetail";
import { mm, timeAgo } from "@/lib/format";
import type { Tool } from "@/types/api";

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-neutral-500">{label}</dt>
      <dd className="font-mono text-neutral-100">{value}</dd>
    </div>
  );
}

function SpecCard({ tool }: { tool: Tool }) {
  const flags = [
    tool.requires_tsc && "TSC required",
    tool.requires_climb && "climb only",
    tool.is_consumable_class && "consumable",
  ].filter(Boolean) as string[];
  return (
    <section className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-3 text-sm font-medium text-neutral-400">Specification</h2>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Field label="Type" value={tool.tool_type.display_name} />
        <Field label="Diameter" value={`${mm(tool.diameter_mm)} mm`} />
        <Field label="Flutes" value={tool.flute_count?.toString() ?? "—"} />
        <Field label="Corner radius" value={`${mm(tool.corner_radius_mm)} mm`} />
        <Field label="Flute length" value={`${mm(tool.flute_length_mm)} mm`} />
        <Field label="Overall length" value={`${mm(tool.overall_length_mm)} mm`} />
        <Field label="Substrate" value={tool.substrate ?? "—"} />
        <Field label="Coating" value={tool.coating ?? "—"} />
        <Field label="Regrinds" value={tool.regrind_count.toString()} />
        <Field label="Vendor" value={tool.vendor ?? "—"} />
        <Field label="Vendor P/N" value={tool.vendor_part_number ?? "—"} />
      </dl>
      {flags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {flags.map((f) => (
            <span key={f} className="rounded bg-neutral-800 px-2 py-0.5 text-xs text-neutral-300">
              {f}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

function Assignments({ tool }: { tool: Tool }) {
  return (
    <section className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-3 text-sm font-medium text-neutral-400">Active assignments</h2>
      {tool.assignments.length === 0 ? (
        <p className="text-neutral-500">Not assigned to any machine.</p>
      ) : (
        <ul className="space-y-1 font-mono text-sm text-neutral-200">
          {tool.assignments.map((a) => (
            <li key={`${a.machine_id}-${a.t_number}`}>
              {a.machine_name}: T{a.t_number} H{a.h_register}
              {a.d_register != null ? ` D${a.d_register}` : ""}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function AuditSection({ id }: { id: string }) {
  const { data, isPending, isError } = useToolAudit(id);
  return (
    <section className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <h2 className="mb-3 text-sm font-medium text-neutral-400">History</h2>
      {isPending && <p className="text-neutral-500">Loading…</p>}
      {isError && <p className="text-status-alarm">Failed to load history.</p>}
      {data && data.items.length === 0 && (
        <p className="text-neutral-500">No history visible for your role.</p>
      )}
      <ul className="space-y-2">
        {data?.items.map((e) => (
          <li key={e.id} className="flex items-baseline justify-between gap-4 text-sm">
            <span className="text-neutral-200">{e.event_type}</span>
            <span className="font-mono text-xs text-neutral-500">{timeAgo(e.occurred_at)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ToolDetailPage() {
  const { id = "" } = useParams();
  const { data: tool, isPending, isError } = useTool(id);

  return (
    <div className="space-y-4">
      <Link to="/tools" className="text-sm text-neutral-400 hover:underline">
        ← Tools
      </Link>
      {isPending && <p className="text-neutral-500">Loading…</p>}
      {isError && <p className="text-status-alarm">Tool not found.</p>}
      {tool && (
        <>
          <div className="flex items-center gap-3">
            <h1 className="font-mono text-xl font-semibold">{tool.short_id}</h1>
            {tool.retired_at && (
              <span className="rounded bg-neutral-800 px-2 py-0.5 text-xs text-status-idle">
                retired
              </span>
            )}
          </div>
          <SpecCard tool={tool} />
          <Assignments tool={tool} />
          <AuditSection id={id} />
        </>
      )}
    </div>
  );
}
