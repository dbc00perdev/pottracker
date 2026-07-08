import { usePots } from "@/hooks/useMachines";
import { cn } from "@/lib/utils";
import type { Machine, Pot, PotStateValue } from "@/types/api";

// Grid pot map (docs/05 Pot Map tab). Random-ATC: pot is a location, T-number is
// identity read from FOCAS (R10 — observed, not commanded). Occupancy (#3)
// correlates that identity with offset-based presence:
//   loaded     — a measured tool is really there (h_geom offset ≠ 0)
//   empty      — confirmed absent
//   unverified — identity known, but no assignment/offset to confirm presence (R11)
//   probe      — reserved probe pot, never assignable
// `verified` marks a loaded pot whose offset was presetter-attributed (#2).

type CellStyle = { border: string; label: string; text: string };

const STATE_STYLE: Record<PotStateValue, CellStyle> = {
  loaded: { border: "border-status-ok", label: "loaded", text: "text-neutral-100" },
  empty: { border: "border-dashed border-neutral-800", label: "empty", text: "text-neutral-600" },
  unverified: {
    border: "border-dashed border-status-warn",
    label: "unverified",
    text: "text-status-warn",
  },
  probe: { border: "border-status-warn", label: "probe", text: "text-status-warn" },
};

export function PotMap({ machine }: { machine: Machine }) {
  const { data: pots, isPending, isError } = usePots(machine.id);

  if (isPending) return <p className="text-neutral-500">Loading pots…</p>;
  if (isError) return <p className="text-status-alarm">Failed to load pot table.</p>;
  if (!pots || pots.length === 0)
    return <p className="text-neutral-500">No pot data mirrored yet.</p>;

  const byPot = new Map<number, Pot>(pots.map((p) => [p.pot_number, p]));
  const cells = Array.from({ length: machine.pot_count }, (_, i) => i + 1);

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-4 gap-2 sm:grid-cols-6 md:grid-cols-8">
        {cells.map((potNumber) => {
          const pot = byPot.get(potNumber);
          // A pot the mirror hasn't observed yet (no row) — distinct from "empty".
          const state: PotStateValue =
            machine.probe_pot === potNumber ? "probe" : (pot?.state ?? "empty");
          const style = STATE_STYLE[state];
          const t = pot?.t_number ?? null;
          const showTool = state !== "probe" && t != null && state !== "empty";
          const label =
            state === "probe"
              ? "probe"
              : showTool
                ? `T${t}`
                : "empty";
          const aria =
            `Pot ${potNumber} ${style.label}` +
            (showTool ? ` tool T${t}` : "") +
            (pot?.verified ? " presetter-verified" : "");

          return (
            <div
              key={potNumber}
              title={
                pot?.assigned_h_register != null
                  ? `H${pot.assigned_h_register}${pot.offset_mm != null ? ` = ${pot.offset_mm} mm` : ""}`
                  : undefined
              }
              className={cn(
                "relative flex min-h-[64px] flex-col items-center justify-center rounded-md border bg-neutral-900 p-2 text-center",
                style.border,
                state === "empty" && "bg-neutral-950",
              )}
              aria-label={aria}
            >
              <span className="font-mono text-xs text-neutral-500">#{potNumber}</span>
              <span className={cn("font-mono text-sm", style.text)}>{label}</span>
              {pot?.verified && (
                <span
                  className="absolute right-1 top-1 text-status-ok"
                  aria-hidden
                  title="presetter-verified"
                >
                  ✓
                </span>
              )}
            </div>
          );
        })}
      </div>
      <PotLegend />
    </div>
  );
}

function PotLegend() {
  const items: { state: PotStateValue; desc: string }[] = [
    { state: "loaded", desc: "measured tool present" },
    { state: "unverified", desc: "identity only — presence unconfirmed" },
    { state: "empty", desc: "no tool" },
    { state: "probe", desc: "reserved" },
  ];
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500">
      {items.map(({ state, desc }) => (
        <span key={state} className="flex items-center gap-1.5">
          <span
            className={cn("inline-block h-3 w-3 rounded-sm border bg-neutral-900", STATE_STYLE[state].border)}
          />
          <span className={STATE_STYLE[state].text}>{STATE_STYLE[state].label}</span>
          <span>— {desc}</span>
        </span>
      ))}
      <span className="flex items-center gap-1">
        <span className="text-status-ok">✓</span> presetter-verified
      </span>
    </div>
  );
}
