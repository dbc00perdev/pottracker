import { usePots } from "@/hooks/useMachines";
import { cn } from "@/lib/utils";
import type { Machine } from "@/types/api";

// Grid pot map (docs/05 Pot Map tab). Random-ATC: pot is a location, T-number is
// identity read from FOCAS (R10 — observed, not commanded). Probe pot is marked
// distinctly and never assignable.
export function PotMap({ machine }: { machine: Machine }) {
  const { data: pots, isPending, isError } = usePots(machine.id);

  if (isPending) return <p className="text-neutral-500">Loading pots…</p>;
  if (isError) return <p className="text-status-alarm">Failed to load pot table.</p>;
  if (!pots || pots.length === 0)
    return <p className="text-neutral-500">No pot data mirrored yet.</p>;

  const byPot = new Map(pots.map((p) => [p.pot_number, p.t_number]));
  const cells = Array.from({ length: machine.pot_count }, (_, i) => i + 1);

  return (
    <div className="grid grid-cols-4 gap-2 sm:grid-cols-6 md:grid-cols-8">
      {cells.map((pot) => {
        const t = byPot.get(pot) ?? null;
        const isProbe = machine.probe_pot === pot;
        return (
          <div
            key={pot}
            className={cn(
              "flex min-h-[64px] flex-col items-center justify-center rounded-md border p-2 text-center",
              isProbe
                ? "border-status-warn bg-neutral-900"
                : t != null
                  ? "border-neutral-700 bg-neutral-900"
                  : "border-dashed border-neutral-800 bg-neutral-950",
            )}
            aria-label={`Pot ${pot}${isProbe ? " probe" : t != null ? ` tool T${t}` : " empty"}`}
          >
            <span className="font-mono text-xs text-neutral-500">#{pot}</span>
            {isProbe ? (
              <span className="font-mono text-sm text-status-warn">probe</span>
            ) : t != null ? (
              <span className="font-mono text-sm text-neutral-100">T{t}</span>
            ) : (
              <span className="text-xs text-neutral-600">empty</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
