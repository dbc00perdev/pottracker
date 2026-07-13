import { usePots, useSpindle } from "@/hooks/useMachines";
import { cn } from "@/lib/utils";
import type { Machine, Pot, PotLocation, PotStateValue } from "@/types/api";

// Grid pot map (docs/05 Pot Map tab). Random-ATC: pot is a location, T-number is
// identity read from FOCAS (R10 — observed, not commanded). Occupancy (#3)
// correlates that identity with offset-based presence:
//   loaded     — a measured tool is really there (h_geom offset ≠ 0)
//   empty      — confirmed absent
//   unverified — identity known, but no assignment/offset to confirm presence (R11)
//   probe      — reserved probe pot, never assignable
// `verified` marks a loaded pot whose offset was presetter-attributed (#2).
//
// Spindle/NEXT overlay: identity + presence don't capture LOCATION. A measured
// tool physically in the spindle (HEAD) or on deck (NEXT) has left its pot, yet
// the sticky pot cell still shows its identity there. The overlay draws HEAD/NEXT
// as their own slots and renders the vacated pot as "→ spindle"/"→ next" rather
// than a loaded ghost. HEAD/NEXT come from the persisted status mirror.

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

const LOCATION_LABEL: Record<Exclude<PotLocation, null>, string> = {
  spindle: "→ spindle",
  next: "→ next",
};

export function PotMap({ machine }: { machine: Machine }) {
  const { data: pots, isPending, isError } = usePots(machine.id);
  const { data: spindle } = useSpindle(machine.id);

  if (isPending) return <p className="text-neutral-500">Loading pots…</p>;
  if (isError) return <p className="text-status-alarm">Failed to load pot table.</p>;
  if (!pots || pots.length === 0)
    return <p className="text-neutral-500">No pot data mirrored yet.</p>;

  const byPot = new Map<number, Pot>(pots.map((p) => [p.pot_number, p]));
  const byTool = new Map<number, Pot>(
    pots.filter((p) => p.t_number != null).map((p) => [p.t_number as number, p]),
  );
  const cells = Array.from({ length: machine.pot_count }, (_, i) => i + 1);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <SpindleSlot title="Spindle" kind="spindle" tNumber={spindle?.head_t_number ?? null} pot={
          spindle?.head_t_number != null ? byTool.get(spindle.head_t_number) : undefined
        } />
        <SpindleSlot title="Next" kind="next" tNumber={spindle?.next_t_number ?? null} pot={
          spindle?.next_t_number != null ? byTool.get(spindle.next_t_number) : undefined
        } />
      </div>

      <div className="grid grid-cols-4 gap-2 sm:grid-cols-6 md:grid-cols-8">
        {cells.map((potNumber) => {
          const pot = byPot.get(potNumber);
          // A pot the mirror hasn't observed yet (no row) — distinct from "empty".
          // The server classifies the probe pot dynamically (whichever pot holds
          // the probe T#, since it floats); trust `pot.state`, never a fixed pot.
          const state: PotStateValue = pot?.state ?? "empty";
          const location = state === "probe" ? null : (pot?.location ?? null);
          const style = STATE_STYLE[state];
          const t = pot?.t_number ?? null;
          // Vacated: the tool is physically elsewhere (spindle/next), so never
          // render it "loaded" — show where it went instead.
          const vacated = location != null;
          const showTool = !vacated && state !== "probe" && t != null && state !== "empty";
          const label =
            state === "probe"
              ? "probe"
              : vacated
                ? LOCATION_LABEL[location]
                : showTool
                  ? `T${t}`
                  : "empty";
          const aria =
            `Pot ${potNumber} ` +
            (vacated ? `tool T${t} ${LOCATION_LABEL[location].replace("→ ", "in ")}` : style.label) +
            (showTool ? ` tool T${t}` : "") +
            (!vacated && pot?.verified ? " presetter-verified" : "");

          return (
            <div
              key={potNumber}
              title={
                vacated && t != null
                  ? `T${t} moved ${LOCATION_LABEL[location].replace("→ ", "to ")}`
                  : pot?.assigned_h_register != null
                    ? `H${pot.assigned_h_register}${pot.offset_mm != null ? ` = ${pot.offset_mm} mm` : ""}`
                    : undefined
              }
              className={cn(
                "relative flex min-h-[64px] flex-col items-center justify-center rounded-md border bg-neutral-900 p-2 text-center",
                vacated ? "border-dashed border-status-ok/40" : style.border,
                state === "empty" && !vacated && "bg-neutral-950",
              )}
              aria-label={aria}
            >
              <span className="font-mono text-xs text-neutral-500">#{potNumber}</span>
              <span
                className={cn(
                  "font-mono text-sm",
                  vacated ? "text-status-ok/70" : style.text,
                )}
              >
                {label}
              </span>
              {vacated && t != null && (
                <span className="font-mono text-[10px] text-neutral-600">T{t}</span>
              )}
              {!vacated && pot?.verified && (
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

function SpindleSlot({
  title,
  kind,
  tNumber,
  pot,
}: {
  title: string;
  kind: "spindle" | "next";
  tNumber: number | null;
  pot: Pot | undefined;
}) {
  const accent = kind === "spindle" ? "border-status-ok text-status-ok" : "border-status-warn text-status-warn";
  return (
    <div
      className={cn(
        "flex min-w-[104px] flex-col items-center justify-center rounded-md border-2 bg-neutral-900 px-3 py-2 text-center",
        accent,
      )}
      aria-label={
        tNumber != null ? `${title}: tool T${tNumber}` : `${title}: none`
      }
    >
      <span className="text-[10px] uppercase tracking-wide text-neutral-500">{title}</span>
      <span className="font-mono text-base">{tNumber != null ? `T${tNumber}` : "—"}</span>
      {tNumber != null && pot?.verified && (
        <span className="text-[10px] text-status-ok" title="presetter-verified">
          ✓ verified
        </span>
      )}
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
        <span className="text-status-ok/70">→ spindle / → next</span>
        <span>— tool moved out of its pot</span>
      </span>
      <span className="flex items-center gap-1">
        <span className="text-status-ok">✓</span> presetter-verified
      </span>
    </div>
  );
}
